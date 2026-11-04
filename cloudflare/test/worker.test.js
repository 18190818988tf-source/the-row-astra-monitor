import test from "node:test";
import assert from "node:assert/strict";
import { compareCatalog, expandShopifyProduct, parseCatalog, parseJsonLdVariant, searchProductUrls } from "../src/worker.js";

test("discovers same-store Shopify links and excludes handles", () => {
  const html = '<a href="/products/astra-black">A</a><a href="https://evil.test/products/no">X</a><a href="/products/pouch">P</a>';
  assert.deepEqual(searchProductUrls("https://www.therow.com/search?q=astra", html, ["pouch"]),
    ["https://www.therow.com/products/astra-black"]);
});

test("expands Shopify variants", () => {
  const source = { id: "astra", brand: "The Row", name: "Astra" };
  const data = { handle: "astra-black", title: "Astra", variants: [{ id: 12, sku: "SKU12", available: false, option1: "Black", option2: "One Size" }] };
  const [item] = expandShopifyProduct(source, "https://www.therow.com/products/astra-black", data);
  assert.equal(item.id, "astra:astra-black:12");
  assert.equal(item.available, false);
});

test("parses exact JSON-LD SKU", () => {
  const source = { product_group_id: "G1", sku: "S1", size: "S", color: "Grey" };
  const doc = { "@type": "ProductGroup", productGroupID: "G1", hasVariant: [{ sku: "S1", size: "S", color: "Grey", offers: { availability: "https://schema.org/InStock" } }] };
  const html = `<script type="application/ld+json">${JSON.stringify(doc)}</script>`;
  assert.equal(parseJsonLdVariant(source, html)[0], "in_stock");
});

test("parses catalog and detects changes", () => {
  const doc = { props: { pageProps: { initialProductList: [{ id: 1, name: "Beta", url: "womens/beta", price: 500, discountPrice: 350 }] } } };
  const current = parseCatalog("https://outlet.arcteryx.com/us/en/c/womens", `<script id="__NEXT_DATA__">${JSON.stringify(doc)}</script>`);
  assert.equal(current["womens/beta"].discount_price, 350);
  const prior = { "womens/beta": { ...current["womens/beta"], discount_price: 400 } };
  assert.equal(compareCatalog(prior, current, 5).priceChanges.length, 1);
});
