"""The Auth Security agent's MCP server, with a throwaway signing key and a faked identity provider (no network)."""

import asyncio
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.client.client import Client

from app.local_mcp import auth

ISSUER = "https://idp.example.com/pool-1"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {
    **json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key())),
    "kid": "k1",
    "alg": "RS256",
    "use": "sig",
}
META = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/jwks",
    "grant_types_supported": ["authorization_code", "refresh_token", "implicit"],
    "response_types_supported": ["code", "token"],
    "id_token_signing_alg_values_supported": ["RS256"],
}


def token(**claims) -> str:
    now = int(time.time())
    body = {
        "iss": ISSUER,
        "aud": "my-api",
        "sub": "user-123456",
        "iat": now,
        "exp": now + 900,
        "scope": "read",
    } | claims
    return jwt.encode(
        {k: v for k, v in body.items() if v is not None},
        KEY,
        algorithm="RS256",
        headers={"kid": "k1"},
    )


@pytest.fixture
def idp(monkeypatch):
    documents = {
        f"{ISSUER}/.well-known/openid-configuration": META,
        f"{ISSUER}/jwks": {"keys": [JWK]},
    }

    async def fake_json(url):
        if url not in documents:
            raise auth.AuthToolError(f"{url} returned HTTP 404")
        return documents[url]

    monkeypatch.setattr(auth, "_json", fake_json)
    return documents


def call(name: str, arguments: dict) -> dict:
    async def run():
        async with Client(auth.create_server()) as client:
            result = await client.call_tool(name, arguments)
            assert not result.is_error, result.content
            return json.loads(result.content[0].text)

    return asyncio.run(run())


def severities(result: dict) -> dict[str, str]:
    return {f["finding"]: f["severity"] for f in result["findings"]}


def test_identity_provider_setup_is_read_and_weak_settings_flagged(idp):
    result = call("check_identity_provider", {"issuer": ISSUER + "/"})
    assert result["token_endpoint"] == f"{ISSUER}/token"
    assert result["signing_keys"] == [
        {"kid": "k1", "kty": "RSA", "alg": "RS256", "use": "sig", "bits": 2048}
    ]
    found = " ".join(severities(result))
    assert (
        "PKCE support isn't advertised" in found and "implicit flow is offered" in found
    )
    assert "differs from" not in found  # the issuer matches, trailing slash or not


def test_a_valid_token_is_verified_and_its_personal_claims_hidden(idp):
    result = call(
        "inspect_jwt",
        {
            "token": "Bearer " + token(email="a@b.c"),
            "issuer": ISSUER,
            "audience": "my-api",
        },
    )
    assert result["verification"] == {
        "verified": True,
        "checked": "signature, issuer, expiry and audience",
    }
    assert result["header"] == {"alg": "RS256", "typ": "JWT", "kid": "k1"}
    assert result["claims"]["aud"] == "my-api" and result["claims"]["sub"].startswith(
        "user…"
    )
    assert "email" in result["other_claims"] and "a@b.c" not in json.dumps(result)
    assert any("personal data (email)" in f for f in severities(result))


def test_wrong_audience_tampering_and_unknown_keys_fail_verification(idp):
    wrong = call(
        "inspect_jwt", {"token": token(), "issuer": ISSUER, "audience": "other-api"}
    )
    assert (
        not wrong["verification"]["verified"]
        and "Audience" in wrong["verification"]["reason"]
    )

    head, body, sig = token().split(".")
    forged = jwt.utils.base64url_encode(
        json.dumps(
            {"iss": ISSUER, "aud": "my-api", "exp": 9999999999, "scope": "admin"}
        ).encode()
    ).decode()
    tampered = call(
        "inspect_jwt", {"token": f"{head}.{forged}.{sig}", "issuer": ISSUER}
    )
    assert (
        not tampered["verification"]["verified"]
        and "Signature" in tampered["verification"]["reason"]
    )

    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    unknown = jwt.encode(
        {"iss": ISSUER, "exp": int(time.time()) + 60},
        other_key,
        algorithm="RS256",
        headers={"kid": "k9"},
    )
    assert (
        "No published key has kid 'k9'"
        in call("inspect_jwt", {"token": unknown, "issuer": ISSUER})["verification"][
            "reason"
        ]
    )


def test_risky_tokens_are_flagged_without_verification():
    unsigned = jwt.encode({"sub": "x"}, None, algorithm="none")
    found = severities(call("inspect_jwt", {"token": unsigned}))
    assert (
        found["alg is none: the token is unsigned. A validator must reject it"]
        == "critical"
    )
    assert any("No exp claim" in f for f in found) and any(
        "No aud claim" in f for f in found
    )

    now = int(time.time())
    shared = jwt.encode(
        {
            "iss": "me",
            "aud": "api",
            "iat": now,
            "exp": now + 7 * 86400,
            "token_use": "id",
        },
        "s" * 32,
        algorithm="HS256",
    )
    found = severities(call("inspect_jwt", {"token": shared}))
    assert any("HS256 uses a shared secret" in f for f in found) and any(
        "Lifetime is 168 hours" in f for f in found
    )
    assert any("looks like an ID token" in f for f in found)


def test_not_a_jwt_is_refused():
    async def run():
        async with Client(auth.create_server()) as client:
            return await client.call_tool("inspect_jwt", {"token": "abc.def"})

    result = asyncio.run(run())
    assert result.is_error and "Not a JWT" in result.content[0].text


def test_security_headers_and_cookie_flags(monkeypatch):
    async def fake_fetch(url, **_):
        if url.startswith("http://"):
            return httpx.Response(200), url, b""  # served over plain HTTP
        headers = [
            ("strict-transport-security", "max-age=63072000"),
            (
                "content-security-policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline'",
            ),
            ("set-cookie", "session=secret-value; Path=/; HttpOnly"),
            ("set-cookie", "theme=dark; Secure; HttpOnly; SameSite=Lax"),
        ]
        return httpx.Response(200, headers=headers), url, b""

    monkeypatch.setattr(auth, "fetch", fake_fetch)
    result = call("check_security_headers", {"url": "https://app.example.com/login"})
    assert result["http_redirects_to_https"] is False
    assert result["cookies"][0] == {
        "name": "session",
        "secure": False,
        "httponly": True,
        "samesite": "not set",
    }
    assert "secret-value" not in json.dumps(result)
    found = severities(result)
    assert found["http:// doesn't redirect to https://"] == "high"
    assert any("Cookie session lacks Secure" in f for f in found) and not any(
        "Cookie theme lacks" in f for f in found
    )
    assert any("'unsafe-inline'" in f for f in found) and not any(
        "No Strict-Transport-Security" in f for f in found
    )
