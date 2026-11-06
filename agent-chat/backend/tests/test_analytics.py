"""Usage analytics: what is recorded, what is left out, and the stats the page shows."""

import pytest
from fastapi.testclient import TestClient

from app import analytics, main
from app.analytics import MemoryAnalyticsStore, device, record, referrer_host, summarize, tracked

CHROME = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
CLOUDFRONT = {
    "user-agent": CHROME,
    "cloudfront-viewer-address": "203.0.113.7:51234",
    "cloudfront-viewer-country": "IN",
    "cloudfront-viewer-country-region-name": "Maharashtra",
}


@pytest.fixture
def store(monkeypatch):
    store = MemoryAnalyticsStore()
    monkeypatch.setattr(analytics, "get_analytics_store", lambda: store)
    return store


def test_an_event_keeps_the_place_and_device_but_never_the_address(store):
    item = record("view", {"view": "chat"}, source="client", session="ab12", headers=CLOUDFRONT)
    assert item["country"] == "IN" and item["region"] == "Maharashtra"
    assert item["device"] == "desktop" and item["browser"] == "Chrome" and item["os"] == "macOS"
    assert len(item["visitor"]) == 12 and "203.0.113.7" not in str(item)
    assert item["expires_at"] > 0 and store.items == [item]


@pytest.mark.parametrize("headers", [
    {"user-agent": "Googlebot/2.1 (+http://www.google.com/bot.html)"},
    {"user-agent": "curl/8.7.1"},
    {"user-agent": ""},
    {**CLOUDFRONT, "dnt": "1"},
    {**CLOUDFRONT, "sec-gpc": "1"},
])
def test_bots_and_opted_out_browsers_are_not_counted(store, headers):
    assert record("view", headers=headers) is None and store.items == []


def test_the_owners_browser_is_recorded_as_internal_and_left_out_of_stats(store):
    record("view", {"view": "chat"}, headers={**CLOUDFRONT, "cookie": "internal=1"})
    record("view", {"view": "chat"}, headers=CLOUDFRONT)
    assert [i["internal"] for i in store.items] == [True, False]
    assert analytics.stats(1)["totals"]["views"] == 1
    assert analytics.stats(1, include_internal=True)["totals"]["views"] == 2


def test_a_failing_store_never_breaks_the_request(monkeypatch):
    class Broken:
        def put(self, item):
            raise RuntimeError("dynamodb is down")

    monkeypatch.setattr(analytics, "get_analytics_store", lambda: Broken())
    assert record("view", headers=CLOUDFRONT) is None


