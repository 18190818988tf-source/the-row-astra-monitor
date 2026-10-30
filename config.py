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
        for key in ("id", "brand", "name", "url", "adapter"):
            if not isinstance(product.get(key), str) or not product[key].strip():
                raise ValueError(f"Product requires a non-empty {key}")
        if product["adapter"] == "shopify" and (not isinstance(product.get("sku"), str) or not product["sku"].strip()):
            raise ValueError("Fixed Shopify product requires a non-empty sku")
        if product["adapter"] == "jsonld_product":
            for key in ("sku", "size", "product_group_id"):
                if not isinstance(product.get(key), str) or not product[key].strip():
                    raise ValueError(f"JSON-LD product requires a non-empty {key}")
        if product["adapter"] == "arcteryx_catalog":
            urls = product.get("catalog_urls")
            if not isinstance(urls, list) or not urls:
                raise ValueError("Arc'teryx catalog requires catalog_urls")
            for catalog_url in urls:
                parsed = urlsplit(catalog_url) if isinstance(catalog_url, str) else None
                if not parsed or parsed.scheme != "https" or parsed.hostname != "outlet.arcteryx.com":
                    raise ValueError("Invalid Arc'teryx catalog URL")
            threshold = product.get("bulk_threshold", 5)
            if not isinstance(threshold, int) or threshold < 2:
                raise ValueError("bulk_threshold must be an integer of at least 2")
        if product["adapter"] == "shopify_search" and urlsplit(product["url"]).path.rstrip("/") != "/search":
            raise ValueError("Shopify search source URL must use /search")
        excluded = product.get("exclude_handles", [])
        if not isinstance(excluded, list) or any(not isinstance(handle, str) or not handle.strip()
                                                   for handle in excluded):
            raise ValueError("exclude_handles must be a list of non-empty product handles")
        if product["id"] in ids:
            raise ValueError(f"Duplicate product id {product['id']}")
        ids.add(product["id"])
        url = urlsplit(product["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError(f"Invalid HTTPS product URL: {product['id']}")
        if product.get("enabled", True) not in (True, False):
            raise ValueError("enabled must be boolean")
    return [p for p in products if p.get("enabled", True)]
