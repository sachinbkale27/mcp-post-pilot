"""MCP server for plain-language drug information from public FDA and NLM sources (no key needed).

It runs inside the agent service (agents.json: "mcp_url": "local:drugs"); `python -m app.local_mcp.drugs`
also serves it over Streamable HTTP for the MCP Inspector.

  find_drug              resolves a brand or generic name (spelling mistakes too) with RxNorm, and lists the
                         FDA labels for it (openFDA drug labels, the text printed with the medicine)
  read_label             sections of one label: what it's for, dosing, warnings, side effects, interactions...,
                         or only the passages that mention some terms (another medicine, "alcohol")
  side_effect_reports    what people reported to the FDA (FAERS): the total and the most reported problems
  recalls                FDA recall (enforcement) reports
  submit_drug_info       files the answer. Each fact must quote a label this session read, and report counts
                         and recalls come from the data, so an answer can't carry invented label text

Each connection gets its own server (create_server), which remembers the labels and reports it read.
An OPENFDA_API_KEY raises openFDA's limit from 1,000 requests a day per address.
"""

import asyncio
import os
import re
from typing import Annotated, Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from .research import quote_found

OPENFDA = "https://api.fda.gov/drug"
RXNAV = "https://rxnav.nlm.nih.gov/REST"
DAILYMED = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="
USER_AGENT = "PostPilotDrugs/1.0 (+https://agent.sachin-kale.com)"
SET_ID = r"^[0-9a-fA-F-]{36}$"
SetId = Annotated[str, Field(pattern=SET_ID)]
DrugName = Annotated[str, Field(min_length=2, max_length=100)]

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

# Friendly section names -> openFDA label fields (prescription labels, then over-the-counter "Drug Facts")
SECTIONS: dict[str, tuple[str, ...]] = {
    "uses": ("indications_and_usage", "purpose"),
    "dosing": ("dosage_and_administration",),
    "boxed_warning": ("boxed_warning",),
    "do_not_use": ("contraindications", "do_not_use"),
    "warnings": ("warnings_and_cautions", "warnings", "precautions", "ask_doctor", "ask_doctor_or_pharmacist", "stop_use", "when_using"),
    "side_effects": ("adverse_reactions",),
    "interactions": ("drug_interactions",),
    "pregnancy": ("pregnancy", "lactation", "pregnancy_or_breast_feeding", "use_in_specific_populations"),
    "children_and_older_adults": ("pediatric_use", "geriatric_use"),
    "how_it_works": ("mechanism_of_action",),
    "overdose": ("overdosage",),
    "patient_info": ("information_for_patients", "spl_patient_package_insert", "spl_medguide"),
}
Section = Literal[
    "uses", "dosing", "boxed_warning", "do_not_use", "warnings", "side_effects", "interactions", "pregnancy",
    "children_and_older_adults", "how_it_works", "overdose", "patient_info",
]
SECTION_TEXT = {
    "uses": "Uses", "dosing": "Dosing", "boxed_warning": "Boxed warning", "do_not_use": "Who should not take it",
    "warnings": "Warnings", "side_effects": "Side effects", "interactions": "Interactions", "pregnancy": "Pregnancy and breastfeeding",
    "children_and_older_adults": "Children and older adults", "how_it_works": "How it works", "overdose": "Overdose",
    "patient_info": "Patient information",
}
SECTION_CHARS = 4000
# Repackagers relabel other makers' products; their labels copy the maker's, often dated later
REPACKAGER = re.compile(
    r"a-s medication|bryant ranch|proficient rx|nucare|preferred pharmaceuticals|quality care|remedyrepack|direct[ _]rx|"
    r"pd-rx|henry schein|lake erie medical|aphena|st\.? mary|northwind|medsource|asclemed|denton pharma|unit dose services",
    re.I,
)
# FAERS terms about how a product was used or handled rather than a health problem
NOT_A_PROBLEM = re.compile(
    r"off label|unapproved indication|product |no adverse event|dose omission|wrong |incorrect |medication error|"
    r"schedule of|intentional product|expired|drug ineffective for unapproved",
    re.I,
)


