"""MCP server for checking facts on the web: search, read pages, check links.

It runs inside the agent service (agents.json: "mcp_url": "local:research"), so it needs no deployment
of its own; `python -m app.local_mcp.research` also serves it over Streamable HTTP for the MCP Inspector.

  web_search     finds sources with OpenAI's web search tool (the agent's own OPENAI_API_KEY)
  fetch_page     reads a page as text, optionally only the passages about some terms
  check_links    reports whether links resolve
  submit_report  files the verdicts. A verdict that cites a source is only accepted when that page was
                 fetched in this session and the quoted evidence is on it, so a report can't rest on
                 search summaries or memory

Each connection gets its own server (create_server), which remembers the pages it fetched.

Pages are fetched from the public internet only: private, loopback and link-local addresses, other
ports and non-HTTP schemes are refused, and every redirect is checked the same way.
"""

import asyncio
import ipaddress
import os
import re
import socket
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

SEARCH_MODEL = os.getenv("OPENAI_SEARCH_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-2024-11-20"
MAX_BYTES = 3_000_000
MAX_REDIRECTS = 5
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/json", "application/xml", "text/xml")
USER_AGENT = "PostPilotFactCheck/1.0 (+https://blog.sachin-kale.com)"

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


class FetchError(ToolError):
    """ToolError messages are shown to the model."""


# ---------------------------------------------------------------- safe fetching


def _check_ip(host: str, address: str) -> None:
    ip = ipaddress.ip_address(address)
    if not ip.is_global:
        raise FetchError(f"{host} resolves to a non-public address; only public web pages can be fetched")


async def check_url(url: str) -> None:
    """Refuse anything but http(s) on the default ports to public addresses."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError(f"Not an http(s) URL: {url}")
    if parts.username or parts.password:
        raise FetchError("URLs with credentials are not allowed")
    if parts.port not in (None, 80, 443):
        raise FetchError(f"Port {parts.port} is not allowed")
    host = parts.hostname
    try:
        _check_ip(host, host)  # an IP literal
        return
    except ValueError:
        pass
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(f"Could not resolve {host}") from exc
    for info in infos:
        _check_ip(host, info[4][0])


async def fetch(
    url: str, *, read_body: bool = True, max_bytes: int = MAX_BYTES, user_agent: str = USER_AGENT
) -> tuple[httpx.Response, str, bytes]:
    """GET a public URL, following redirects one checked hop at a time. Returns (response, final URL, body).

    Reading stops after max_bytes: a body longer than max_bytes means the resource is larger.
    """
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(12, connect=5), headers={"user-agent": user_agent}, follow_redirects=False
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await check_url(url)
            async with client.stream("GET", url) as resp:
                if resp.is_redirect and "location" in resp.headers:
                    url = urljoin(url, resp.headers["location"])
                    continue
                body = b""
                if read_body:
                    async for chunk in resp.aiter_bytes():
                        body += chunk
                        if len(body) > max_bytes:
                            break
                return resp, url, body[: max_bytes + 1]
    raise FetchError(f"Too many redirects from {url}")


# ---------------------------------------------------------------- HTML to text

SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "head"}
BLOCK = {
    "p",
    "div",
    "section",
    "article",
    "li",
    "tr",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "pre",
    "table",
    "ul",
    "ol",
    "dd",
    "dt",
    "figcaption",
    "header",
    "footer",
    "main",
    "aside",
    "nav",
}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag in SKIP:
            self._skip += 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """Returns (title, text) with one paragraph per line."""
    parser = _TextParser()
    parser.feed(html)
    lines = (re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).split("\n"))
    return re.sub(r"\s+", " ", parser.title).strip(), "\n".join(line for line in lines if line)


def _terms(text: str) -> list[str]:
    return [t for t in re.findall(r"[\w.%-]+", text.lower()) if len(t) > 2 or t.isdigit()]


def find_passages(text: str, focus: str, limit: int = 8) -> list[str]:
    """The sentences that mention the most focus terms, each with its neighbours, in page order."""
    terms = set(_terms(focus))
    scored = []
    for p, para in enumerate(text.split("\n")):
        sentences = re.split(r"(?<=[.!?])\s+", para)
        for i, sentence in enumerate(sentences):
            if score := len(terms & set(_terms(sentence))):
                scored.append((score, (p, i), " ".join(sentences[max(0, i - 1) : i + 2])[:1200]))
    best = sorted(scored, key=lambda s: (-s[0], s[1]))[:limit]
    return list(dict.fromkeys(passage for _, _, passage in sorted(best, key=lambda s: s[1])))


# ---------------------------------------------------------------- tools


# NCBI answers scripts with a bot check (reCAPTCHA, cookie wall) on its web pages, and asks programs to use
# its E-utilities API instead; the same records are read from there.
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_PAGES = [
    (re.compile(r"^https?://pubmed\.ncbi\.nlm\.nih\.gov/(\d+)"), "pubmed"),
    (re.compile(r"^https?://(?:pmc\.ncbi\.nlm\.nih\.gov|(?:www\.)?ncbi\.nlm\.nih\.gov/pmc)/articles/PMC(\d+)"), "pmc"),
    (re.compile(r"^https?://(?:www\.)?ncbi\.nlm\.nih\.gov/clinvar/variation/(\d+)"), "clinvar"),
    (re.compile(r"^https?://(?:www\.)?ncbi\.nlm\.nih\.gov/gene/(\d+)"), "gene"),
]
BOT_CHECK = re.compile(
    r"checking your browser|recaptcha|just a moment|attention required|are you a robot|verify you are human"
    r"|enable (?:cookies|javascript)",
    re.IGNORECASE,
)


_ncbi_lock = asyncio.Lock()
_ncbi_last = 0.0


async def _ncbi_get(client: httpx.AsyncClient, endpoint: str, params: dict) -> httpx.Response:
    """GET from E-utilities within NCBI's limit of 3 requests a second, retrying when it answers 429."""
    global _ncbi_last
    for attempt in range(3):
        async with _ncbi_lock:
            loop = asyncio.get_running_loop()
            await asyncio.sleep(max(0.0, _ncbi_last + 0.35 - loop.time()))
            _ncbi_last = loop.time()
            resp = await client.get(f"{EUTILS}/{endpoint}", params=params)
        if resp.status_code != 429 or attempt == 2:
            break
        await asyncio.sleep(1 + attempt)
    resp.raise_for_status()
    return resp


async def _ncbi_record(db: str, uid: str) -> tuple[str, str]:
    """(title, text) of a PubMed article, ClinVar variant or Gene record, from E-utilities."""
    params = {"db": db, "id": uid, "tool": "post-pilot-factcheck"}
    async with httpx.AsyncClient(timeout=15, headers={"user-agent": USER_AGENT}) as client:
        if db == "pubmed":
            resp = await _ncbi_get(client, "efetch.fcgi", {**params, "rettype": "abstract", "retmode": "text"})
            # Paragraphs are separated by blank lines and hard-wrapped inside
            paragraphs = [" ".join(p.split()) for p in resp.text.strip().split("\n\n")]
            return paragraphs[1] if len(paragraphs) > 1 else "", "\n".join(paragraphs)
        if db == "pmc":  # full text as JATS XML
            resp = await _ncbi_get(client, "efetch.fcgi", params)
            title = re.search(r"<article-title[^>]*>(.*?)</article-title>", resp.text, re.DOTALL)
            body = re.sub(r"</(p|title|td|th|caption)>", r"</\1>\n", resp.text)
            return html_to_text(re.sub(r"<[^>]+>", "", title.group(1)) if title else "")[1], html_to_text(body)[1]
        resp = await _ncbi_get(client, "esummary.fcgi", {**params, "retmode": "json"})
    record = resp.json().get("result", {}).get(uid)
    if not record or "error" in record:
        raise FetchError(f"No {db} record {uid}")
    if db == "gene":
        title = f"{record.get('name')} - {record.get('description')}"
        lines = [
            title,
            f"Organism: {record.get('organism', {}).get('scientificname')}",
            f"Aliases: {record.get('otheraliases')}",
            f"Location: {record.get('maplocation')}",
            f"Summary: {record.get('summary')}",
        ]
    else:
        germline = record.get("germline_classification") or {}
        traits = [t.get("trait_name") for t in germline.get("trait_set", [])]
        title = record.get("title", "")
        lines = [
            title,
            f"Classification: {germline.get('description')}",
            f"Review status: {germline.get('review_status')}",
            f"Last evaluated: {germline.get('last_evaluated')}",
            f"Conditions: {'; '.join(t for t in traits if t)}",
            f"Genes: {', '.join(g.get('symbol', '') for g in record.get('genes', []))}",
            f"Variant type: {record.get('obj_type')}",
        ]
    return title, "\n".join(line for line in lines if not line.endswith(": None"))


async def _read(url: str) -> tuple[dict, str, str]:
    """(result fields, title, text) of a page, or a result with an error."""
    for pattern, db in NCBI_PAGES:
        if match := pattern.match(url):
            try:
                title, text = await _ncbi_record(db, match.group(1))
            except httpx.HTTPError as exc:
                raise FetchError(f"Could not read {db} record {match.group(1)}: {type(exc).__name__}") from exc
            return {"url": url, "final_url": url, "status": 200, "via": f"NCBI E-utilities ({db})"}, title, text
    try:
        resp, final_url, body = await fetch(url)
    except httpx.HTTPError as exc:
        raise FetchError(f"Could not fetch {url}: {type(exc).__name__}") from exc
    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    result: dict = {"url": url, "final_url": final_url, "status": resp.status_code}
    if resp.status_code >= 400:
        return {**result, "error": f"HTTP {resp.status_code}"}, "", ""
    if content_type and not content_type.startswith(TEXT_TYPES):
        return (
            {**result, "error": f"Unsupported content type {content_type}; only web pages and text can be read"},
            "",
            "",
        )
    raw = body.decode(resp.encoding or "utf-8", errors="replace")
    title, text = html_to_text(raw) if "html" in content_type or raw.lstrip()[:1] == "<" else ("", raw)
    if len(text) < 1500 and BOT_CHECK.search(f"{title}\n{text}"):
        error = "The site blocks automated reading (bot check). Don't count this as evidence either way; find another source."
        return {**result, "error": error}, title, ""
    return result, title, text


def _clean(url: str) -> str:
    """Drop the utm_* tracking parameters web search adds to links."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.startswith("utm_")]
    return urlunsplit(parts._replace(query=urlencode(query)))


def _key(url: str) -> str:
    parts = urlsplit(_clean(url.strip()))
    return f"{parts.netloc.lower().removeprefix('www.')}{parts.path.rstrip('/')}?{parts.query}"


def _normalize(text: str) -> str:
    text = text.lower().replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    return " ".join(re.findall(r"[a-z0-9%]+(?:[.,][0-9]+)?", text))


QUOTED = re.compile(r'"([^"]+)"|\u201c([^\u201d]+)\u201d')


def quote_found(quote: str, page: str) -> bool:
    """Whether every part of the quote (parts split at ellipses) appears on the page, ignoring case and punctuation.

    When the evidence has quotation marks (The paper says, "..."), only the quoted text has to match.
    """
    quoted = [a or b for a, b in QUOTED.findall(quote)]
    parts = [_normalize(p) for q in (quoted or [quote]) for p in re.split(r"\.\.\.|\u2026", q)]
    parts = [p for p in parts if p]
    normalized = _normalize(page)
    return sum(len(p) for p in parts) >= 15 and all(p in normalized for p in parts)


STOPWORDS = set(
    "about after also and are been being between both but can could does from has have into its more most such "
    "than that the their them then there these they this those through very was were what when which while who "
    "will with would recent include includes including like".split()
)


def on_topic(claim: str, evidence: str) -> bool:
    """Whether the evidence is about the claim: it shares one of the claim's numbers, or two of its key words
    (or the only one)."""
    claim_terms, evidence_terms = set(_terms(_normalize(claim))), set(_terms(_normalize(evidence)))
    numbers = {t for t in claim_terms if any(ch.isdigit() for ch in t)}
    words = {t for t in claim_terms - numbers if len(t) > 3 and t not in STOPWORDS}
    return bool(numbers & evidence_terms) or len(words & evidence_terms) >= min(2, len(words))


Verdict = Literal["supported", "partly supported", "contradicted", "outdated", "unverified"]
NEEDS_SOURCE = {"supported", "partly supported", "contradicted", "outdated"}


class ClaimCheck(BaseModel):
    claim: str = Field(description="The claim, in the checked text's own words")
    verdict: Verdict
    evidence: str = Field(
        description="For a verdict with a source: an exact quote from the fetched page (use ... between parts). "
        "For unverified: what you searched for and why it didn't settle the claim"
    )
    source_url: str | None = Field(None, description="The page the evidence is quoted from, as passed to fetch_page")
    fix: str | None = Field(None, description="For partly supported, contradicted or outdated: how to correct the text")


def _cell(text: str | None) -> str:
    return " ".join((text or "").split()).replace("|", "\\|")


def format_report(
    claims: list[ClaimCheck], broken_links: list[str], skipped: list[str], overall: str, notes: list[str] = ()
) -> str:
    rows = [
        f"| {_cell(c.claim)} | {c.verdict.capitalize()} | {_cell(c.evidence)} | {c.source_url or ''} | {_cell(c.fix)} |"
        for c in claims
    ]
    counts = ", ".join(
        f"{sum(c.verdict == v for c in claims)} {v}" for v in Verdict.__args__ if any(c.verdict == v for c in claims)
    )
    lines = [
        f"**Fact-check: {overall}** ({len(claims)} claims checked: {counts})",
        "",
        "| Claim | Verdict | Evidence | Source | Fix |",
        "|---|---|---|---|---|",
        *rows,
    ]
    if broken_links:
        lines += ["", "Broken links: " + ", ".join(broken_links)]
    if skipped:
        lines += ["", "Not checked: " + "; ".join(skipped)]
    lines += ["", *notes] if notes else []
    return "\n".join(lines)


def create_server() -> MCPServer:
    """A research server for one fact-check session; it remembers the pages fetched in it."""
    mcp = MCPServer(
        name="research",
        instructions=(
            "Tools for checking claims against web sources. web_search finds candidate sources; its summary is "
            "machine-written, so read the source with fetch_page before relying on it. File the verdicts with "
            "submit_report: a verdict that cites a source must quote a page fetched in this session."
        ),
    )
    pages: dict[str, str] = {}  # page key -> text, for every page fetched in this session
    refusals: list[dict] = []  # submit_report refuses one report, then downgrades what it can't confirm

    @mcp.tool(annotations=READ_ONLY)
    async def fetch_page(url: str, focus: str | None = None, max_chars: int = 6000) -> dict:
        """Read a web page as plain text. PubMed, ClinVar and NCBI Gene links are read from NCBI's API.

        Args:
            url: The page's http(s) URL.
            focus: Words, a number or a quote to look for. When given, the result has the passages that mention
                them and whether the exact phrase appears, instead of the start of the page.
            max_chars: How much text to return without focus (at most 20000).
        """
        result, title, text = await _read(url)
        if "error" in result:
            return result
        pages[_key(url)] = pages[_key(result["final_url"])] = f"{title}\n{text}"
        result["title"] = title
        if focus:
            normalized = re.sub(r"\s+", " ", text).lower()
            passages = find_passages(text, focus)
            return {
                **result,
                "exact_phrase_found": re.sub(r"\s+", " ", focus).strip().lower() in normalized,
                # A short record (e.g. from NCBI) is returned whole: it is all relevant
                **({"text": text} if len(text) < 3000 else {"passages": passages}),
            }
        limit = max(500, min(max_chars, 20000))
        return {**result, "text": text[:limit], "truncated": len(text) > limit}

    @mcp.tool(annotations=READ_ONLY)
    async def check_links(urls: list[str]) -> list[dict]:
        """Check whether links work: HTTP status and where they end up after redirects (at most 20 links).

        Args:
            urls: The links to check.
        """
        if len(urls) > 20:
            raise FetchError("Check at most 20 links at a time")
        limit = asyncio.Semaphore(6)

        async def one(url: str) -> dict:
            async with limit:
                try:
                    resp, final_url, _ = await fetch(url, read_body=False)
                except (httpx.HTTPError, ToolError) as exc:
                    return {"url": url, "ok": False, "error": str(exc) or type(exc).__name__}
                return {"url": url, "ok": resp.status_code < 400, "status": resp.status_code, "final_url": final_url}

        return await asyncio.gather(*(one(u) for u in urls))

    @mcp.tool(annotations=READ_ONLY)
    async def web_search(query: str) -> dict:
        """Search the web for sources about a claim or topic.

        Returns a short machine-written summary with the sources it is based on. The summary can be wrong:
        open the most relevant sources with fetch_page to confirm what they say.

        Args:
            query: What to look for, e.g. the claim to check or a question about it.
        """
        from openai import APIError, AsyncOpenAI

        try:
            response = await AsyncOpenAI(timeout=45).responses.create(
                model=SEARCH_MODEL,
                tools=[{"type": "web_search", "search_context_size": "medium"}],
                tool_choice="required",
                input=(
                    "Find reliable sources about the following. Summarize briefly what the sources say, citing them, "
                    "and note where they disagree. Do not add facts the sources don't state.\n\n" + query
                ),
            )
        except APIError as exc:
            raise ToolError(f"Web search failed: {exc.message}") from exc
        sources: dict[str, str] = {}
        for item in response.output:
            if item.type == "message":
                for part in item.content:
                    for note in getattr(part, "annotations", None) or []:
                        if note.type == "url_citation":
                            sources.setdefault(_clean(note.url), note.title)
        for item in response.output:  # sources the search consulted but the summary didn't cite
            if item.type == "web_search_call" and getattr(item.action, "type", "") == "search":
                for source in item.action.sources or []:
                    sources.setdefault(_clean(source.url), "")
        return {
            "query": query,
            "summary": re.sub(r"\?utm_source=[\w.-]+(?=\))", "", response.output_text),
            "sources": [{"url": url, "title": title} for url, title in list(sources.items())[:12]],
        }

    @mcp.tool()
    async def submit_report(
        claims: list[ClaimCheck],
        overall: Literal["ready to publish", "needs fixes", "needs major revision"],
        broken_links: list[str] | None = None,
        skipped: list[str] | None = None,
    ) -> str:
        """File the fact-check verdicts and get the formatted report. Call it once every claim is checked.

        Each supported, partly supported, contradicted or outdated verdict must quote, word for word, a page you
        read with fetch_page in this session, and the quote must be about the claim. The first report with
        verdicts that don't is refused with the reasons, so you can fix them; after that, such verdicts are
        recorded as unverified.

        Args:
            claims: One entry per checked claim.
            overall: The overall verdict on the text.
            broken_links: Links in the text that don't work.
            skipped: Claims you did not check, with the reason.
        """
        problems: dict[int, str] = {}
        for i, c in enumerate(claims):
            if c.verdict not in NEEDS_SOURCE:
                continue
            page = pages.get(_key(c.source_url)) if c.source_url else None
            if page is None:
                problems[i] = f"{c.source_url or 'no source'} was not read with fetch_page in this session"
            elif not quote_found(c.evidence, page):
                problems[i] = f"the evidence is not an exact quote (of 15+ characters) from {c.source_url}"
            elif not on_topic(c.claim, c.evidence):
                problems[i] = "the quote doesn't mention what the claim is about; quote the passage that states it"
        if problems and not refusals:
            refusals.append(problems)
            raise ToolError(
                "Report refused: "
                + "; ".join(f"claim {i + 1}: {why}" for i, why in problems.items())
                + ". Fix these (fetch the page, or quote it exactly) and submit again; unfixed ones will be "
                "recorded as unverified."
            )
        checked = [
            c.model_copy(
                update={
                    "verdict": "unverified",
                    "evidence": f"Was {c.verdict}, but the evidence could not be confirmed ({problems[i]}).",
                    "fix": None,
                }
            )
            if i in problems
            else c
            for i, c in enumerate(claims)
        ]
        notes = (
            [f"{len(problems)} verdict(s) were changed to unverified because their evidence could not be confirmed."]
            if problems
            else []
        )
        if overall == "ready to publish" and any(c.verdict != "supported" for c in checked):
            overall = "needs fixes"
            notes.append("Not ready to publish: some claims are not supported by a source.")
        return format_report(checked, broken_links or [], skipped or [], overall, notes)

    return mcp


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        create_server().streamable_http_app(host="127.0.0.1"), host="127.0.0.1", port=int(os.getenv("MCP_PORT", "8103"))
    )
