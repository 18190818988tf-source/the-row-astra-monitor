"""Shopify product checks plus dynamic search-page discovery.

Treat missing, blocked or conflicting data as UNKNOWN. Never infer a restock
from general page text: search HTML is used only to discover product handles,
while availability always comes from each official product JSON endpoint.
"""
import json
from html.parser import HTMLParser
from http.client import IncompleteRead
from urllib.error import URLError, HTTPError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


class StockError(Exception):
    pass


def endpoint(url):
    p = urlsplit(url)
    if not p.path.rstrip("/").startswith("/products/"):
        raise StockError("Shopify product URL must contain /products/<handle>")
    return urlunsplit((p.scheme, p.netloc, p.path.rstrip("/") + ".js", "", ""))


class _ProductLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.hrefs.append(href)


def search_product_urls(search_url, html, exclude_handles=()):
    """Return unique same-store /products/<handle> URLs from search HTML."""
    parser = _ProductLinkParser()
    parser.feed(html)
    source = urlsplit(search_url)
    results = []
    seen = set()
    excluded = {str(handle).strip().casefold() for handle in exclude_handles}
    for href in parser.hrefs:
        absolute = urlsplit(urljoin(search_url, href))
        parts = [part for part in absolute.path.split("/") if part]
        if absolute.hostname != source.hostname or len(parts) != 2 or parts[0] != "products":
            continue
        if parts[1].casefold() in excluded:
            continue
        clean = urlunsplit((source.scheme, source.netloc, "/products/" + parts[1], "", ""))
        if clean not in seen:
            seen.add(clean)
            results.append(clean)
    return results


def variants_from_product(source, product_url, data):
    """Expand one Shopify product document into independently tracked variants."""
    if not isinstance(data, dict) or not isinstance(data.get("variants"), list):
        raise StockError("Invalid Shopify product JSON")
    handle = urlsplit(product_url).path.rstrip("/").rsplit("/", 1)[-1]
    if data.get("handle") != handle:
        raise StockError("Wrong product handle during discovery")
    title = str(data.get("title") or source["name"]).strip()
    items = []
    for variant in data["variants"]:
        if not isinstance(variant, dict) or variant.get("id") in (None, ""):
            continue
        variant_id = str(variant["id"])
        sku = str(variant.get("sku") or "").strip()
        option1 = str(variant.get("option1") or "").strip()
        option2 = str(variant.get("option2") or "").strip()
        item = {
            "id": f"{source['id']}:{handle}:{variant_id}",
            "brand": source["brand"],
            "name": title,
            "url": f"{product_url}?variant={variant_id}",
            "adapter": "shopify",
            "variant_id": variant_id,
            "sku": sku,
        }
        if option1 and option1.casefold() != "default title":
            item["color"] = option1
        if option2:
            item["size"] = option2
        items.append(item)
    if not items:
        raise StockError("No Shopify variants discovered")
    return items


def _get_json(url, attempts=3):
    last_error = None
    for _ in range(attempts):
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; PersonalInventoryMonitor/1.0)",
            "Accept": "application/json", "Cache-Control": "no-store"
        })
        try:
            with urlopen(req, timeout=16) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise StockError("Shopify product JSON exceeds size limit")
            return json.loads(raw)
        except (HTTPError, URLError, IncompleteRead, ValueError, OSError, TimeoutError) as exc:
            last_error = exc
    raise last_error


def discover_shopify_search(source):
    """Discover every current product and variant linked by a Shopify search page."""
    req = Request(source["url"], headers={
        "User-Agent": "Mozilla/5.0 (compatible; PersonalInventoryMonitor/1.0)",
        "Accept": "text/html", "Cache-Control": "no-store"
    })
    try:
        with urlopen(req, timeout=20) as response:
            try:
                html = response.read(4 * 1024 * 1024 + 1)
            except IncompleteRead as exc:
                # The Row's CDN can close after sending usable HTML but before
                # the advertised compressed length. Product JSON below remains
                # the authoritative source for every availability decision.
                html = exc.partial
        if len(html) > 4 * 1024 * 1024:
            raise StockError("Search page exceeds size limit")
        urls = search_product_urls(source["url"], html.decode("utf-8", errors="replace"),
                                   source.get("exclude_handles", []))
        if not urls:
            raise StockError("Search page returned no product links")
        items = []
        for product_url in urls:
            items.extend(variants_from_product(source, product_url, _get_json(endpoint(product_url))))
        return items
    except StockError:
        raise
    except (HTTPError, URLError, IncompleteRead, ValueError, OSError, TimeoutError) as exc:
        raise StockError(f"Shopify discovery failed: {type(exc).__name__}") from exc


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
    if product.get("variant_id"):
        matches = [v for v in variants if isinstance(v, dict)
                   and str(v.get("id")) == str(product["variant_id"])]
        identity = f"variant {product['variant_id']}"
    else:
        matches = [v for v in variants if isinstance(v, dict)
                   and str(v.get("sku") or "").strip().upper() == product["sku"].strip().upper()]
        identity = f"SKU {product['sku']}"
    if len(matches) != 1:
        return "unknown", f"Expected 1 matching {identity}, got {len(matches)}"
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
    sku = str(variant.get("sku") or "").strip()
    label = f"SKU {sku}" if sku else identity
    return result, f"Official Shopify JSON {label} available={str(variant['available']).lower()}"


def check_shopify(product):
    url = endpoint(product["url"])
    try:
        return evaluate(product, _get_json(url))
    except (StockError, HTTPError, URLError, IncompleteRead, ValueError, OSError, TimeoutError) as e:
        return "unknown", f"Shopify endpoint failed: {type(e).__name__}"