class Fact(BaseModel):
    point: str = Field(max_length=400, description="One fact in plain language, e.g. 'It can cause low blood sugar when used with insulin.'")
    set_id: str = Field(pattern=SET_ID, description="The label it comes from (read with read_label in this session)")
    section: Section
    quote: str = Field(max_length=400, description="Words copied exactly from that label section that back the fact")


class SourceError(ToolError):
    """ToolError messages are shown to the model."""


# ---------------------------------------------------------------- sources


async def get_json(url: str, params: dict[str, Any], source: str) -> dict:
    """A JSON answer from openFDA or RxNav; openFDA's 404 means "no matches" and comes back as {}."""
    if url.startswith(OPENFDA) and (key := os.getenv("OPENFDA_API_KEY")):
        params = {**params, "api_key": key}
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
        try:
            resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise SourceError(f"{source} could not be reached ({type(exc).__name__})") from exc
    if resp.status_code == 404:
        return {}
    if resp.status_code == 429:
        raise SourceError(f"{source} is rate-limiting requests; wait a moment and make fewer calls")
    if resp.status_code >= 400:
        raise SourceError(f"{source} answered HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def _quoted(term: str) -> str:
    """A term for an openFDA search phrase: no quotes or query syntax inside."""
    return re.sub(r'["\\:()\[\]{}]', " ", term).strip()


async def normalize(name: str) -> dict:
    """RxNorm's best match for a name: its ingredients and brand names, e.g. ozempik -> semaglutide (Ozempic,
    Rybelsus, Wegovy). Empty lists when RxNorm doesn't know it."""
    data = await get_json(f"{RXNAV}/approximateTerm.json", {"term": name, "maxEntries": 3}, "RxNorm")
    candidates = [c for c in data.get("approximateGroup", {}).get("candidate", []) if c.get("rxcui")]
    if not candidates:
        return {"matched": "", "ingredients": [], "brands": []}
    best = next((c for c in candidates if c.get("name")), candidates[0])
    related = await get_json(f"{RXNAV}/rxcui/{best['rxcui']}/allrelated.json", {}, "RxNorm")
    names: dict[str, list[str]] = {}
    for group in related.get("allRelatedGroup", {}).get("conceptGroup", []):
        if group.get("tty") in ("IN", "MIN", "BN"):
            names.setdefault(group["tty"], []).extend(c["name"] for c in group.get("conceptProperties", []))
    return {
        "matched": best.get("name", ""),
        "ingredients": sorted(set(names.get("IN", []) or names.get("MIN", [])))[:5],
        "brands": sorted(set(names.get("BN", [])))[:10],
    }


def label_query(terms: list[str]) -> str:
    return " OR ".join(
        f'openfda.{field}:"{_quoted(t)}"' for t in dict.fromkeys(terms) if _quoted(t) for field in ("brand_name", "generic_name")
    )


def _first(values: Any) -> str:
    return values[0] if isinstance(values, list) and values else values if isinstance(values, str) else ""


def _date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}" if re.fullmatch(r"\d{8}", yyyymmdd or "") else yyyymmdd or ""


def label_card(label: dict) -> dict:
    """Who makes the product this label is for, and when the label was last updated."""
    fda = label.get("openfda", {})
    set_id = label.get("set_id", "")
    return {
        "set_id": set_id,
        "brand": _first(fda.get("brand_name")).title(),
        "generic": _first(fda.get("generic_name")).lower(),
        "manufacturer": _first(fda.get("manufacturer_name")),
        "route": ", ".join(fda.get("route", [])).lower(),
        "type": _first(fda.get("product_type")).replace("HUMAN ", "").lower(),  # "prescription drug" or "otc drug"
        "updated": _date(label.get("effective_time", "")),
        "sections": [name for name, fields in SECTIONS.items() if any(label.get(f) for f in fields)],
        "repackaged": bool(REPACKAGER.search(_first(fda.get("manufacturer_name")))),
        "url": DAILYMED + set_id,
    }


def section_text(label: dict, section: str) -> str:
    parts = []
    for field in SECTIONS[section]:
        for text in label.get(field, []):
            parts.append(re.sub(r"\s+", " ", text).strip())
    return "\n".join(p for p in parts if p)


