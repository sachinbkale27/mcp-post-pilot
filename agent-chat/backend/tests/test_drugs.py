"""The Drug Information agent's in-process MCP server (openFDA and RxNorm calls are faked)."""

import json
from pathlib import Path

from app.local_mcp import drugs
from app.local_mcp.drugs import label_card, label_query, passages
from app.specialists import AgentSpec, parse_agents
from app.specialists.runner import connect

SET_ID = "27f15fac-7d98-4114-a2ec-92494a91da98"
LABEL = {
    "set_id": SET_ID,
    "effective_time": "20260730",
    "openfda": {
        "brand_name": ["OZEMPIC"], "generic_name": ["SEMAGLUTIDE"], "manufacturer_name": ["Novo Nordisk"],
        "route": ["SUBCUTANEOUS"], "product_type": ["HUMAN PRESCRIPTION DRUG"],
    },
    "indications_and_usage": ["1 INDICATIONS AND USAGE OZEMPIC is indicated as an adjunct to diet and exercise to improve glycemic control in adults with type 2 diabetes mellitus."],
    "boxed_warning": ["WARNING: RISK OF THYROID C-CELL TUMORS. In rodents, semaglutide causes thyroid C-cell tumors."],
    "drug_interactions": ["7.1 Concomitant Use with an Insulin Secretagogue or with Insulin. Patients may be at increased risk of hypoglycemia. 7.2 Oral Medications. OZEMPIC delays gastric emptying."],
}
GENERIC = {**LABEL, "set_id": "11111111-2222-3333-4444-555555555555", "effective_time": "20231117"}


def data(result) -> dict:
    return json.loads(result.content[0].text)


async def fake_get(url, params, source):
    if url.endswith("/approximateTerm.json"):
        return {"approximateGroup": {"candidate": [{"rxcui": "1991307", "name": "Ozempic"}]}}
    if url.endswith("/allrelated.json"):
        return {"allRelatedGroup": {"conceptGroup": [
            {"tty": "IN", "conceptProperties": [{"name": "semaglutide"}]},
            {"tty": "BN", "conceptProperties": [{"name": "Ozempic"}, {"name": "Wegovy"}]},
        ]}}
    if url.endswith("/label.json"):
        if params["search"].startswith("set_id:"):
            return {"results": [LABEL]} if SET_ID in params["search"] else {}
        return {"meta": {"results": {"total": 2}}, "results": [LABEL, GENERIC]}
    if url.endswith("/event.json"):
        if "count" in params:
            return {"results": [{"term": "NAUSEA", "count": 10674}, {"term": "OFF LABEL USE", "count": 7325}, {"term": "VOMITING", "count": 6964}]}
        return {"meta": {"results": {"total": 73001}}}
    if url.endswith("/enforcement.json"):
        return {}  # openFDA answers 404 for no matches
    raise AssertionError(url)


def test_label_query_and_card():
    assert label_query(["Ozempic", 'semaglutide"']) == (
        'openfda.brand_name:"Ozempic" OR openfda.generic_name:"Ozempic" OR '
        'openfda.brand_name:"semaglutide" OR openfda.generic_name:"semaglutide"'
    )
    card = label_card(LABEL)
    assert card["brand"] == "Ozempic" and card["type"] == "prescription drug" and card["updated"] == "2026-07-30"
    assert card["sections"] == ["uses", "boxed_warning", "interactions"]
    assert card["url"].endswith(SET_ID)


def test_passages_keep_only_matching_sentences():
    text = LABEL["drug_interactions"][0]
    assert passages(text, ["insulin"]).startswith("7.1 Concomitant Use") and "gastric" not in passages(text, ["insulin"])


def test_drugs_agent_is_configured_in_process(monkeypatch):
    monkeypatch.delenv("DRUGS_MCP_URL", raising=False)
    path = Path(__file__).parents[1] / "app" / "specialists" / "agents.json"
    specs = {s.name: s for s in parse_agents(json.loads(path.read_text()), path.parent)}
    assert specs["drugs"].mcp_url == "local:drugs" and specs["drugs"].report_tool == "submit_drug_info"


