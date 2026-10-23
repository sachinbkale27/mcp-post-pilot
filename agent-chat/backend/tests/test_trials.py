"""The Clinical Trials agent's in-process MCP server (registry calls are faked)."""

import json
from pathlib import Path

from app.local_mcp import trials
from app.local_mcp.trials import Near, age_filter, search_params, sites, summary
from app.specialists import AgentSpec, parse_agents
from app.specialists.runner import connect, filed_report

STUDY = {
    "hasResults": False,
    "protocolSection": {
        "identificationModule": {"nctId": "NCT01234567", "briefTitle": "Drug A in Melanoma"},
        "statusModule": {
            "overallStatus": "RECRUITING",
            "startDateStruct": {"date": "2025-01"},
            "lastUpdatePostDateStruct": {"date": "2026-09-30"},
        },
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Acme Oncology", "class": "INDUSTRY"}},
        "conditionsModule": {"conditions": ["Melanoma"]},
        "designModule": {"phases": ["PHASE2", "PHASE3"], "studyType": "INTERVENTIONAL", "enrollmentInfo": {"count": 300}},
        "armsInterventionsModule": {"interventions": [{"name": "Drug A", "type": "DRUG"}]},
        "eligibilityModule": {"minimumAge": "18 Years", "sex": "ALL", "eligibilityCriteria": "Inclusion: progressed on at least one prior anti-PD-1 therapy"},
        "contactsLocationsModule": {
            "locations": [
                {"facility": "Far Clinic", "city": "Delhi", "country": "India", "status": "RECRUITING",
                 "geoPoint": {"lat": 28.61, "lon": 77.21}},
                {"facility": "Near Hospital", "city": "Mumbai", "state": "Maharashtra", "country": "India",
                 "status": "RECRUITING", "geoPoint": {"lat": 19.08, "lon": 72.88}},
            ]
        },
    },
}
def data(result) -> dict:
    """A tool's dict result: the runner reads it from the JSON text content, as here."""
    return json.loads(result.content[0].text)


PUNE = Near(latitude=18.52, longitude=73.86, radius_km=200, place="Pune")


def test_search_params_combine_filters():
    params = search_params(
        "melanoma", "pembrolizumab", "BRAF V600E", PUNE, None, ["RECRUITING"], ["PHASE2", "PHASE3"], 68, "female",
        "recently_updated", 5,
    )
    assert params["query.cond"] == "melanoma" and params["query.intr"] == "pembrolizumab"
    assert params["filter.geo"] == "distance(18.5200,73.8600,200km)"
    assert params["filter.overallStatus"] == "RECRUITING"
    assert params["filter.advanced"].startswith("AREA[Phase](PHASE2 OR PHASE3) AND (AREA[MinimumAge]")
    assert "AREA[Sex](ALL OR FEMALE)" in params["filter.advanced"]
    assert params["sort"] == "LastUpdatePostDate:desc" and params["pageSize"] == 5


def test_age_filter_keeps_trials_without_an_age_limit():
    assert age_filter(68) == (
        "(AREA[MinimumAge]RANGE[MIN, 68 years] OR NOT AREA[MinimumAge]RANGE[MIN, MAX]) AND "
        "(AREA[MaximumAge]RANGE[68 years, MAX] OR NOT AREA[MaximumAge]RANGE[MIN, MAX])"
    )


def test_sites_are_sorted_by_distance():
    found = sites(STUDY, PUNE)
    assert [s["facility"] for s in found] == ["Near Hospital", "Far Clinic"]
    assert 100 < found[0]["distance_km"] < 150 and found[0]["city"] == "Mumbai, Maharashtra"


def test_open_sites_come_before_closer_withdrawn_ones():
    study = json.loads(json.dumps(STUDY))
    study["protocolSection"]["contactsLocationsModule"]["locations"][1]["status"] = "WITHDRAWN"
    assert [s["facility"] for s in sites(study, PUNE)] == ["Far Clinic", "Near Hospital"]


def test_summary_is_built_from_the_record():
    card = summary(STUDY, PUNE)
    assert card["status"] == "Recruiting" and card["phases"] == ["Phase 2", "Phase 3"]
    assert card["ages"] == "18 Years to no upper limit" and card["sponsor_type"] == "Industry"
    assert card["nearest_site"]["facility"] == "Near Hospital"
    assert card["url"] == "https://clinicaltrials.gov/study/NCT01234567"


def test_trials_agent_is_configured_in_process(monkeypatch):
    monkeypatch.delenv("TRIALS_MCP_URL", raising=False)
    path = Path(__file__).parents[1] / "app" / "specialists" / "agents.json"
    specs = {s.name: s for s in parse_agents(json.loads(path.read_text()), path.parent)}
    assert specs["trials"].mcp_url == "local:trials" and specs["trials"].report_tool == "submit_trials"


async def test_report_only_accepts_trials_read_from_the_registry(monkeypatch):
    calls = []

    async def fake_get(path="", params=None):
        calls.append((path, params))
        return {"totalCount": 1, "studies": [STUDY]} if not path else STUDY

    monkeypatch.setattr(trials, "registry_get", fake_get)
    spec = AgentSpec(name="trials", title="t", description="d", mcp_url="local:trials", prompt="p")
    pick = {"nct_id": "NCT01234567", "why_matched": "For melanoma after immunotherapy",
            "evidence": "Progressed on at least one prior anti-PD-1 therapy", "to_confirm": ["No brain metastases"]}
    invented = {"nct_id": "NCT09999999", "why_matched": "x", "evidence": "Drug A in Melanoma"}

    async with connect(spec) as mcp:
        assert {t.name for t in (await mcp.list_tools()).tools} == {"search_trials", "get_trial", "trial_locations", "submit_trials"}
        refused = await mcp.call_tool("submit_trials", {"summary_text": "s", "trials": [pick]})
        assert refused.is_error and "NCT01234567: not read in this session" in refused.content[0].text

        found = await mcp.call_tool("search_trials", {"condition": "melanoma", "near": PUNE.model_dump(), "age_years": 68})
        assert data(found)["total"] == 1
        assert calls[-1][1]["filter.overallStatus"] == "RECRUITING,NOT_YET_RECRUITING"
        await mcp.call_tool("get_trial", {"nct_id": "NCT01234567"})  # keeps the search's place for the card

        made_up = {**pick, "nct_id": "NCT01234567", "evidence": "patients who progressed on osimertinib"}
        filed = await mcp.call_tool("submit_trials", {"summary_text": "Searched melanoma near Pune.", "trials": [pick, invented, made_up]})
        assert not filed.is_error  # refused once already: unread trials and unsupported matches are left out
        out = data(filed)
        assert [c["nct_id"] for c in out["trials"]] == ["NCT01234567"]
        assert out["trials"][0]["evidence"] == pick["evidence"]
        assert out["trials"][0]["nearest_site"]["city"] == "Mumbai, Maharashtra"
        assert "Left out NCT09999999" in out["result"] and "[NCT01234567](https://clinicaltrials.gov/study/NCT01234567)" in out["result"]
        assert "not medical advice" in out["result"]

        bad = await mcp.call_tool("get_trial", {"nct_id": "12345"})
        assert bad.is_error


def test_the_supervisor_gets_the_markdown_report():
    from langchain_core.messages import ToolMessage

    message = ToolMessage(json.dumps({"result": "| Trial |", "trials": []}), tool_call_id="1", name="submit_trials")
    assert filed_report([message], "submit_trials") == "| Trial |"