def label_text(label: dict) -> dict[str, str]:
    """Every section's full text, which facts must quote."""
    return {name: text for name in SECTIONS if (text := section_text(label, name))}


def passages(text: str, terms: list[str], limit: int = 2500) -> str:
    """The sentences that mention any of the terms, each with the sentence after it (a heading such as
    "Use with Insulin." is followed by what happens)."""
    wanted = [t.lower() for t in terms if t.strip()]
    sentences = re.split(r"(?<=[.;])\s+", text)
    keep = sorted({j for i, s in enumerate(sentences) if any(t in s.lower() for t in wanted) for j in (i, i + 1) if j < len(sentences)})
    runs, prev = [], -2
    for i in keep:
        runs.append(sentences[i] if i == prev + 1 and runs else "\u2026 " + sentences[i])
        prev = i
    return " ".join(runs).removeprefix("\u2026 ")[:limit]


# ---------------------------------------------------------------- report


def _cell(text: Any) -> str:
    return str(text if text not in (None, "") else "–").replace("|", "/").replace("\n", " ")


def format_report(drug: str, summary_text: str, facts: list[dict], labels: dict[str, dict], reports: dict | None,
                  recalls: dict | None, notes: list[str]) -> str:
    lines = [summary_text.strip(), ""]
    for set_id in dict.fromkeys(f["set_id"] for f in facts):
        card = labels[set_id]
        product = card["brand"] or card["generic"] or drug
        by = (
            f" (published by the repackager {card['manufacturer']})" if card["repackaged"]
            else f" ({card['manufacturer']})" if card["manufacturer"] else ""
        )
        lines.append(f"From the FDA label for **{product}**{by}, updated {card['updated']} ([DailyMed]({card['url']})):")
        for section in dict.fromkeys(f["section"] for f in facts if f["set_id"] == set_id):
            lines.append(f"\n**{SECTION_TEXT[section]}**")
            for f in facts:
                if f["set_id"] == set_id and f["section"] == section:
                    lines.append(f"- {f['point'].strip()} _Label: \u201c{f['quote'].strip()}\u201d_")
        lines.append("")
    if reports:
        lines += [
            f"**Reports to the FDA**: {reports['total']:,} adverse event reports mention {reports['drug']}. Most often reported:",
            "",
            "| Problem | Reports |",
            "|---|---|",
            *(f"| {_cell(r['problem'])} | {r['reports']:,} |" for r in reports["top"]),
            "",
            "Reports show what people noticed while taking the medicine, not that it caused the problem or how often it happens.",
            "",
        ]
    if recalls is not None:
        if recalls["items"]:
            lines += ["**FDA recalls**", "", "| Date | Class | Product | Reason | Status |", "|---|---|---|---|---|"]
            lines += [
                f"| {_cell(r['date'])} | {_cell(r['class'])} | {_cell(r['product'][:120])} | {_cell(r['reason'][:160])} | {_cell(r['status'])} |"
                for r in recalls["items"]
            ]
            lines += ["", f"{recalls['total']} recall reports in all; a recall usually concerns certain batches, not every pack.", ""]
        else:
            lines += [f"**FDA recalls**: none found for {recalls['drug']}.", ""]
    lines += [f"- {n}" for n in notes]
    lines.append(
        "\nFrom FDA drug labels (openFDA, DailyMed) and FDA reports. This is general information, not medical advice: "
        "ask your doctor or pharmacist before starting, stopping or changing a medicine."
    )
    return "\n".join(lines).strip()


# ---------------------------------------------------------------- server