async def test_answers_only_carry_facts_quoted_from_labels_it_read(monkeypatch):
    monkeypatch.setattr(drugs, "get_json", fake_get)
    spec = AgentSpec(name="drugs", title="t", description="d", mcp_url="local:drugs", prompt="p")
    quoted = {"point": "It can cause low blood sugar with insulin.", "set_id": SET_ID, "section": "interactions",
              "quote": "may be at increased risk of hypoglycemia"}
    invented = {**quoted, "point": "It is safe with alcohol.", "quote": "safe to drink alcohol while taking it"}

    async with connect(spec) as mcp:
        assert {t.name for t in (await mcp.list_tools()).tools} == {"find_drug", "read_label", "side_effect_reports", "recalls", "submit_drug_info"}
        refused = await mcp.call_tool("submit_drug_info", {"drug": "Ozempic", "summary_text": "s", "facts": [quoted]})
        assert refused.is_error and "not read in this session" in refused.content[0].text

        found = data(await mcp.call_tool("find_drug", {"name": "ozempik"}))
        assert found["rxnorm"]["ingredients"] == ["semaglutide"] and found["labels"][0]["set_id"] == SET_ID
        assert len(found["labels"]) == 1  # the older label for the same product is a duplicate

        read = data(await mcp.call_tool("read_label", {"set_id": SET_ID, "about": ["insulin"]}))
        assert list(read["text"]) == ["interactions"] and "hypoglycemia" in read["text"]["interactions"]
        none = data(await mcp.call_tool("read_label", {"set_id": SET_ID, "about": ["warfarin"]}))
        assert none["text"] == {} and "doesn't mention warfarin" in none["note"]

        reports = data(await mcp.call_tool("side_effect_reports", {"name": "Ozempic"}))
        assert reports["drug"] == "semaglutide" and reports["total"] == 73001
        assert data(await mcp.call_tool("recalls", {"name": "Ozempic"}))["items"] == []

        # a quote filed under the wrong section of the label is moved to the right one
        misfiled = {**quoted, "point": "Ozempic is for type 2 diabetes.", "section": "warnings", "quote": "improve glycemic control in adults with type 2 diabetes"}
        filed = await mcp.call_tool("submit_drug_info", {
            "drug": "Ozempic", "summary_text": "Ozempic treats type 2 diabetes.", "facts": [quoted, invented, misfiled],
            "include_reports": True, "include_recalls": True,
        })
        assert not filed.is_error  # refused once already: the unsupported fact is left out
        out = data(filed)
        assert [(f["point"], f["section"]) for f in out["facts"]] == [(quoted["point"], "interactions"), (misfiled["point"], "uses")]
        report = out["result"]
        assert f"[DailyMed](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={SET_ID})" in report
        assert "73,001 adverse event reports mention semaglutide" in report and "| Nausea | 10,674 |" in report and "Off label" not in report
        assert "FDA recalls**: none found" in report and "1 point(s) were left out" in report
        assert "not medical advice" in report

        bad = await mcp.call_tool("read_label", {"set_id": "not-an-id"})
        assert bad.is_error


def test_drugs_endpoint_streams_the_agent(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main

    async def fake_run(question):
        assert question == "What is metformin for?"
        yield {"type": "drug_report", "report": "Metformin treats type 2 diabetes."}

    monkeypatch.setattr(main, "run_drugs", fake_run)
    with TestClient(main.app) as client:
        body = client.post("/drugs", json={"question": "What is metformin for?"}).text
    assert "event: drug_report" in body and "event: done" in body


def test_a_refused_quote_gets_the_closest_label_sentence():
    text = "7.1 Use with Insulin. Patients may be at increased risk of hypoglycemia. 7.2 Oral Medications."
    assert drugs.closest_sentence("patients could have a higher risk of hypoglycaemia", text) == "Patients may be at increased risk of hypoglycemia."
