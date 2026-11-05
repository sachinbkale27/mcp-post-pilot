"""MCP server for designing and reviewing OAuth 2.0 / OpenID Connect sign-in and JWT validation.

It runs inside the agent service (agents.json: "mcp_url": "local:auth"), so it needs no deployment of its own;
`python -m app.local_mcp.auth` also serves it over Streamable HTTP for the MCP Inspector.

  check_identity_provider  reads an issuer's discovery document and signing keys, and flags weak settings
  inspect_jwt              decodes a token's header and claims (never its signature), flags risky ones, and
                           verifies it against the issuer's published keys when an issuer is given
  check_security_headers   reports a site's HTTPS redirect, security headers and cookie flags

Everything is read-only and fetched from the public internet only, through the fact-check server's checked
fetch (no private addresses, no other ports, every redirect checked). Tokens are never stored, and claim
values that may identify a person are reported by name only.
"""

import json
import os
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import jwt
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from .research import FetchError, fetch

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
USER_AGENT = "PostPilotAuthCheck/1.0 (+https://agent.sachin-kale.com)"

# Claims whose values are shown; any other claim is listed by name only, since it may identify a person
SHOWN_CLAIMS = {
    "iss",
    "aud",
    "azp",
    "client_id",
    "exp",
    "iat",
    "nbf",
    "auth_time",
    "scope",
    "scp",
    "roles",
    "groups",
    "cognito:groups",
    "token_use",
    "typ",
    "amr",
    "acr",
    "ver",
    "tid",
}
PERSONAL_CLAIMS = {
    "email",
    "name",
    "given_name",
    "family_name",
    "phone_number",
    "address",
    "birthdate",
    "preferred_username",
}
ASYMMETRIC = ("RS", "PS", "ES", "Ed")


class AuthToolError(ToolError):
    """ToolError messages are shown to the model."""


async def _json(url: str) -> dict[str, Any]:
    try:
        resp, _, body = await fetch(url, max_bytes=500_000, user_agent=USER_AGENT)
    except FetchError:
        raise
    except Exception as exc:
        raise AuthToolError(f"Could not fetch {url}: {exc}") from exc
    if resp.status_code != 200:
        raise AuthToolError(f"{url} returned HTTP {resp.status_code}")
    try:
        return json.loads(body)
    except ValueError as exc:
        raise AuthToolError(f"{url} did not return JSON") from exc


async def discovery(issuer: str) -> tuple[str, dict[str, Any]]:
    """The issuer's OpenID Connect discovery document, or its OAuth server metadata (RFC 8414)."""
    issuer = issuer.strip().rstrip("/")
    if not issuer.startswith("https://"):
        raise AuthToolError(
            "The issuer must be an https:// URL, e.g. https://cognito-idp.<region>.amazonaws.com/<pool id>"
        )
    parts = urlsplit(issuer)
    candidates = [
        f"{issuer}/.well-known/openid-configuration",
        urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                f"/.well-known/oauth-authorization-server{parts.path}",
                "",
                "",
            )
        ),
    ]
    errors = []
    for url in candidates:
        try:
            return url, await _json(url)
        except ToolError as exc:
            errors.append(str(exc))
    raise AuthToolError("No discovery document found: " + "; ".join(errors))


def describe_key(key: dict[str, Any]) -> dict[str, Any]:
    """A signing key's id, type and strength; never its material."""
    out = {k: key[k] for k in ("kid", "kty", "alg", "use", "crv") if k in key}
    if key.get("kty") == "RSA" and isinstance(key.get("n"), str):
        n = key["n"]
        out["bits"] = len(jwt.utils.base64url_decode(n + "=" * (-len(n) % 4))) * 8
    return out


