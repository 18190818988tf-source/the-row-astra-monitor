"""Validated product manifest for multi-store monitoring."""
import json
from pathlib import Path
from urllib.parse import urlsplit


def load_products(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema_version") != 1:
        raise ValueError("Unsupported products.json schema_version")
    products = doc.get("products")
    if not isinstance(products, list):
        raise ValueError("products must be a list")
    ids = set()
    for product in products:
        if not isinstance(product, dict):
            raise ValueError("Each product must be an object")
        for key in ("id", "brand", "name", "url", "adapter", "sku"):
            if not isinstance(product.get(key), str) or not product[key].strip():
                raise ValueError(f"Product requires a non-empty {key}")
        if product["id"] in ids:
            raise ValueError(f"Duplicate product id {product['id']}")
        ids.add(product["id"])
        url = urlsplit(product["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError(f"Invalid HTTPS product URL: {product['id']}")
        if product.get("enabled", True) not in (True, False):
            raise ValueError("enabled must be boolean")
    return [p for p in products if p.get("enabled", True)]
