"""First-party usage analytics: what people view and which agents, tools and features they use.

What an event holds: its name, a few short properties (which view, which agents and tools ran, how long it
took, whether it failed), the visitor's daily id and coarse place from viewer.py, and the device class read
from the User-Agent. Never the address, a message, an image or a report. No cookies are set; the browser's
per-tab session id lives in sessionStorage.

Left out: bots, browsers that send Do Not Track or Global Privacy Control, and (unless asked for) the
owner's own browsers, marked internal with ?internal=1.

ANALYTICS_BACKEND selects where events live, like CONVERSATION_BACKEND in memory.py:
  memory (default) - a list in this process; fine for one local server
  dynamodb         - Amazon DynamoDB (ANALYTICS_TABLE): one partition per UTC day, removed by TTL

Recording must never break the app: a failed write is logged and dropped.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import AsyncIterable, AsyncIterator
from decimal import Decimal
from functools import lru_cache
from statistics import median
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

from .viewer import REQUEST, is_internal, visitor_id

log = logging.getLogger(__name__)

RETENTION_DAYS = int(os.getenv("ANALYTICS_RETENTION_DAYS", "395"))  # about 13 months: a year-on-year view
MAX_STATS_DAYS = 90

BOT = re.compile(r"bot|crawl|spider|slurp|preview|headless|lighthouse|curl|wget|python-|httpx|go-http|java/", re.I)

Item = dict[str, Any]


# ---------------------------------------------------------------- storage


class AnalyticsStore(Protocol):
    def put(self, item: Item) -> None: ...
    def query(self, day: str) -> list[Item]: ...


class MemoryAnalyticsStore:
    def __init__(self):
        self.items: list[Item] = []

    def put(self, item):
        self.items.append(item)

    def query(self, day):
        return [i for i in self.items if i["day"] == day]


class DynamoAnalyticsStore:
    def __init__(self, table_name: str):
        import boto3

        self._table = boto3.resource("dynamodb").Table(table_name)

    def put(self, item):
        self._table.put_item(Item=_to_dynamo(item))

    def query(self, day):
        from boto3.dynamodb.conditions import Key

        items, kwargs = [], {"KeyConditionExpression": Key("day").eq(day)}
        while True:
            page = self._table.query(**kwargs)
            items += [_from_dynamo(i) for i in page["Items"]]
            if "LastEvaluatedKey" not in page:
                return items
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _to_dynamo(value):
    """DynamoDB takes Decimal, not float; and an empty string can't be a key."""
    if isinstance(value, float):
        return Decimal(str(round(value, 3)))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items() if v != "" and v is not None}
    if isinstance(value, list):
        return [_to_dynamo(v) for v in value]
    return value


