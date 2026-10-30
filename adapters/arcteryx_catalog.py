"""Arc'teryx Outlet catalog snapshots from server-rendered Next.js data."""
import json
from html.parser import HTMLParser
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class CatalogError(Exception):
    pass


class _NextDataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = False
        self.buffer = []
        self.document = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.casefold() == "script" and attrs.get("id") == "__NEXT_DATA__":
            self.capture = True
            self.buffer = []

    def handle_data(self, data):
        if self.capture:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag.casefold() == "script" and self.capture:
            self.capture = False
            self.document = json.loads("".join(self.buffer))


def parse_catalog_html(page_url, html):
    parser = _NextDataParser()
    parser.feed(html)
    try:
        products = parser.document["props"]["pageProps"]["initialProductList"]
    except (TypeError, KeyError):
        raise CatalogError("Catalog Next.js product list missing")
    if not isinstance(products, list) or not products:
        raise CatalogError("Catalog product list is empty")
    snapshot = {}
    for product in products:
        if not isinstance(product, dict):
            continue
        product_id = str(product.get("id") or "").strip()
        slug = str(product.get("url") or product.get("slug") or "").strip()
        name = str(product.get("name") or product.get("marketingName") or "").strip()
        price = product.get("price")
        discount_price = product.get("discountPrice")
        if not product_id or not slug or not name or not isinstance(price, (int, float)):
            continue
        key = slug.strip("/").casefold()
        snapshot[key] = {
            "id": product_id,
            "name": name,
            "url": urljoin(page_url, "/us/en/shop/" + slug.lstrip("/").removeprefix("us/en/shop/")),
            "price": price,
            "discount_price": discount_price if isinstance(discount_price, (int, float)) else price,
        }
    if not snapshot:
        raise CatalogError("Catalog contained no valid products")
    return snapshot


def compare_catalog(previous, current, bulk_threshold):
    """Return new listings and discount changes; empty previous means baseline."""
    if not previous:
        return [], []
    new_keys = sorted(set(current) - set(previous))
    price_changes = []
    for key in sorted(set(current) & set(previous)):
        before, after = previous[key], current[key]
        if before.get("price") != after.get("price") or before.get("discount_price") != after.get("discount_price"):
            price_changes.append({"before": before, "after": after})
    return new_keys if len(new_keys) >= bulk_threshold else [], price_changes


def fetch_arcteryx_catalog(source):
    snapshot = {}
    for page_url in source["catalog_urls"]:
        req = Request(page_url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; PersonalInventoryMonitor/1.0)",
            "Accept": "text/html", "Cache-Control": "no-store"
        })
        try:
            with urlopen(req, timeout=25) as response:
                try:
                    raw = response.read(8 * 1024 * 1024 + 1)
                except IncompleteRead as exc:
                    raw = exc.partial
            if len(raw) > 8 * 1024 * 1024:
                raise CatalogError("Catalog page exceeds size limit")
            snapshot.update(parse_catalog_html(page_url, raw.decode("utf-8", errors="replace")))
        except CatalogError:
            raise
        except (HTTPError, URLError, IncompleteRead, ValueError, OSError, TimeoutError) as exc:
            raise CatalogError(f"Catalog fetch failed: {type(exc).__name__}") from exc
    if not snapshot:
        raise CatalogError("No catalog products found")
    return snapshot
