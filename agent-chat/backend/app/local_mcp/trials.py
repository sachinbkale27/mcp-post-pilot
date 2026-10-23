"""MCP server for finding clinical trials in the ClinicalTrials.gov registry (API v2: public, no key).

It runs inside the agent service (agents.json: "mcp_url": "local:trials"); `python -m app.local_mcp.trials`
also serves it over Streamable HTTP for the MCP Inspector.

  search_trials    trials by condition, drug, status, phase, age, sex and distance from a place
  get_trial        one trial's design, arms, eligibility criteria and outcomes
  trial_locations  a trial's sites, nearest first
  submit_trials    files the trials to show the user. Only trials this session read from the registry are
                   accepted, and the cards are built from registry data, so a report can't carry invented
                   trial ids, statuses or sites

Each connection gets its own server (create_server), which remembers the trials it read.
"""

import math
import os
from typing import Annotated, Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

API = "https://clinicaltrials.gov/api/v2/studies"
STUDY_URL = "https://clinicaltrials.gov/study/"
USER_AGENT = "PostPilotTrials/1.0 (+https://agent.sachin-kale.com)"
NCT_ID = r"^NCT\d{8}$"
NctId = Annotated[str, Field(pattern=NCT_ID)]

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

Status = Literal[
    "RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION", "ACTIVE_NOT_RECRUITING",
    "COMPLETED", "SUSPENDED", "TERMINATED", "WITHDRAWN",
]
Phase = Literal["EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4", "NA"]

STATUS_TEXT = {
    "RECRUITING": "Recruiting", "NOT_YET_RECRUITING": "Not yet recruiting",
    "ENROLLING_BY_INVITATION": "Enrolling by invitation", "ACTIVE_NOT_RECRUITING": "Active, not recruiting",
    "COMPLETED": "Completed", "SUSPENDED": "Suspended", "TERMINATED": "Terminated", "WITHDRAWN": "Withdrawn",
}
CLOSED = {"Withdrawn", "Completed", "Terminated", "Suspended", "Active, not recruiting"}  # sites' statuses
PHASE_TEXT = {"EARLY_PHASE1": "Early phase 1", "PHASE1": "Phase 1", "PHASE2": "Phase 2", "PHASE3": "Phase 3",
              "PHASE4": "Phase 4", "NA": "Not applicable"}


