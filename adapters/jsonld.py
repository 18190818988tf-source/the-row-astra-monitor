"""Strict variant inventory checks from a retailer's official JSON-LD."""
import json
from html.parser import HTMLParser
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class _JsonLdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = False
        self.buffer = []
        self.documents = []

    def handle_starttag(self, tag, attrs):
        if tag.casefold() == "script" and dict(attrs).get("type", "").casefold() == "application/ld+json":
            self.capture = True
            self.buffer = []

    def handle_data(self, data):
        if self.capture:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag.casefold() == "script" and self.capture:
            self.capture = False
            raw = "".join(self.buffer).strip()
            if raw:
                try:
                    self.documents.append(json.loads(raw))
                except ValueError:
                    pass


def parse_jsonld_variant(product, html):
    """Return (status, proof) for one exact JSON-LD SKU and expected size."""
    parser = _JsonLdParser()
    parser.feed(html)
    variants = []
    for document in parser.documents:
        documents = document if isinstance(document, list) else [document]
        for node in documents:
            if not isinstance(node, dict) or node.get("@type") != "ProductGroup":
                continue
            if product.get("product_group_id") and str(node.get("productGroupID")) != product["product_group_id"]:
                continue
            variants.extend(node.get("hasVariant") or [])
    matches = [variant for variant in variants if isinstance(variant, dict)
               and str(variant.get("sku") or "").strip().upper() == product["sku"].strip().upper()]
    if len(matches) != 1:
        return "unknown", f"Expected 1 matching JSON-LD SKU, got {len(matches)}"
    variant = matches[0]
    if str(variant.get("size") or "").strip().casefold() != product["size"].strip().casefold():
        return "unknown", "JSON-LD size mismatch"
    if product.get("color") and str(variant.get("color") or "").strip().casefold() != product["color"].strip().casefold():
        return "unknown", "JSON-LD color mismatch"
    offers = variant.get("offers")
    if not isinstance(offers, dict):
        return "unknown", "JSON-LD offer missing"
    availability = str(offers.get("availability") or "").rstrip("/").rsplit("/", 1)[-1]
    if availability in ("InStock", "LimitedAvailability"):
        return "in_stock", f"Official JSON-LD SKU {product['sku']} availability={availability}"
    if availability == "OutOfStock":
        return "out_of_stock", f"Official JSON-LD SKU {product['sku']} availability=OutOfStock"
    return "unknown", f"Unrecognized JSON-LD availability={availability or 'missing'}"


def check_jsonld_product(product):
    req = Request(product["url"], headers={
        "User-Agent": "Mozilla/5.0 (compatible; PersonalInventoryMonitor/1.0)",
        "Accept": "text/html", "Cache-Control": "no-store"
    })
    try:
        with urlopen(req, timeout=20) as response:
            try:
                raw = response.read(4 * 1024 * 1024 + 1)
            except IncompleteRead as exc:
                raw = exc.partial
        if len(raw) > 4 * 1024 * 1024:
            return "unknown", "Product page exceeds size limit"
        return parse_jsonld_variant(product, raw.decode("utf-8", errors="replace"))
    except (HTTPError, URLError, IncompleteRead, ValueError, OSError, TimeoutError) as exc:
        return "unknown", f"JSON-LD endpoint failed: {type(exc).__name__}"
