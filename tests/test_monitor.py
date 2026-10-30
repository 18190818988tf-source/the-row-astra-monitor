import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adapters.shopify import endpoint, evaluate, search_product_urls, variants_from_product
from adapters.jsonld import parse_jsonld_variant
from config import load_products
from monitor import update_one, load_state, save_state

ITEM = {"id":"astra","brand":"The Row","name":"Astra Bag",
        "url":"https://www.therow.com/products/astra-black-ans-1",
        "adapter":"shopify","sku":"W2164L117BLANS1SZ",
        "color":"Black","size":"One Size"}


def payload(available):
    return {"handle":"astra-black-ans-1","available":available,
            "variants":[{"sku":"W2164L117BLANS1SZ","available":available,
                         "option1":"Black","option2":"One Size"}]}


class StockCheckTests(unittest.TestCase):
    def test_endpoint(self):
        self.assertEqual(endpoint(ITEM['url']), ITEM['url'] + '.js')

    def test_in_stock(self):
        self.assertEqual(evaluate(ITEM, payload(True))[0], 'in_stock')

    def test_out_of_stock(self):
        self.assertEqual(evaluate(ITEM, payload(False))[0], 'out_of_stock')

    def test_sku_mismatch(self):
        data = payload(True); data['variants'][0]['sku'] = 'NOTASTRA'
        self.assertEqual(evaluate(ITEM, data)[0], 'unknown')

    def test_product_mismatch(self):
        data = payload(True); data['handle'] = 'wrong'
        self.assertEqual(evaluate(ITEM, data)[0], 'unknown')

    def test_option_mismatch(self):
        data = payload(True); data['variants'][0]['option1'] = 'White'
        self.assertEqual(evaluate(ITEM, data)[0], 'unknown')

    def test_ambiguous_variant(self):
        data = payload(True); data['variants'].append(data['variants'][0])
        self.assertEqual(evaluate(ITEM, data)[0], 'unknown')

    def test_missing_availability(self):
        data = payload(True); del data['variants'][0]['available']
        self.assertEqual(evaluate(ITEM, data)[0], 'unknown')

    def test_conflicting_flags(self):
        data = payload(True); data['available'] = False
        self.assertEqual(evaluate(ITEM, data)[0], 'unknown')

    def test_search_product_urls_are_unique_and_same_store(self):
        search='https://www.therow.com/search?q=astra&type=product'
        html='''<a href="/products/astra-black?x=1">A</a>
                <a href="https://www.therow.com/products/astra-black">A2</a>
                <a href="https://evil.example/products/fake">bad</a>'''
        self.assertEqual(search_product_urls(search, html),
                         ['https://www.therow.com/products/astra-black'])

    def test_search_product_can_be_excluded_by_handle(self):
        search='https://www.therow.com/search?q=astra&type=product'
        html='''<a href="/products/astra-pouch-nuez-ans">Pouch</a>
                <a href="/products/astra-black-ans-1">Bag</a>'''
        self.assertEqual(search_product_urls(search, html, ['astra-pouch-nuez-ans']),
                         ['https://www.therow.com/products/astra-black-ans-1'])

    def test_dynamic_product_expands_all_variants_without_fixed_sku(self):
        source={"id":"series","brand":"The Row","name":"Astra Series"}
        data={"handle":"astra-black","title":"Astra Bag in Leather","variants":[
            {"id":101,"sku":"SKU1","option1":"Black","option2":"One Size","available":False},
            {"id":102,"sku":"","option1":"Walnut","option2":"One Size","available":True}]}
        items=variants_from_product(source,'https://www.therow.com/products/astra-black',data)
        self.assertEqual(len(items),2)
        self.assertEqual(items[1]['variant_id'],'102')
        self.assertEqual(items[1]['sku'],'')
        self.assertEqual(evaluate(items[1],data)[0],'in_stock')


