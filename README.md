# Multi-brand Stock Monitor（多品牌库存监控中心）

**One repository, many brands, many products.** The Row Astra source dynamically discovers every product and variant currently listed by the official search page.

> ⚠️ Important: Stock signals are from Shopify's public product JSON, not proof of a completed checkout. The program never logs in, adds products to cart, places orders, or pays. An item being flagged `in_stock` by Shopify is an actionable signal, not an absolute guarantee of website purchase success.

## Current catalog

- The Row Astra series search page (all current products and variants; no fixed SKU list)
- https://www.therow.com/search?q=%28title%3Aastra%2A+OR+tag%3Aastra%2A+OR+variants.sku%3Aastra%2A%29&type=product
- Excluded from alerts: `astra-pouch-nuez-ans` (Astra Pouch Nuez)

## Project structure

- `products.json` — monitored fixed products or dynamic catalog sources
- `adapters/shopify.py` — Shopify search discovery plus strict variant-level stock checks
- `monitor.py` — scheduler entrypoint, state transitions, Bark push and optional uptime heartbeat
- `notifications/bark.py` — Bark notification delivery, from `BARK_PUSH_URL` secret
- `state.json` — persisted stock status across GitHub Actions runs
- `.github/workflows/stock-monitor.yml` — GitHub Actions trial, every 5 minutes *attempted*
- `tests/` — local unit tests, no live stock necessary

## IMPORTANT: Upload source files, not a ZIP file!

1. In your GitHub repository, click `Add file > Upload files`.
2. Upload **the contents of the extracted folder**, not the ZIP file itself. Upload all subfolders including the hidden `.github` directory. The GitHub website may not upload hidden directories reliably via Finder drag and drop; if you cannot see the workflow, use git in Terminal or manually create `.github/workflows/stock-monitor.yml`.
3. Confirm this file is visible on the GitHub page: `.github/workflows/stock-monitor.yml`.
4. The workflow's `workflow_dispatch` lets you run a manual **dry run** without Bark credentials.

### macOS terminal upload (more reliable)

```bash
# Clone your existing repo. GitHub may ask you to authenticate.
git clone https://github.com/18190818988tf-source/the-row-astra-monitor.git
cd the-row-astra-monitor
# Copy ALL files, including the hidden .github workflow, from the extracted package.
cp -R /path/to/extracted/multi-brand-stock-monitor/. .
git add -A
git commit -m 'Add multi-brand stock monitor'
git push origin main
```

**Existing repo includes an obsolete ZIP file.** Leave it in place until all source files are pushed and working, then delete it if desired.

## Quick verification

First go to `Actions > Multi-brand stock monitor > Run workflow`.

- Default manual run is `dry_run=true`: fetch real product stock but **no notification**, no state change.
- To test Bark, first create a repository secret `BARK_PUSH_URL` containing the full HTTPS Bark device push endpoint, like `https://api.day.app/DEVICE_PRIVATE_KEY` (do not share the real URL). Run manually with `test_push=true`.
- For real notification on manual run: `test_push=false, dry_run=false`; this queries enabled products and saves their latest status.
- Scheduled runs are **not** dry-run; they rediscover the whole Astra result page and alert independently for each variant seen `in_stock` and not already notified in that stock cycle.

## Adding products

The Astra entry uses `adapter: shopify_search`, so products added to that official search result are discovered automatically. A fixed Shopify item can still be added like this:

```json
{
  "id": "my-second-product",
  "brand": "SampleBrand",
  "name": "Sample Bag",
  "url": "https://example.com/products/sample-bag",
  "adapter": "shopify",
  "sku": "YOUR_VERIFIED_SKU",
  "color": "Black",
  "size": "One Size",
  "enabled": false
}
```

This works **only for Shopify stores** exposing the standard public `.js` endpoint. For other ecommerce platforms you must implement and test a new adapter in `adapters/`; changing only a URL will not be enough.

## Reliability & free-tier boundaries

- GitHub Actions scheduled workflows can start late or skip runs; it is not a strict 5-minute SLA. Public repository standard GitHub-hosted runners are normally free; private repos have usage quotas. Test overall cost before switching visibility.
- The monitor writes `state.json` only when relevant state changes. For more than a few hundred items or for strongly reliable 5-minute schedules, prefer Cloudflare Workers + D1 with adapters and data management reimplemented appropriately.
- If Bark push fails, notification status is not committed, so a future run retries.
- Keep your Bark device endpoint secret (repository Settings > Secrets and variables > Actions > `BARK_PUSH_URL`), never in source code or `products.json`.
- Optional uptime monitoring: set `HC_PING_URL` to the Healthchecks HTTPS ping URL; add a check with a >5-minute grace to account for GitHub scheduling delay.
- For a robust setup, have a second notification transport for delivery failures and a watchdog independent of GitHub. No free service guarantees 100% notifications.

## Local test

```bash
python3 -m unittest discover -s tests -v
python3 monitor.py --dry-run
```
