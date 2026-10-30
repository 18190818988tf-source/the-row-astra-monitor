"""Retailer adapters: add new sites here without changing the scheduler."""
from .shopify import check_shopify, discover_shopify_search

ADAPTERS = {"shopify": check_shopify}

DISCOVERERS = {"shopify_search": discover_shopify_search}
