"""Run once on GitHub Actions cron; poll configured enabled products.

Real browser/checkout UI verification is NOT part of this MVP. Shopify SKU
availability is a reliable signal to investigate, not a guarantee of checkout.
No purchase or checkout functionality is included.
"""
import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
from datetime import datetime, timezone

from adapters import ADAPTERS
from config import load_products
from notifications.bark import send_bark


def load_state(path):
    path = Path(path)
    if not path.exists():
        return {"schema_version": 1, "products": {}}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("products"), dict):
        raise ValueError("Bad state.json")
    return doc


def save_state(path, state):
    path = Path(path)
    contents = json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != contents:
        path.write_text(contents, encoding="utf-8")


def update_one(item, previous, status, proof, send_push, now):
    """Perform state transition and notify once per stock cycle.

    A failed notification remains pending and is retried on the next run.
    Unknown status does not reset stock state or produce false alerts.
    """
    state = dict(previous or {"last_reliable": None, "notified_in_stock": False, "unknown_streak": 0})
    if status == "unknown":
        state["unknown_streak"] = min(3, state.get("unknown_streak", 0) + 1)
        return state, "unknown"
    state["unknown_streak"] = 0
    if status == "out_of_stock":
        state["last_reliable"] = "out_of_stock"
        state["notified_in_stock"] = False
        return state, "out_of_stock"
    if status == "in_stock":
        state["last_reliable"] = "in_stock"
        if not state.get("notified_in_stock", False):
            title = f"补货提醒：{item['brand']} {item['name']}"
            details = [f"SKU: {item['sku']}", f"颜色: {item.get('color', '未指定')}",
                       f"尺码: {item.get('size', '未指定')}",
                       f"时间(UTC): {now}", proof, "点击查看官网；未验证最终结账"]
            # On push errors, raises. The state is not marked notified.
            send_push(title, "\n".join(details), item["url"])
            state["notified_in_stock"] = True
            state["last_notified_utc"] = now
            return state, "sent"
        return state, "already_notified"
    raise ValueError(f"Unhandled status {status}")


def heartbeat():
    url = os.getenv("HC_PING_URL", "").strip()
    if not url:
        return
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise ValueError("HC_PING_URL must be HTTPS")
    with urlopen(Request(url, headers={"User-Agent": "PersonalInventoryMonitor/1.0"}), timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError("Heartbeat rejected")


def main():
    cli = argparse.ArgumentParser(description="Multi-brand stock monitor")
    cli.add_argument("--test-push", action="store_true", help="Send only a Bark test push")
    cli.add_argument("--dry-run", action="store_true", help="Query stock but do not notify or change state")
    cli.add_argument("--config", default="products.json")
    cli.add_argument("--state", default="state.json")
    args = cli.parse_args()

    bark_url = os.getenv("BARK_PUSH_URL", "")
    if args.test_push:
        send_bark(bark_url, "Multi-brand stock monitor test", "GitHub Actions → Bark 测试消息", "https://www.therow.com/products/astra-black-ans-1", test=True)
        print("Bark test notification accepted")
        return 0

    items = load_products(args.config)
    if not items:
        print("No enabled products; nothing to do")
        return 1
    state = load_state(args.state)
    statuses = []
    failures = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for item in items:
        adapter = ADAPTERS.get(item["adapter"])
        if adapter is None:
            statuses.append("unknown")
            print(f"{item['id']}: unknown: unsupported adapter {item['adapter']}")
            continue
        status, proof = adapter(item)
        statuses.append(status)
        print(f"{item['id']}: {status}: {proof}")
        if args.dry_run:
            continue
        old_state = state["products"].get(item["id"], {})
        try:
            send = lambda title, body, product_url: send_bark(bark_url, title, body, product_url)
            new_state, action = update_one(item, old_state, status, proof, send, now)
            state["products"][item["id"]] = new_state
            print(f"{item['id']}: action={action}")
        except Exception as exc:
            # Reuse old state so the alert will retry, never record a successful send.
            failures.append(item["id"])
            print(f"{item['id']}: notification failed ({type(exc).__name__})")
    if args.dry_run:
        return 0 if any(s != "unknown" for s in statuses) else 2
    save_state(args.state, state)
    if failures or all(s == "unknown" for s in statuses):
        print("Monitor unhealthy: notification failure or all checks unknown")
        return 2
    try:
        heartbeat()
    except Exception as exc:
        print(f"Heartbeat error ({type(exc).__name__})")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