def _from_dynamo(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    return value


@lru_cache
def get_analytics_store() -> AnalyticsStore:
    if os.getenv("ANALYTICS_BACKEND", "memory") == "dynamodb":
        return DynamoAnalyticsStore(os.environ["ANALYTICS_TABLE"])
    return MemoryAnalyticsStore()


# ---------------------------------------------------------------- recording


def device(user_agent: str) -> dict[str, str]:
    """Coarse device, browser and OS from the User-Agent (the full string is not kept)."""
    ua = user_agent
    if re.search(r"iPad|Tablet", ua) or ("Android" in ua and "Mobile" not in ua):
        kind = "tablet"
    elif re.search(r"Mobi|iPhone|iPod", ua):
        kind = "mobile"
    else:
        kind = "desktop"
    browser = next(
        (name for pattern, name in [("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
                                    ("CriOS/", "Chrome"), ("Safari/", "Safari")] if pattern in ua),
        "Other",
    )
    os_name = next(
        (name for pattern, name in [("iPhone", "iOS"), ("iPad", "iOS"), ("Android", "Android"), ("Windows", "Windows"),
                                    ("Mac OS X", "macOS"), ("CrOS", "ChromeOS"), ("Linux", "Linux")] if pattern in ua),
        "Other",
    )
    return {"device": kind, "browser": browser, "os": os_name}


def _visit(headers: dict[str, str]) -> Item | None:
    """Who and where this request came from, or None when it must not be counted."""
    ua = headers.get("user-agent", "")
    if not ua or BOT.search(ua) or headers.get("dnt") == "1" or headers.get("sec-gpc") == "1":
        return None
    # Through CloudFront the viewer's address; locally the TCP peer, so a dev server still counts visitors
    address = headers.get("cloudfront-viewer-address", "").rsplit(":", 1)[0] or headers.get("x-client-host", "")
    return {
        "visitor": visitor_id(address, ua),
        "country": headers.get("cloudfront-viewer-country", ""),
        "region": unquote(headers.get("cloudfront-viewer-country-region-name", ""))[:60],
        "internal": is_internal(headers),
        **device(ua),
    }


def record(name: str, props: dict[str, Any] | None = None, *, source: str = "server", session: str = "",
           headers: dict[str, str] | None = None) -> Item | None:
    """Store one event for the current request; returns it (None when it wasn't counted)."""
    try:
        visit = _visit(REQUEST.get() if headers is None else headers)
        if visit is None:
            return None
        now = datetime.datetime.now(datetime.UTC)
        item = {
            "day": now.date().isoformat(),
            "sk": f"{now.isoformat(timespec='milliseconds')}#{uuid.uuid4().hex[:8]}",  # sorts by time, never collides
            "name": name,
            "source": source,
            "session": session,
            "props": props or {},
            "expires_at": int(time.time()) + RETENTION_DAYS * 86400,  # DynamoDB TTL removes old events
            **visit,
        }
        get_analytics_store().put(item)
        return item
    except Exception:  # analytics must never break a request
        log.exception("could not record analytics event %r", name)
        return None


async def tracked(name: str, events: AsyncIterable[dict], **props: Any) -> AsyncIterator[dict]:
    """Pass an agent's SSE events through unchanged, and record one `name` event when the run ends: the agents
    and tools it used, whether it failed, and how long it took. Recorded even when the reader goes away."""
    started = time.monotonic()
    agents: list[str] = []
    tools: list[str] = []
    tool_errors = 0
    error = completed = False
    try:
        async for event in events:
            kind = event.get("type")
            if kind == "agent_start" and event.get("agent"):
                agents.append(str(event["agent"]))
            elif kind == "tool_call" and event.get("name"):
                tools.append(str(event["name"]))
            elif kind == "tool_result" and event.get("is_error"):
                tool_errors += 1
            elif kind == "error":
                error = True
            yield event
        completed = True
    except Exception:  # not GeneratorExit / CancelledError: a reader leaving early is not a failure
        error = True
        raise
    finally:
        record(name, {
            **props,
            "agents": sorted(set(agents)),
            "tools": sorted(set(tools)),
            "tool_calls": len(tools),
            "tool_errors": tool_errors,
            "error": error,
            "completed": completed,  # false: the reader stopped it or left
            "duration_ms": round((time.monotonic() - started) * 1000),
        })


# --------------------------------------------------------------- reporting

# Server events, one per agent run or action; shown together as "features"
FEATURES = {
    "chat_turn": "Chat", "label": "Annotate", "pathology": "Pathology tools", "diagnose": "Diagnose",
    "trials": "Clinical trials", "drugs": "Medicines", "security": "App security",
    "handoff": "Ask AI handoff", "share": "Open in Image Label", "fetch_image": "Image from URL",
    "upload": "Image upload", "download": "Download",
}


def _top(counter: Counter, n: int = 10) -> list[dict]:
    return [{"key": k, "count": c} for k, c in counter.most_common(n) if k]


def summarize(items: list[Item], days: list[str]) -> dict:
    """The stats page's numbers for these events (`days` are the dates asked for, oldest first)."""
    views = [i for i in items if i["name"] == "view"]
    visitor_days = {(i["day"], i["visitor"]) for i in items}
    per_day: dict[str, dict[str, set | int]] = defaultdict(lambda: {"visitors": set(), "views": 0, "runs": 0})
    for i in items:
        d = per_day[i["day"]]
        d["visitors"].add(i["visitor"])
        if i["name"] == "view":
            d["views"] += 1
        elif i["source"] == "server":
            d["runs"] += 1

    # Place, device: counted once per visitor and day, so a busy visitor doesn't dominate
    first_seen: dict[tuple, Item] = {}
    for i in sorted(items, key=lambda i: i["sk"]):
        first_seen.setdefault((i["day"], i["visitor"]), i)
    people = list(first_seen.values())

    features = []
    for name, title in FEATURES.items():
        runs = [i for i in items if i["name"] == name]
        if not runs:
            continue
        durations = [i["props"]["duration_ms"] for i in runs if isinstance(i["props"].get("duration_ms"), int)]
        errors = sum(1 for i in runs if i["props"].get("error") or i["props"].get("ok") is False)
        features.append({
            "key": name, "title": title, "count": len(runs), "visitors": len({(i["day"], i["visitor"]) for i in runs}),
            "errors": errors, "error_rate": round(errors / len(runs), 3),
            "p50_ms": round(median(durations)) if durations else None,
            "p95_ms": sorted(durations)[max(0, int(len(durations) * 0.95 + 0.5) - 1)] if durations else None,
        })

    runs = [i for i in items if i["source"] == "server"]
    return {
        "days": days,
        "totals": {
            "visitors": len(visitor_days),
            "sessions": len({i["session"] for i in items if i.get("session")}),
            "views": len(views),
            "runs": len(runs),
            "errors": sum(f["errors"] for f in features),
        },
        "daily": [
            {"day": day, "visitors": len(per_day[day]["visitors"]), "views": per_day[day]["views"], "runs": per_day[day]["runs"]}
            if day in per_day else {"day": day, "visitors": 0, "views": 0, "runs": 0}
            for day in days
        ],
        "views": _top(Counter(i["props"].get("view", "") for i in views)),
        "features": sorted(features, key=lambda f: -f["count"]),
        "agents": _top(Counter(a for i in runs for a in i["props"].get("agents", []))),
        "tools": _top(Counter(t for i in runs for t in i["props"].get("tools", [])), 15),
        "downloads": _top(Counter(i["props"].get("format", "") for i in items if i["name"] == "download")),
        "referrers": _top(Counter(i["props"].get("referrer", "") for i in views)),
        "campaigns": _top(Counter(i["props"].get("utm_source", "") for i in views)),
        "countries": _top(Counter(p["country"] for p in people if p.get("country"))),
        "devices": _top(Counter(p["device"] for p in people)),
        "browsers": _top(Counter(p["browser"] for p in people)),
        "os": _top(Counter(p["os"] for p in people)),
    }


def stats(days: int, include_internal: bool = False) -> dict:
    today = datetime.datetime.now(datetime.UTC).date()
    dates = [(today - datetime.timedelta(days=n)).isoformat() for n in range(days - 1, -1, -1)]
    store = get_analytics_store()
    items = [i for day in dates for i in store.query(day)]
    if not include_internal:
        items = [i for i in items if not i.get("internal")]
    return summarize(items, dates)


def referrer_host(referrer: str) -> str:
    """Only the other site's host name ("news.ycombinator.com"), never the page or its query."""
    host = (urlparse(referrer).hostname or "").removeprefix("www.")
    return host[:100]
