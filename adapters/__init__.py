"""Retailer adapters: add new sites here without changing the scheduler."""
from .shopify import check_shopify

ADAPTERS = {"shopify": check_shopify}