@pytest.mark.parametrize("ua, kind, browser, os_name", [
    (CHROME, "desktop", "Chrome", "macOS"),
    (IPHONE, "mobile", "Safari", "iOS"),
    ("Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 Chrome/131.0 Safari/537.36", "tablet", "Chrome", "Android"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36 Edg/131.0", "desktop", "Edge", "Windows"),
])
def test_device_is_read_coarsely_from_the_user_agent(ua, kind, browser, os_name):
    assert device(ua) == {"device": kind, "browser": browser, "os": os_name}


def test_only_the_referrers_host_is_kept():
    assert referrer_host("https://www.linkedin.com/feed/update/urn:li:activity:123?trk=x") == "linkedin.com"
    assert referrer_host("") == "" and referrer_host("not a url") == ""


async def _events(*events, fail=False):
    for event in events:
        yield event
    if fail:
        raise RuntimeError("model down")


async def test_tracked_passes_events_through_and_records_the_run(store, monkeypatch):
    analytics.REQUEST.set(CLOUDFRONT)  # what ViewerMiddleware does for a real request
    events = [
        {"type": "agent_start", "agent": "genetics"},
        {"type": "tool_call", "name": "clinvar_search"},
        {"type": "tool_result", "name": "clinvar_search", "is_error": True},
        {"type": "tool_call", "name": "clinvar_search"},
        {"type": "agent_start", "agent": "blog"},
        {"type": "token", "text": "hi"},
    ]
    seen = [e async for e in tracked("chat_turn", _events(*events), images=1)]
    assert seen == events
    (item,) = store.items
    assert item["name"] == "chat_turn" and item["source"] == "server"
    props = item["props"]
    assert props["agents"] == ["blog", "genetics"] and props["tools"] == ["clinvar_search"]
    assert props["tool_calls"] == 2 and props["tool_errors"] == 1 and props["images"] == 1
    assert props["error"] is False and props["completed"] is True and isinstance(props["duration_ms"], int)


async def test_tracked_records_a_failed_run_and_re_raises(store, monkeypatch):
    analytics.REQUEST.set(CLOUDFRONT)  # what ViewerMiddleware does for a real request
    with pytest.raises(RuntimeError):
        async for _ in tracked("trials", _events({"type": "token", "text": "x"}, fail=True)):
            pass
    assert store.items[0]["props"]["error"] is True and store.items[0]["props"]["completed"] is False


async def test_tracked_records_a_run_the_reader_left(store, monkeypatch):
    analytics.REQUEST.set(CLOUDFRONT)  # what ViewerMiddleware does for a real request
    run = tracked("drugs", _events({"type": "token", "text": "a"}, {"type": "token", "text": "b"}))
    await anext(run)
    await run.aclose()  # the browser stopped reading
    assert store.items[0]["props"]["completed"] is False and store.items[0]["props"]["error"] is False


def _item(day, visitor, name, source="server", **props):
    return {"day": day, "sk": f"{day}T00:00:00#{visitor}{name}", "visitor": visitor, "name": name, "source": source,
            "session": "", "props": props, "country": "IN", "device": "desktop", "browser": "Chrome", "os": "macOS"}


def test_summarize_counts_visitors_per_day_and_features():
    items = [
        _item("2026-11-01", "a", "view", "client", view="chat", referrer="linkedin.com"),
        _item("2026-11-01", "a", "chat_turn", agents=["genetics"], tools=["clinvar"], error=False, duration_ms=1000),
        _item("2026-11-01", "b", "view", "client", view="label"),
        _item("2026-11-02", "a", "chat_turn", agents=["genetics", "blog"], tools=[], error=True, duration_ms=3000),
        _item("2026-11-02", "a", "download", "client", format="coco"),
    ]
    stats = summarize(items, ["2026-10-31", "2026-11-01", "2026-11-02"])
    assert stats["totals"] == {"visitors": 3, "sessions": 0, "views": 2, "runs": 2, "errors": 1}
    assert [d["visitors"] for d in stats["daily"]] == [0, 2, 1]
    chat = next(f for f in stats["features"] if f["key"] == "chat_turn")
    assert chat["count"] == 2 and chat["errors"] == 1 and chat["p50_ms"] == 2000 and chat["p95_ms"] == 3000
    assert stats["agents"][0] == {"key": "genetics", "count": 2}
    assert stats["referrers"] == [{"key": "linkedin.com", "count": 1}]
    assert stats["downloads"] == [{"key": "coco", "count": 1}]
    assert stats["countries"] == [{"key": "IN", "count": 3}]  # once per visitor and day


# ------------------------------------------------------------------ the API


@pytest.fixture
def client(store):
    with TestClient(main.app, headers={"user-agent": CHROME}) as client:
        yield client


def test_the_browser_posts_events(client, store):
    res = client.post("/events", json={
        "name": "view", "props": {"view": "trials"}, "session": "0123456789abcdef",
        "referrer": "https://news.ycombinator.com/item?id=1", "utm_source": "LinkedIn",
    })
    assert res.status_code == 204
    (item,) = store.items
    assert item["source"] == "client" and item["session"] == "0123456789abcdef"
    assert item["props"] == {"view": "trials", "referrer": "news.ycombinator.com", "utm_source": "linkedin"}


@pytest.mark.parametrize("body", [
    {"name": "purchase"},                                   # not an event the site sends
    {"name": "view", "props": {"View": "x"}},               # bad property name
    {"name": "view", "props": {"view": "<script>"}},        # bad value
    {"name": "view", "props": {f"k{i}": "x" for i in range(7)}},  # too many
    {"name": "view", "session": "not-hex!"},
])
def test_odd_events_are_rejected(client, store, body):
    assert client.post("/events", json=body).status_code == 422 and store.items == []


def test_a_dynamodb_round_trip_keeps_numbers_as_numbers():
    item = {"props": {"duration_ms": 1200, "score": 0.5, "agents": ["a"], "empty": ""}, "session": ""}
    stored = analytics._to_dynamo(item)
    assert "session" not in stored and "empty" not in stored["props"]
    assert analytics._from_dynamo(stored) == {"props": {"duration_ms": 1200, "score": 0.5, "agents": ["a"]}}
