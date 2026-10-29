"""Bark HTTPS push integration. Never print device secrets in logs."""
import json
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def send_bark(push_url, title, body, product_url, *, test=False):
    push_url = (push_url or "").strip().rstrip("/")
    p = urlsplit(push_url)
    if p.scheme != "https" or not p.hostname or not p.path.strip("/") or p.username or p.password or p.query or p.fragment:
        raise ValueError("Missing/invalid BARK_PUSH_URL (full HTTPS device endpoint required)")
    payload = {
        "title": title,
        "body": body,
        "group": "MultiBrandStockMonitor",
        "url": product_url,
        "level": "active" if test else "timeSensitive",
        "sound": "minuet" if test else "alarm",
    }
    req = Request(push_url,
                  data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                  headers={"Content-Type": "application/json", "Accept": "application/json"},
                  method="POST")
    with urlopen(req, timeout=15) as resp:
        raw = resp.read(8192)
        if resp.status != 200:
            raise RuntimeError(f"Bark HTTP status {resp.status}")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Invalid Bark response") from exc
    if str(data.get("code")) not in ("200",):
        raise RuntimeError("Bark API did not accept notification")
    return True