class JsonLdStockTests(unittest.TestCase):
    def setUp(self):
        self.item={"sku":"X000010516037","size":"XS","color":"Solitude",
                   "product_group_id":"X000010516"}

    def html(self, availability="OutOfStock", size="XS"):
        doc={"@type":"ProductGroup","productGroupID":"X000010516","hasVariant":[{
            "@type":"Product","sku":"X000010516037","size":size,"color":"Solitude",
            "offers":{"@type":"Offer","availability":f"https://schema.org/{availability}"}}]}
        return '<script type="application/ld+json">'+json.dumps(doc)+'</script>'

    def test_jsonld_out_of_stock(self):
        self.assertEqual(parse_jsonld_variant(self.item,self.html())[0],'out_of_stock')

    def test_jsonld_in_stock(self):
        self.assertEqual(parse_jsonld_variant(self.item,self.html('InStock'))[0],'in_stock')

    def test_jsonld_limited_is_in_stock(self):
        self.assertEqual(parse_jsonld_variant(self.item,self.html('LimitedAvailability'))[0],'in_stock')

    def test_jsonld_size_mismatch_is_unknown(self):
        self.assertEqual(parse_jsonld_variant(self.item,self.html(size='S'))[0],'unknown')


class StateTests(unittest.TestCase):
    def test_initial_in_stock_alert_once(self):
        sent = []
        cb=lambda a,b,c: sent.append((a,b,c))
        s, action=update_one(ITEM, {}, 'in_stock', 'evidence', cb, '2026-10-29T00:00:00Z')
        self.assertEqual(action, 'sent')
        self.assertEqual(len(sent), 1)
        s2, action=update_one(ITEM, s, 'in_stock', 'evidence', cb, '2026-10-29T00:05:00Z')
        self.assertEqual(action, 'already_notified')
        self.assertEqual(len(sent), 1)

    def test_back_in_stock_alert_again(self):
        sent = []
        cb=lambda a,b,c: sent.append(a)
        s,_=update_one(ITEM, {}, 'in_stock', 'proof', cb, 't1')
        s,_=update_one(ITEM, s, 'out_of_stock', 'proof', cb, 't2')
        s,action=update_one(ITEM, s, 'in_stock', 'proof', cb, 't3')
        self.assertEqual(action, 'sent'); self.assertEqual(len(sent), 2)

    def test_unknown_does_not_trigger(self):
        cb=lambda *args: self.fail('Should never push')
        s,act=update_one(ITEM, {}, 'unknown', 'HTTP error', cb, 't1')
        self.assertEqual(act, 'unknown')
        self.assertEqual(s['unknown_streak'],1)

    def test_push_failure_retries(self):
        def fail(*args): raise ConnectionError('failed')
        with self.assertRaises(ConnectionError):
            update_one(ITEM, {}, 'in_stock', 'proof', fail, 't1')
        pushes=[]
        s,a=update_one(ITEM, {}, 'in_stock', 'proof', lambda *x:pushes.append(x), 't2')
        self.assertTrue(s['notified_in_stock']); self.assertEqual(len(pushes),1)

    def test_save_load(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.json'; obj={'schema_version':1,'products':{'a':{'last_reliable':'out_of_stock'}}}
            save_state(p,obj)
            self.assertEqual(load_state(p), obj)


class ManifestTests(unittest.TestCase):
    def test_read_products(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'products.json';p.write_text(json.dumps({'schema_version':1,'products':[ITEM]}))
            self.assertEqual(len(load_products(p)),1)

    def test_duplicate_id_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'products.json';p.write_text(json.dumps({'schema_version':1,'products':[ITEM, ITEM]}))
            with self.assertRaises(ValueError): load_products(p)

    def test_disabled_product_not_monitored(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'products.json';p.write_text(json.dumps({'schema_version':1,'products':[dict(ITEM,enabled=False)]}))
            self.assertEqual(load_products(p),[])

    def test_search_source_does_not_require_sku(self):
        source={"id":"astra-series","brand":"The Row","name":"Astra Series",
                "url":"https://www.therow.com/search?q=astra&type=product",
                "adapter":"shopify_search"}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'products.json';p.write_text(json.dumps({'schema_version':1,'products':[source]}))
            self.assertEqual(load_products(p)[0]['adapter'],'shopify_search')

    def test_jsonld_product_requires_size(self):
        item={"id":"beta-xs","brand":"Arc'teryx","name":"Beta","url":"https://example.com/beta",
              "adapter":"jsonld_product","sku":"SKU1","product_group_id":"GROUP1"}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'products.json';p.write_text(json.dumps({'schema_version':1,'products':[item]}))
            with self.assertRaises(ValueError): load_products(p)


if __name__ == '__main__': unittest.main()