def provider_findings(
    issuer: str, meta: dict[str, Any], keys: list[dict[str, Any]]
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    def add(severity: str, text: str) -> None:
        findings.append({"severity": severity, "finding": text})

    if meta.get("issuer", "").rstrip("/") != issuer.rstrip("/"):
        add(
            "high",
            f"The document's issuer ({meta.get('issuer')}) differs from {issuer}: tokens must be checked against the document's issuer exactly",
        )
    for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if meta.get(name) and not str(meta[name]).startswith("https://"):
            add("high", f"{name} is not HTTPS")
    pkce = meta.get("code_challenge_methods_supported")
    if pkce is None:
        add(
            "medium",
            "PKCE support isn't advertised (code_challenge_methods_supported); confirm it supports S256 before relying on it",
        )
    elif "S256" not in pkce:
        add(
            "high",
            "PKCE with S256 isn't supported: public clients (SPAs, mobile apps) need it",
        )
    grants = meta.get("grant_types_supported") or []
    responses = meta.get("response_types_supported") or []
    if "implicit" in grants or any("token" in r.split() for r in responses):
        add(
            "medium",
            "The implicit flow is offered: don't use it (OAuth 2.1 removes it); use the authorization code flow with PKCE",
        )
    if "password" in grants:
        add(
            "medium",
            "The password grant is enabled: don't use it (OAuth 2.1 removes it); apps should never handle users' passwords",
        )
    algs = meta.get("id_token_signing_alg_values_supported") or []
    if "none" in algs:
        add(
            "high",
            "Unsigned tokens (alg none) are advertised: pin your validator to the asymmetric algorithm you use",
        )
    for key in keys:
        if key.get("bits") and key["bits"] < 2048:
            add(
                "high",
                f"Signing key {key.get('kid')} is RSA-{key['bits']}: use at least 2048 bits",
            )
    if not keys:
        add("high", "The JWKS has no keys: tokens can't be verified")
    if meta.get("registration_endpoint"):
        add(
            "info",
            "Dynamic client registration is available (MCP clients can register themselves); make sure it is restricted as you intend",
        )
    return findings


def _time(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(value), UTC).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def token_findings(
    header: dict[str, Any], claims: dict[str, Any], now: float
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    def add(severity: str, text: str) -> None:
        findings.append({"severity": severity, "finding": text})

    alg = str(header.get("alg", ""))
    if alg.lower() == "none":
        add(
            "critical", "alg is none: the token is unsigned. A validator must reject it"
        )
    elif alg.startswith("HS"):
        add(
            "medium",
            f"{alg} uses a shared secret: every service that verifies it can also mint tokens. Prefer RS256/ES256 from an identity provider; if HS256 is intended, pin algorithms=['{alg}'] so an RS public key can't be used as the secret",
        )
    if "jku" in header or "x5u" in header:
        add(
            "high",
            "The header points to its own key URL (jku/x5u): never fetch keys from the token; use the issuer's configured JWKS",
        )
    if "exp" not in claims:
        add("high", "No exp claim: the token never expires")
    else:
        exp = float(claims["exp"])
        if exp < now:
            add("info", f"Expired at {_time(exp)}")
        issued = float(claims.get("iat") or claims.get("nbf") or now)
        hours = (exp - issued) / 3600
        if hours > 24:
            add(
                "medium",
                f"Lifetime is {hours:.0f} hours: keep access tokens short (5 to 60 minutes) and use refresh tokens",
            )
    if "nbf" in claims and float(claims["nbf"]) > now + 60:
        add("info", "Not valid yet (nbf is in the future)")
    if "aud" not in claims and "client_id" not in claims:
        add(
            "medium",
            "No aud claim: an API can't tell whether the token was issued for it",
        )
    if "iss" not in claims:
        add("medium", "No iss claim: validators can't check who issued it")
    if claims.get("token_use") == "id" or (
        "nonce" in claims and "scope" not in claims and "scp" not in claims
    ):
        add(
            "medium",
            "This looks like an ID token: it proves a sign-in to the client app; APIs must accept access tokens instead",
        )
    personal = sorted(PERSONAL_CLAIMS & claims.keys())
    if personal:
        add(
            "info",
            f"Carries personal data ({', '.join(personal)}): JWTs are only encoded, not encrypted, so anyone holding it can read them",
        )
    return findings


def describe_claims(claims: dict[str, Any]) -> dict[str, Any]:
    shown: dict[str, Any] = {}
    for name, value in claims.items():
        if name in SHOWN_CLAIMS:
            shown[name] = (
                _time(value) if name in ("exp", "iat", "nbf", "auth_time") else value
            )
    if "sub" in claims:
        sub = str(claims["sub"])
        shown["sub"] = f"{sub[:4]}… ({len(sub)} characters)"
    return {
        "claims": shown,
        "other_claims": sorted(set(claims) - SHOWN_CLAIMS - {"sub"}),
    }


async def verify(
    token: str, header: dict[str, Any], issuer: str, audience: str | None
) -> dict[str, Any]:
    """Check the signature with the issuer's published keys, and iss, aud, exp and nbf."""
    alg = str(header.get("alg", ""))
    if not alg.startswith(ASYMMETRIC):
        return {
            "verified": False,
            "reason": f"{alg or 'This algorithm'} can't be checked against published keys (it needs the shared secret, which must never be shared here)",
        }
    _, meta = await discovery(issuer)
    jwks = await _json(meta["jwks_uri"]) if meta.get("jwks_uri") else {}
    try:
        keys = {k.key_id: k for k in jwt.PyJWKSet.from_dict(jwks).keys}
    except jwt.PyJWTError as exc:
        return {
            "verified": False,
            "reason": f"The issuer's JWKS couldn't be read: {exc}",
        }
    key = (
        keys.get(header.get("kid"))
        if header.get("kid")
        else (next(iter(keys.values())) if len(keys) == 1 else None)
    )
    if key is None:
        return {
            "verified": False,
            "reason": f"No published key has kid {header.get('kid')!r}: the token wasn't signed by this issuer's current keys",
        }
    try:
        jwt.decode(
            token,
            key=key,
            algorithms=[alg],
            issuer=meta.get("issuer", issuer),
            audience=audience,
            options={"verify_aud": audience is not None, "require": ["exp"]},
            leeway=60,
        )
    except jwt.PyJWTError as exc:
        return {"verified": False, "reason": f"{type(exc).__name__}: {exc}"}
    checked = "signature, issuer, expiry" + (
        " and audience" if audience else " (audience not checked: none given)"
    )
    return {"verified": True, "checked": checked}


def cookie_flags(raw: str) -> dict[str, Any]:
    name, _, rest = raw.partition("=")
    attrs = {
        a.split("=", 1)[0].strip().lower(): (
            a.split("=", 1)[1].strip() if "=" in a else True
        )
        for a in rest.split(";")[1:]
    }
    return {
        "name": name.strip(),
        "secure": "secure" in attrs,
        "httponly": "httponly" in attrs,
        "samesite": attrs.get("samesite") or "not set",
    }


def header_findings(
    headers: dict[str, str], cookies: list[dict[str, Any]], https_redirect: bool | None
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    def add(severity: str, text: str) -> None:
        findings.append({"severity": severity, "finding": text})

    if https_redirect is False:
        add("high", "http:// doesn't redirect to https://")
    hsts = headers.get("strict-transport-security", "")
    if not hsts:
        add("medium", "No Strict-Transport-Security header")
    csp = headers.get("content-security-policy", "")
    if not csp:
        add(
            "medium",
            "No Content-Security-Policy: a CSP limits the damage of an XSS bug, which could otherwise read tokens kept in JavaScript",
        )
    elif "'unsafe-inline'" in csp and "script-src" in csp:
        add("low", "The CSP allows inline scripts ('unsafe-inline' in script-src)")
    if "x-frame-options" not in headers and "frame-ancestors" not in csp:
        add(
            "low",
            "No X-Frame-Options or CSP frame-ancestors: the sign-in page could be framed (clickjacking)",
        )
    if headers.get("x-content-type-options", "").lower() != "nosniff":
        add("low", "No X-Content-Type-Options: nosniff")
    if (
        headers.get("access-control-allow-origin") == "*"
        and headers.get("access-control-allow-credentials") == "true"
    ):
        add("high", "CORS allows any origin with credentials")
    for cookie in cookies:
        missing = [flag for flag in ("secure", "httponly") if not cookie[flag]]
        if missing:
            add(
                "medium",
                f"Cookie {cookie['name']} lacks {' and '.join(missing).replace('httponly', 'HttpOnly').replace('secure', 'Secure')}; session and token cookies need both",
            )
        if cookie["samesite"] == "not set" or str(cookie["samesite"]).lower() == "none":
            add(
                "low",
                f"Cookie {cookie['name']} has SameSite={cookie['samesite']}: use Lax or Strict for session cookies unless cross-site use is needed",
            )
    return findings


def create_server() -> MCPServer:
    mcp = MCPServer(
        name="auth",
        instructions=(
            "Read-only checks for OAuth 2.0 / OpenID Connect sign-in and JWT validation: an identity provider's "
            "setup, a token's header and claims, and a site's security headers and cookies."
        ),
    )

    @mcp.tool(annotations=READ_ONLY)
    async def check_identity_provider(issuer: str) -> dict:
        """Read an OAuth / OpenID Connect issuer's discovery document and signing keys, and flag weak settings
        (no PKCE S256, implicit or password grants, unsigned tokens, short RSA keys, issuer mismatch).

        Args:
            issuer: The issuer URL, e.g. https://cognito-idp.us-east-1.amazonaws.com/us-east-1_AbC123,
                https://dev-123.us.auth0.com/ or https://accounts.google.com.
        """
        url, meta = await discovery(issuer)
        keys: list[dict[str, Any]] = []
        if meta.get("jwks_uri"):
            jwks = await _json(meta["jwks_uri"])
            keys = [
                describe_key(k) for k in jwks.get("keys", []) if isinstance(k, dict)
            ][:10]
        fields = (
            "issuer",
            "authorization_endpoint",
            "token_endpoint",
            "jwks_uri",
            "userinfo_endpoint",
            "end_session_endpoint",
            "revocation_endpoint",
            "registration_endpoint",
            "grant_types_supported",
            "response_types_supported",
            "code_challenge_methods_supported",
            "id_token_signing_alg_values_supported",
            "token_endpoint_auth_methods_supported",
        )
        return {
            "discovery_url": url,
            **{name: meta[name] for name in fields if name in meta},
            "scopes_supported": (meta.get("scopes_supported") or [])[:25],
            "signing_keys": keys,
            "findings": provider_findings(issuer, meta, keys),
        }

    @mcp.tool(annotations=READ_ONLY)
    async def inspect_jwt(
        token: str, issuer: str | None = None, audience: str | None = None
    ) -> dict:
        """Decode a JWT's header and claims and flag risky ones (alg none, HS256, no expiry, long lifetime, no
        audience, an ID token used as an access token, personal data). With an issuer, also verify the signature
        against the issuer's published keys and check iss, exp and (with an audience) aud. The signature itself is
        never returned, and claims that may identify a person are listed by name only. Use test tokens.

        Args:
            token: The JWT (three base64url parts separated by dots), with or without a "Bearer " prefix.
            issuer: The issuer to verify against (its https URL), optional.
            audience: The audience the API expects, optional.
        """
        token = token.strip().removeprefix("Bearer ").strip()
        if token.count(".") != 2:
            raise AuthToolError(
                "Not a JWT: expected three parts separated by dots (an encrypted JWE has five)"
            )
        try:
            header = jwt.get_unverified_header(token)
            claims = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as exc:
            raise AuthToolError(f"Not a valid JWT: {exc}") from exc
        result: dict[str, Any] = {
            "header": {
                k: header[k]
                for k in ("alg", "typ", "kid", "cty", "jku", "x5u")
                if k in header
            },
            **describe_claims(claims),
            "findings": token_findings(header, claims, time.time()),
        }
        if issuer:
            result["verification"] = await verify(token, header, issuer, audience)
        return result

    @mcp.tool(annotations=READ_ONLY)
    async def check_security_headers(url: str) -> dict:
        """Check a public site's HTTPS redirect, security headers (HSTS, CSP, framing, nosniff, CORS) and the
        flags on the cookies it sets (Secure, HttpOnly, SameSite; never their values). One ordinary GET request,
        like a browser's.

        Args:
            url: The page, e.g. the app's sign-in page or an API URL.
        """
        resp, final_url, _ = await fetch(url, read_body=False, user_agent=USER_AGENT)
        headers = {k.lower(): v for k, v in resp.headers.items()}
        cookies = [cookie_flags(c) for c in resp.headers.get_list("set-cookie")]
        https_redirect = None
        parts = urlsplit(url)
        if parts.scheme == "https":
            try:
                _, plain_final, _ = await fetch(
                    urlunsplit(("http", *parts[1:])),
                    read_body=False,
                    user_agent=USER_AGENT,
                )
                https_redirect = plain_final.startswith("https://")
            except (
                Exception
            ):  # plain HTTP refused or unreachable: nothing served insecurely
                https_redirect = None
        wanted = (
            "strict-transport-security",
            "content-security-policy",
            "x-frame-options",
            "x-content-type-options",
            "referrer-policy",
            "permissions-policy",
            "access-control-allow-origin",
            "access-control-allow-credentials",
        )
        return {
            "final_url": final_url,
            "status": resp.status_code,
            "headers": {
                name: headers[name][:400] for name in wanted if name in headers
            },
            "cookies": cookies,
            "http_redirects_to_https": https_redirect,
            "findings": header_findings(headers, cookies, https_redirect),
        }

    return mcp


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        create_server().streamable_http_app(host="127.0.0.1"),
        host="127.0.0.1",
        port=int(os.getenv("MCP_PORT", "8106")),
    )
