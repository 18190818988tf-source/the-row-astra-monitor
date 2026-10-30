"""Retailer adapters: add new sites here without changing the scheduler."""
from .shopify import check_shopify, discover_shopify_search
from .jsonld import check_jsonld_product
from .arcteryx_catalog import fetch_arcteryx_catalog

ADAPTERS = {"shopify": check_shopify, "jsonld_product": check_jsonld_product}

DISCOVERERS = {"shopify_search": discover_shopify_search}

CATALOG_ADAPTERS = {"arcteryx_catalog": fetch_arcteryx_catalog}
