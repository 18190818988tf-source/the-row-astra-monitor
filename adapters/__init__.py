"""Retailer adapters: add new sites here without changing the scheduler."""
from .shopify import check_shopify, discover_shopify_search
from .jsonld import check_jsonld_product

ADAPTERS = {"shopify": check_shopify, "jsonld_product": check_jsonld_product}

DISCOVERERS = {"shopify_search": discover_shopify_search}