class Near(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: int = Field(default=100, ge=1, le=5000)
    place: str = Field(default="", description="The place these coordinates stand for, e.g. 'Pune, India'")


class TrialPick(BaseModel):
    nct_id: str = Field(pattern=NCT_ID)
    why_matched: str = Field(description="Which of the user's criteria this trial fits, in one sentence")
    to_confirm: list[str] = Field(
        default_factory=list,
        description="Eligibility points only the trial team can confirm (key exclusions, prior treatment, biomarkers)",
    )


class RegistryError(ToolError):
    """ToolError messages are shown to the model."""


# ---------------------------------------------------------------- registry access


async def registry_get(path: str = "", params: dict[str, Any] | None = None) -> dict:
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
        try:
            resp = await client.get(API + path, params=params)
        except httpx.HTTPError as exc:
            raise RegistryError(f"ClinicalTrials.gov could not be reached ({type(exc).__name__})") from exc
    if resp.status_code == 404:
        raise RegistryError(f"No trial {path.lstrip('/')} in ClinicalTrials.gov")
    if resp.status_code == 429:
        raise RegistryError("ClinicalTrials.gov is rate-limiting requests; wait a moment and try fewer searches")
    if resp.status_code >= 400:
        raise RegistryError(f"ClinicalTrials.gov answered HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def age_filter(age: int) -> str:
    """Trials open to this age: no minimum or a minimum at most age, and no maximum or a maximum at least age."""
    return (
        f"(AREA[MinimumAge]RANGE[MIN, {age} years] OR NOT AREA[MinimumAge]RANGE[MIN, MAX]) AND "
        f"(AREA[MaximumAge]RANGE[{age} years, MAX] OR NOT AREA[MaximumAge]RANGE[MIN, MAX])"
    )


def search_params(
    condition: str, intervention: str | None, keywords: str | None, near: Near | None, country: str | None,
    statuses: list[str], phases: list[str] | None, age_years: int | None, sex: str | None, sort: str, max_results: int,
) -> dict[str, Any]:
    params: dict[str, Any] = {"query.cond": condition, "pageSize": max_results, "countTotal": "true"}
    if intervention:
        params["query.intr"] = intervention
    if keywords:
        params["query.term"] = keywords
    if country:
        params["query.locn"] = country
    if near:
        params["filter.geo"] = f"distance({near.latitude:.4f},{near.longitude:.4f},{near.radius_km}km)"
    if statuses:
        params["filter.overallStatus"] = ",".join(statuses)
    advanced = []
    if phases:
        advanced.append(f"AREA[Phase]({' OR '.join(phases)})")
    if age_years is not None:
        advanced.append(age_filter(age_years))
    if sex:
        advanced.append(f"AREA[Sex](ALL OR {sex.upper()})")
    if advanced:
        params["filter.advanced"] = " AND ".join(advanced)
    if sort == "recently_updated":
        params["sort"] = "LastUpdatePostDate:desc"
    elif sort == "newest":
        params["sort"] = "StudyFirstPostDate:desc"
    return params


# ---------------------------------------------------------------- study records


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def sites(study: dict, near: Near | None = None, country: str | None = None) -> list[dict]:
    """The trial's sites as {facility, city, country, status, distance_km}: open ones first, nearest (or in the
    country) first."""
    out = []
    for loc in study.get("protocolSection", {}).get("contactsLocationsModule", {}).get("locations", []):
        site = {
            "facility": loc.get("facility", ""),
            "city": ", ".join(p for p in (loc.get("city"), loc.get("state")) if p),
            "country": loc.get("country", ""),
            "status": STATUS_TEXT.get(loc.get("status", ""), loc.get("status", "").replace("_", " ").capitalize()),
        }
        geo = loc.get("geoPoint")
        if near and geo:
            site["distance_km"] = round(distance_km(near.latitude, near.longitude, geo["lat"], geo["lon"]))
        out.append(site)
    # Open sites first (a trial can match a search through a withdrawn site), then by distance or country
    if near:
        out.sort(key=lambda s: (s["status"] in CLOSED, s.get("distance_km", math.inf)))
    elif country:
        out.sort(key=lambda s: (s["status"] in CLOSED, s["country"].lower() != country.lower()))
    return out


def _date(struct: dict | None) -> str:
    return (struct or {}).get("date", "")


def summary(study: dict, near: Near | None = None, country: str | None = None) -> dict:
    """The facts a trial card shows, all from the registry record."""
    p = study.get("protocolSection", {})
    ident, status, design = p.get("identificationModule", {}), p.get("statusModule", {}), p.get("designModule", {})
    sponsor = p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
    elig = p.get("eligibilityModule", {})
    nct = ident.get("nctId", "")
    all_sites = sites(study, near, country)
    return {
        "nct_id": nct,
        "title": ident.get("briefTitle", ""),
        "status": STATUS_TEXT.get(status.get("overallStatus", ""), status.get("overallStatus", "")),
        "phases": [PHASE_TEXT.get(ph, ph) for ph in design.get("phases", [])],
        "study_type": design.get("studyType", "").replace("_", " ").capitalize(),
        "conditions": p.get("conditionsModule", {}).get("conditions", [])[:5],
        "interventions": [
            f"{i.get('name', '')} ({i.get('type', '').replace('_', ' ').lower()})"
            for i in p.get("armsInterventionsModule", {}).get("interventions", [])[:5]
        ],
        "enrollment": design.get("enrollmentInfo", {}).get("count"),
        "sponsor": sponsor.get("name", ""),
        "sponsor_type": sponsor.get("class", "").replace("_", " ").capitalize(),
        "ages": f"{elig.get('minimumAge', 'any age')} to {elig.get('maximumAge', 'no upper limit')}",
        "sex": elig.get("sex", "ALL").capitalize(),
        "start": _date(status.get("startDateStruct")),
        "primary_completion": _date(status.get("primaryCompletionDateStruct")),
        "last_update": _date(status.get("lastUpdatePostDateStruct")),
        "why_stopped": status.get("whyStopped", ""),
        "has_results": bool(study.get("hasResults")),
        "site_count": len(all_sites),
        "nearest_site": all_sites[0] if all_sites and (near or country) else None,
        "url": STUDY_URL + nct,
    }


def details(study: dict) -> dict:
    """What get_trial adds to the summary: the design, arms, eligibility criteria and outcomes."""
    p = study.get("protocolSection", {})
    design, arms = p.get("designModule", {}), p.get("armsInterventionsModule", {})
    info = design.get("designInfo", {})
    outcomes = p.get("outcomesModule", {})
    criteria = p.get("eligibilityModule", {}).get("eligibilityCriteria", "")
    return {
        "brief_summary": p.get("descriptionModule", {}).get("briefSummary", "")[:1500],
        "design": {
            "allocation": info.get("allocation", ""),
            "model": info.get("interventionModel", ""),
            "masking": info.get("maskingInfo", {}).get("masking", ""),
            "purpose": info.get("primaryPurpose", ""),
        },
        "arms": [
            {
                "label": a.get("label", ""),
                "type": a.get("type", "").replace("_", " ").lower(),
                "description": a.get("description", "")[:300],
                "interventions": a.get("interventionNames", []),
            }
            for a in arms.get("armGroups", [])[:8]
        ],
        "healthy_volunteers": p.get("eligibilityModule", {}).get("healthyVolunteers", False),
        "eligibility_criteria": criteria[:5000] + (" […cut; read the rest at the registry]" if len(criteria) > 5000 else ""),
        "primary_outcomes": [
            {"measure": o.get("measure", ""), "time_frame": o.get("timeFrame", "")}
            for o in outcomes.get("primaryOutcomes", [])[:5]
        ],
        "secondary_outcomes": [o.get("measure", "") for o in outcomes.get("secondaryOutcomes", [])[:8]],
        "results_url": STUDY_URL + p.get("identificationModule", {}).get("nctId", "") + "?tab=results"
        if study.get("hasResults")
        else None,
    }


# ---------------------------------------------------------------- report


def _cell(text: Any) -> str:
    return str(text or "–").replace("|", "/").replace("\n", " ")


def format_report(summary_text: str, cards: list[dict], notes: list[str]) -> str:
    lines = [summary_text.strip(), ""]
    if cards:
        lines += ["| Trial | Status | Phase | Nearest site | Why it matched |", "|---|---|---|---|---|"]
        for c in cards:
            site = c.get("nearest_site")
            where = f"{site['city']}, {site['country']}" + (f" ({site['distance_km']} km)" if "distance_km" in site else "") if site else f"{c['site_count']} sites"
            lines.append(
                f"| [{c['nct_id']}]({c['url']}): {_cell(c['title'])} | {_cell(c['status'])} | "
                f"{_cell(', '.join(c['phases']))} | {_cell(where)} | {_cell(c['why_matched'])} |"
            )
        lines.append("")
    lines += [f"- {n}" for n in notes]
    lines.append(
        "\nFrom the ClinicalTrials.gov registry, as last updated by each sponsor. Only the trial team can confirm "
        "eligibility; this is not medical advice."
    )
    return "\n".join(lines).strip()


# ---------------------------------------------------------------- server


def create_server() -> MCPServer:
    mcp = MCPServer(
        "clinical-trials",
        instructions="Searches ClinicalTrials.gov. Read trials with search_trials or get_trial, then file the ones to "
        "show with submit_trials.",
    )
    seen: dict[str, dict] = {}  # nct id -> summary, for every trial read in this session
    last_near: list[Near] = []  # the latest search's place, so cards can show the nearest site
    refusals: list[list[str]] = []

    @mcp.tool(annotations=READ_ONLY)
    async def search_trials(
        condition: str,
        intervention: str | None = None,
        keywords: str | None = None,
        near: Near | None = None,
        country: str | None = None,
        statuses: list[Status] | None = None,
        phases: list[Phase] | None = None,
        age_years: Annotated[int | None, Field(ge=0, le=120)] = None,
        sex: Literal["female", "male"] | None = None,
        sort: Literal["relevance", "recently_updated", "newest"] = "relevance",
        max_results: Annotated[int, Field(ge=1, le=20)] = 10,
    ) -> dict:
        """Search ClinicalTrials.gov for trials. Returns the total number of matches and the first max_results.

        Args:
            condition: The disease or condition, e.g. "metastatic melanoma", "HER2-low breast cancer".
            intervention: A drug, device or procedure, e.g. "pembrolizumab".
            keywords: Other terms anywhere in the record, e.g. a biomarker ("BRAF V600E") or "second line".
            near: Coordinates of a place and a radius: only trials with a site within it.
            country: Only trials with a site in this country (when no city is given), e.g. "India".
            statuses: Overall statuses to include; default RECRUITING and NOT_YET_RECRUITING.
            phases: Only these phases.
            age_years: Only trials open to someone of this age.
            sex: Only trials open to this sex (trials open to all are included).
            sort: relevance (default), recently_updated or newest.
            max_results: How many trials to return (1 to 20).
        """
        chosen = statuses if statuses is not None else ["RECRUITING", "NOT_YET_RECRUITING"]
        params = search_params(
            condition, intervention, keywords, near, country, chosen, phases, age_years, sex, sort, max_results
        )
        data = await registry_get("", params)
        last_near[:] = [near] if near else []
        trials = []
        for study in data.get("studies", []):
            card = summary(study, near, country)
            seen[card["nct_id"]] = card
            trials.append(card)
        result: dict[str, Any] = {"total": data.get("totalCount", len(trials)), "returned": len(trials), "trials": trials}
        if not trials:
            result["hint"] = (
                "No trials matched. Try a broader condition term, fewer filters, more statuses, a larger radius, "
                "or a country instead of a city."
            )
        return result

    @mcp.tool(annotations=READ_ONLY)
    async def get_trial(nct_id: NctId) -> dict:
        """One trial in full: summary, design, arms, eligibility criteria, outcomes and whether results are posted.

        Args:
            nct_id: The trial's registry id, e.g. "NCT04657991".
        """
        study = await registry_get(f"/{nct_id}")
        near = last_near[0] if last_near else None
        card = summary(study, near)
        seen[nct_id] = card
        return {**card, **details(study)}

    @mcp.tool(annotations=READ_ONLY)
    async def trial_locations(
        nct_id: NctId,
        near: Near | None = None,
        country: str | None = None,
        recruiting_only: bool = True,
        limit: Annotated[int, Field(ge=1, le=50)] = 15,
    ) -> dict:
        """A trial's sites, nearest to a place first (or those in a country first), with each site's status.

        Args:
            nct_id: The trial's registry id.
            near: Coordinates of the user's place, to sort sites by distance.
            country: Sites in this country first.
            recruiting_only: Only sites that are recruiting (or not yet recruiting).
            limit: How many sites to return.
        """
        study = await registry_get(f"/{nct_id}")
        seen[nct_id] = summary(study, near or (last_near[0] if last_near else None), country)
        found = sites(study, near, country)
        if recruiting_only:
            found = [s for s in found if s["status"] in ("Recruiting", "Not yet recruiting")]
        return {"nct_id": nct_id, "total_sites": len(sites(study)), "sites": found[:limit], "url": STUDY_URL + nct_id}

    @mcp.tool()
    async def submit_trials(
        summary_text: str,
        trials: Annotated[list[TrialPick], Field(max_length=12)],
        notes: list[str] | None = None,
    ) -> dict:
        """File the trials to show the user, best match first, and get the formatted report. Call it once.

        Only trials you read in this session with search_trials, get_trial or trial_locations are accepted; the
        status, phase, sites and dates are taken from the registry, not from you. An empty list is fine when
        nothing matched: say so in summary_text and suggest how to broaden the search in notes.

        Args:
            summary_text: What was searched and found, in plain language.
            trials: The trials to show, each with why it matched and what the trial team must confirm.
            notes: Search tips or caveats, e.g. "No trials within 100 km; 3 more within 500 km".
        """
        unknown = [t.nct_id for t in trials if t.nct_id not in seen]
        if unknown and not refusals:
            refusals.append(unknown)
            raise ToolError(
                f"Not read in this session: {', '.join(unknown)}. Look them up with get_trial (or drop them) and "
                "submit again; trials still unread will be left out."
            )
        cards = [{**seen[t.nct_id], "why_matched": t.why_matched, "to_confirm": t.to_confirm[:5]}
                 for t in trials if t.nct_id in seen]
        all_notes = list(notes or [])
        if unknown:
            all_notes.append(f"Left out {', '.join(unknown)}: not found in the registry in this session.")
        return {"result": format_report(summary_text, cards, all_notes), "trials": cards}

    return mcp


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        create_server().streamable_http_app(host="127.0.0.1"), host="127.0.0.1", port=int(os.getenv("MCP_PORT", "8104"))
    )
