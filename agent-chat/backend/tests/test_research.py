"""The fact-check agent's in-process research MCP server (no network calls)."""

import json
from pathlib import Path

import pytest

from app.local_mcp import local_server, research
from app.local_mcp.research import FetchError, check_url, find_passages, html_to_text, on_topic, quote_found
from app.specialists import AgentSpec, parse_agents
from app.specialists.runner import connect


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://127.0.0.1/",
        "http://localhost:8102/",  # also a non-default port
        "http://[::1]/",
        "http://10.0.0.5/",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.1/",
        "https://user:pw@example.com/",
        "https://example.com:8443/",
    ],
)
async def test_refuses_non_public_urls(url):
    with pytest.raises(FetchError):
        await check_url(url)


async def test_allows_public_ip_literal():
    await check_url("https://8.8.8.8/")


def test_html_to_text_keeps_paragraphs_and_drops_scripts():
    title, text = html_to_text(
        "<html><head><title> CFTR &amp; CF </title><style>p{}</style></head>"
        "<body><nav>Menu</nav><p>F508del is the most common  CF variant.</p><script>var x=1</script>"
        "<p>It affects about 70% of alleles.</p></body></html>"
    )
    assert title == "CFTR & CF"
    assert text.split("\n") == ["Menu", "F508del is the most common CF variant.", "It affects about 70% of alleles."]


def test_find_passages_ranks_by_focus_terms_in_page_order():
    text = "Intro about genes.\nF508del accounts for 70% of CF alleles.\nUnrelated.\nF508del causes misfolding."
    assert find_passages(text, "F508del 70%", limit=2) == [
        "F508del accounts for 70% of CF alleles.",
        "F508del causes misfolding.",
    ]


def test_factcheck_agent_is_configured_in_process(monkeypatch):
    monkeypatch.delenv("FACTCHECK_MCP_URL", raising=False)
    path = Path(__file__).parents[1] / "app" / "specialists" / "agents.json"
    specs = {s.name: s for s in parse_agents(json.loads(path.read_text()), path.parent)}
    assert specs["factcheck"].mcp_url == "local:research"
    with pytest.raises(ValueError):
        local_server("nope")


async def test_connects_to_local_server_in_process():
    spec = AgentSpec(name="factcheck", title="t", description="d", mcp_url="local:research", prompt="p")
    async with connect(spec) as mcp:
        tools = {t.name for t in (await mcp.list_tools()).tools}
        assert tools == {"web_search", "fetch_page", "check_links", "submit_report"}
        result = await mcp.call_tool("fetch_page", {"url": "http://127.0.0.1:8102/agents"})
        assert result.is_error


PAGE = "F508del accounts for approximately 70% of the CF alleles in the population."


async def submit(mcp, claim: dict):
    return await mcp.call_tool("submit_report", {"claims": [claim], "overall": "needs fixes"})


async def test_report_needs_an_exact_quote_from_a_page_fetched_in_this_session(monkeypatch):
    async def fake_read(url):
        return {"url": url, "final_url": url, "status": 200}, "Genetic Variation in CF", PAGE

    monkeypatch.setattr(research, "_read", fake_read)
    url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC4029837/"
    claim = {"claim": "F508del causes 70% of cases", "verdict": "partly supported", "source_url": url,
             "evidence": "accounts for approximately 70% of the CF alleles", "fix": "Say 70% of CF alleles"}
    spec = AgentSpec(name="factcheck", title="t", description="d", mcp_url="local:research", prompt="p")

    async with connect(spec) as mcp:
        refused = await submit(mcp, claim)  # cites a page it never read
        assert refused.is_error and "was not read with fetch_page" in refused.content[0].text

        await mcp.call_tool("fetch_page", {"url": url, "focus": "70%"})
        made_up = await submit(mcp, {**claim, "evidence": "accounts for 70% of all cystic fibrosis cases"})
        assert not made_up.is_error  # refused once already: now recorded as unverified
        assert "Unverified" in made_up.structured_content["result"]
        assert "1 verdict(s) were changed to unverified" in made_up.structured_content["result"]

        # "ready to publish" needs every claim supported
        ready = await mcp.call_tool("submit_report", {"claims": [{"claim": "x", "verdict": "unverified", "evidence": "none"}], "overall": "ready to publish"})
        assert "**Fact-check: needs fixes**" in ready.structured_content["result"]

        accepted = await submit(mcp, {**claim, "source_url": url.rstrip("/"), "evidence": "approximately 70%... CF alleles in the population"})
        assert not accepted.is_error
        report = accepted.structured_content["result"]
        assert "Partly supported" in report and "1 partly supported" in report

        # unverified verdicts need no source
        assert not (await submit(mcp, {"claim": "x", "verdict": "unverified", "evidence": "searched, nothing found"})).is_error

    async with connect(spec) as fresh:  # a new delegation starts with no fetched pages
        assert (await submit(fresh, claim)).is_error


def test_evidence_must_be_about_the_claim():
    claim = "Modulators such as ivacaftor and elexacaftor-tezacaftor-ivacaftor are recent breakthroughs"
    assert not on_topic(claim, "CFTR is an anion channel in the apical membrane of epithelial cells")
    assert on_topic(claim, "elexacaftor-tezacaftor-ivacaftor, a CFTR modulator, improved lung function")
    assert on_topic("F508del causes 70% of cases", "accounts for approximately 70% of the CF alleles")


def test_passages_split_long_paragraphs_into_sentences():
    abstract = " ".join(f"Sentence {i} is filler about care." for i in range(60)) + (
        " Modulators are now available to approximately 90% of people aged 2 years or older. Later text."
    )
    assert find_passages(abstract, "approximately 90%") == [
        (
            "Sentence 59 is filler about care. Modulators are now available to approximately 90% of people aged 2 "
            "years or older. Later text."
        )
    ]


def test_quote_matching_ignores_case_punctuation_and_dashes():
    assert quote_found("Approximately 70 % ... CF alleles", PAGE.replace("70%", "70 %"))
    assert quote_found("1,480–amino acid protein", "normally 1,480-amino acid protein")
    assert not quote_found("70%", PAGE)  # too short to be evidence
