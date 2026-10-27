from app.viewer import viewer_headers


def test_visitor_place_from_cloudfront():
    headers = {
        "cloudfront-viewer-country": "BR",
        "cloudfront-viewer-country-region-name": "São Paulo",
        "cloudfront-viewer-city": "São Paulo",
        "cloudfront-viewer-time-zone": "America/Sao_Paulo",
        "cloudfront-viewer-address": "203.0.113.7:51234",
        "user-agent": "Mozilla/5.0",
    }
    viewer = viewer_headers(headers)
    assert viewer["x-viewer-country"] == "BR" and viewer["x-viewer-time-zone"] == "America/Sao_Paulo"
    assert viewer["x-viewer-city"] == "S%C3%A3o Paulo"  # header-safe; the API decodes it
    assert len(viewer["x-viewer-visitor"]) == 12 and "203.0.113.7" not in viewer["x-viewer-visitor"]
    assert viewer["x-viewer-address"] == "203.0.113.7"  # for Image Label's keyed hash (distinct addresses)
    # the same person on another port is the same visitor; another browser is not
    assert viewer_headers({**headers, "cloudfront-viewer-address": "203.0.113.7:6000"})["x-viewer-visitor"] == viewer["x-viewer-visitor"]
    assert viewer_headers({**headers, "user-agent": "curl"})["x-viewer-visitor"] != viewer["x-viewer-visitor"]


def test_no_place_without_cloudfront():
    assert viewer_headers({"user-agent": "Mozilla/5.0"}) == {}


def test_the_owners_browser_is_marked_internal():
    cloudfront = {"cloudfront-viewer-country": "US", "cloudfront-viewer-address": "203.0.113.7:1", "user-agent": "x"}
    assert viewer_headers({**cloudfront, "cookie": "a=b; internal=1"})["x-viewer-internal"] == "1"
    assert viewer_headers({"cookie": "internal=1"}) == {"x-viewer-internal": "1"}  # even without CloudFront
    assert "x-viewer-internal" not in viewer_headers({**cloudfront, "cookie": "internal=0; notinternal=1"})