def create_server() -> MCPServer:
    mcp = MCPServer(
        "drug-information",
        instructions="FDA drug labels and reports. Find the drug with find_drug, read its label with read_label, "
        "then file the answer with submit_drug_info.",
    )
    labels: dict[str, dict] = {}  # set id -> label card, for every label read in this session
    texts: dict[str, dict[str, str]] = {}  # set id -> section -> full text, which facts must quote
    data: dict[str, Any] = {}  # the latest side_effect_reports and recalls results
    refusals: list[dict] = []

    async def fetch_label(set_id: str) -> dict:
        found = await get_json(f"{OPENFDA}/label.json", {"search": f'set_id:"{set_id}"', "limit": 1}, "openFDA")
        if not found.get("results"):
            raise SourceError(f"No FDA label {set_id}; use a set_id from find_drug")
        label = found["results"][0]
        card = label_card(label)
        labels[set_id], texts[set_id] = card, label_text(label)
        return label

    async def ingredient(name: str) -> str:
        names = await normalize(name)
        return names["ingredients"][0] if names["ingredients"] else name

    @mcp.tool(annotations=READ_ONLY)
    async def find_drug(name: DrugName, otc: bool | None = None) -> dict:
        """Look up a medicine by brand or generic name (spelling mistakes are fine) and list its FDA labels, newest
        first: prescription labels first unless otc is true.

        Args:
            name: A brand or generic name, e.g. "Ozempic", "metformin", "ibuprofen".
            otc: True for over-the-counter labels only, False for prescription only, None for both.
        """
        names = await normalize(name)
        terms = [name, *names["ingredients"], *([names["matched"]] if names["matched"] else [])]
        query = f"({label_query(terms)})"
        if otc is not None:
            query += f' AND openfda.product_type:"{"HUMAN OTC DRUG" if otc else "HUMAN PRESCRIPTION DRUG"}"'
        found = await get_json(f"{OPENFDA}/label.json", {"search": query, "sort": "effective_time:desc", "limit": 25}, "openFDA")
        cards, seen = [], set()
        # The maker's own label before a repackager's copy (sorted is stable: newest first otherwise)
        for card in sorted(map(label_card, found.get("results", [])), key=lambda c: c["repackaged"]):
            key = (card["brand"].lower(), card["route"], card["type"])  # one label per product: generics repeat
            if card["set_id"] and key not in seen:
                seen.add(key)
                cards.append(card)
        cards.sort(key=lambda c: c["type"] != "prescription drug")  # stable: newest first within each type
        result: dict[str, Any] = {
            "rxnorm": names,
            "total_labels": found.get("meta", {}).get("results", {}).get("total", 0),
            "labels": cards[:8],
        }
        if not cards:
            result["hint"] = "No FDA label matched. Check the spelling, try the generic name, or the drug may not be sold in the US."
        return result

    @mcp.tool(annotations=READ_ONLY)
    async def read_label(set_id: SetId, sections: list[Section] | None = None, about: list[str] | None = None) -> dict:
        """Read sections of one FDA label (from find_drug), or only the passages that mention some terms.

        Args:
            set_id: The label's set_id from find_drug.
            sections: Which sections to read; default uses, boxed_warning, do_not_use, warnings and side_effects.
                Over-the-counter labels have uses, dosing, do_not_use, warnings and pregnancy.
            about: Only return sentences mentioning these terms, e.g. ["warfarin", "anticoagulant"] or ["alcohol"],
                searched in the chosen sections (or in all sections when none are chosen).
        """
        await fetch_label(set_id)
        chosen = sections or (list(SECTIONS) if about else ["uses", "boxed_warning", "do_not_use", "warnings", "side_effects"])
        out: dict[str, str] = {}
        for name in chosen:
            text = texts[set_id].get(name, "")
            if about:
                text = passages(text, about)
            elif len(text) > SECTION_CHARS:
                text = text[:SECTION_CHARS] + " […cut; read the rest on DailyMed]"
            if text:
                out[name] = text
        result: dict[str, Any] = {**labels[set_id], "text": out}
        if about and not out:
            result["note"] = f"The label doesn't mention {', '.join(about)} in these sections."
        elif not out:
            result["note"] = "This label has none of these sections."
        return result

    @mcp.tool(annotations=READ_ONLY)
    async def side_effect_reports(name: DrugName, top: Annotated[int, Field(ge=3, le=20)] = 10) -> dict:
        """How many reports to the FDA (FAERS) mention a medicine, and the problems reported most often. Reports are
        not proof that the medicine caused a problem, and don't show how common it is.

        Args:
            name: The medicine's generic name (a brand name is resolved to it).
            top: How many of the most reported problems to return.
        """
        generic = await ingredient(name)
        search = f'patient.drug.openfda.generic_name:"{_quoted(generic)}"'
        total, counts = await asyncio.gather(
            get_json(f"{OPENFDA}/event.json", {"search": search, "limit": 1}, "openFDA"),
            get_json(f"{OPENFDA}/event.json", {"search": search, "count": "patient.reaction.reactionmeddrapt.exact", "limit": top + 15}, "openFDA"),
        )
        problems = [r for r in counts.get("results", []) if not NOT_A_PROBLEM.search(r["term"])][:top]
        result = {
            "drug": generic,
            "total": total.get("meta", {}).get("results", {}).get("total", 0),
            "top": [{"problem": r["term"].capitalize(), "reports": r["count"]} for r in problems],
        }
        data["reports"] = result
        return result

    @mcp.tool(annotations=READ_ONLY)
    async def recalls(name: DrugName, max_results: Annotated[int, Field(ge=1, le=10)] = 5) -> dict:
        """FDA recall reports for a medicine, newest first: date, class (I is the most serious), product, reason
        and status.

        Args:
            name: A brand or generic name.
            max_results: How many recalls to return.
        """
        generic = await ingredient(name)
        terms = list(dict.fromkeys([generic, name]))
        query = " OR ".join(f'openfda.generic_name:"{_quoted(t)}" OR openfda.brand_name:"{_quoted(t)}"' for t in terms)
        found = await get_json(
            f"{OPENFDA}/enforcement.json", {"search": query, "sort": "report_date:desc", "limit": max_results}, "openFDA"
        )
        result = {
            "drug": generic,
            "total": found.get("meta", {}).get("results", {}).get("total", 0),
            "items": [
                {
                    "date": _date(r.get("recall_initiation_date", "")),
                    "class": r.get("classification", ""),
                    "product": r.get("product_description", ""),
                    "reason": r.get("reason_for_recall", ""),
                    "status": r.get("status", ""),
                    "firm": r.get("recalling_firm", ""),
                }
                for r in found.get("results", [])
            ],
        }
        data["recalls"] = result
        return result

    @mcp.tool()
    async def submit_drug_info(
        drug: str,
        summary_text: str,
        facts: Annotated[list[Fact], Field(max_length=20)],
        include_reports: bool = False,
        include_recalls: bool = False,
        notes: list[str] | None = None,
    ) -> dict:
        """File the answer and get the formatted report. Call it once.

        Each fact must come from a label you read in this session with read_label, and its quote must be copied
        exactly from that section. Report counts and recalls are added from side_effect_reports and recalls, not
        from you.

        Args:
            drug: The medicine, as the user named it.
            summary_text: A short plain-language answer to the question (two or three sentences).
            facts: The facts that answer it, grouped by section, most important first.
            include_reports: Add the FAERS reports table (call side_effect_reports first).
            include_recalls: Add the recalls (call recalls first).
            notes: Caveats, e.g. "Labels differ between brands; this is the one for tablets."
        """
        problems: dict[int, str] = {}
        for i, f in enumerate(facts):
            if f.set_id not in labels:
                problems[i] = "its label was not read in this session; read it with read_label"
            elif not quote_found(f.quote, texts[f.set_id].get(f.section, "")):
                problems[i] = f"its quote is not an exact quote (of 15+ characters) from the label's {f.section} section"
        if problems and not refusals:
            refusals.append(problems)
            raise ToolError(
                "Not accepted: " + "; ".join(f"fact {i + 1} ({facts[i].point[:50]}): {why}" for i, why in problems.items())
                + ". Fix these (read the section, copy the words exactly) or drop them, and submit again; facts still "
                "not fixed will be left out."
            )
        kept = [f.model_dump() for i, f in enumerate(facts) if i not in problems]
        all_notes = list(notes or [])
        if problems:
            all_notes.append(f"{len(problems)} point(s) were left out because the label text could not confirm them.")
        report = format_report(
            drug, summary_text, kept, labels,
            data.get("reports") if include_reports else None,
            data.get("recalls") if include_recalls else None,
            all_notes,
        )
        return {"result": report, "facts": kept, "labels": [labels[s] for s in dict.fromkeys(f["set_id"] for f in kept)]}

    return mcp


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        create_server().streamable_http_app(host="127.0.0.1"), host="127.0.0.1", port=int(os.getenv("MCP_PORT", "8105"))
    )
