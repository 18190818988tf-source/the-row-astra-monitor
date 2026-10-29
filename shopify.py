"""Strict SKU-level inventory check for Shopify public product JSON.

Treat missing, blocked or conflicting data as UNKNOWN. Never infer a restock
from general page text, cached search results, or other products.
"""
import json
import os
from urllib.error import URLError, HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


class StockError(Exception):
    pass


def endpoint(url):
    p = urlsplit(url)
    if not p.path.rstrip("/").startswith("/products/"):
        raise StockError("Shopify product URL must contain /products/<handle>")
    return urlunsplit((p.scheme, p.netloc, p.path.rstrip("/") + ".js", "", ""))


def evaluate(product, data):
    """Return (status, proof), status: in_stock/out_of_stock/unknown."""
    if not isinstance(data, dict):
        return "unknown", "Not a Shopify JSON object"
    target_handle = urlsplit(product["url"]).path.rstrip("/").rsplit("/", 1)[-1]
    if data.get("handle") != target_handle:
        return "unknown", "Wrong product handle"
    variants = data.get("variants")
    if not isinstance(variants, list):
        return "unknown", "No variants array"
    matches = [v for v in variants if isinstance(v, dict)
               and str(v.get("sku") or "").strip().upper() == product["sku"].strip().upper()]
    if len(matches) != 1:
        return "unknown", f"Expected 1 matching SKU, got {len(matches)}"
    variant = matches[0]
    if type(variant.get("available")) is not bool:
        return "unknown", "Variant availability is missing or nonboolean"
    product_availability = data.get("available")
    if type(product_availability) is bool and product_availability != variant["available"]:
        # Shopify products with multiple variants can be available when target variant is not;
        # only a target IN-STOCK flag can be invalidated by disagreement if product says false.
        if variant["available"]:
            return "unknown", "Product unavailable while target SKU claims stock"
    for option, expected in (("option1", product.get("color")), ("option2", product.get("size"))):
        if expected and str(variant.get(option) or "").strip().casefold() != expected.strip().casefold():
            return "unknown", f"{option} mismatch"
    result = "in_stock" if variant["available"] else "out_of_stock"
    return result, f"Official Shopify JSON SKU {product['sku']} available={str(variant['available']).lower()}"


def check_shopify(product):
    url = endpoint(product["url"])
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; PersonalInventoryMonitor/1.0)",
        "Accept": "application/json", "Cache-Control": "no-store"
    })
    try:
        with urlopen(req, timeout=16) as r:
            data = json.load(r)
        return evaluate(product, data)
    except (HTTPError, URLError, ValueError, OSError, TimeoutError) as e:
        return "unknown", f"Shopify endpoint failed: {type(e).__name__}"
