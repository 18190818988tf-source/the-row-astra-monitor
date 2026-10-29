import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adapters.shopify import endpoint, evaluate
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


if __name__ == '__main__': unittest.main()
