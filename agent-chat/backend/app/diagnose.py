"""An AI interpretation of an image, for the "Diagnose" button in the Annotate Images view.

One vision-model call, streamed as token events. The answer is structured like a pathologist's or
radiologist's read (findings, most likely interpretation, differential, what would confirm it), and is
always framed as research and education, not a diagnosis.

A second, small call then turns the interpretation into the areas to outline (a diagnosis_regions
event); the UI hands those to the Labeling agent, so the findings are shown on the image.
"""

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from .agent import _model

PROMPT = """You interpret images for research and education, in the way a pathologist or radiologist would
describe them to a colleague. You are not diagnosing a patient: you never see the clinical history, and a
single image is never enough for a diagnosis.

First decide what the image is (e.g. H&E histology, cytology, CT, MRI, X-ray, ultrasound, dermoscopy,
endoscopy, fundus photo, or not a medical image). If it isn't a medical image, describe it briefly and stop.

Then answer in Markdown with these sections:
## What the image shows
Modality, likely stain or sequence, apparent magnification or view, and image quality limits.
## Findings
Specific observations in standard terminology: architecture, cells and nuclei, pigment, inflammation,
necrosis, structures and their location. Describe; don't jump to conclusions.
## Most likely interpretation
The leading interpretation and the features supporting it, with your confidence (low, moderate, high).
## Differential
Other possibilities, most likely first, each with what speaks for or against it.
## What would confirm it
Special stains, immunohistochemistry, further imaging, clinical information or other tests.
## Limits
What this image can't tell you (resolution, single field, missing history, unknown site).

Be specific and honest about uncertainty. Don't give treatment advice. End with one line:
"AI interpretation for research and education; not a medical diagnosis."
"""


async def run_diagnosis(image: dict[str, str], context: str = "") -> AsyncIterator[dict[str, Any]]:
    """Yield token events with the interpretation of one image."""
    text = "Interpret this image."
    if context.strip():
        text += f"\n\nContext from the user (may describe the specimen or what to look for):\n{context.strip()}"
    message = HumanMessage(
        [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": image["data_url"], "detail": "high"}},
        ]
    )
    model = _model(streaming=True)
    answer: list[str] = []
    async for chunk in model.astream([SystemMessage(PROMPT), message]):
        if chunk.text:
            answer.append(chunk.text)
            yield {"type": "token", "text": chunk.text}
    try:
        found = await extract_regions("".join(answer), image["data_url"])
    except Exception:  # the interpretation is already shown; just nothing to outline
        return
    yield {
        "type": "diagnosis_regions",
        "medical": found.medical,
        "regions": [r.model_dump() for r in found.regions[:6]],
        "diagnosis": found.leading_diagnosis.strip() if found.medical else "",
        "lesion_area": found.lesion_area.strip(),
    }


REGIONS_PROMPT = """From this image interpretation, list the problematic regions to outline on the image: the
abnormal or concerning findings a pathologist or radiologist would point at, most important first, at most
6 kinds. Name each with precise medical terminology for the finding (e.g. "atypical melanocytes",
"melanophages (pigment-laden macrophages)", "sheet of atypical epithelioid cells", "tumour necrosis",
"atypical mitotic figure", "haemorrhage", "spiculated mass", "pleural effusion"). Each must be a concrete thing
you can draw a line around in this image: a kind of cell, deposit, structure or area. Never a property or
pattern of the whole tissue (not "pleomorphism", "minimal matrix", "growth pattern", "crowded cells"):
outline the cells or area that show it instead. Don't list normal tissue, background or stroma, and leave
out absences (e.g. "no necrosis"). Check each against the image: only list what is clearly visible. Keep diagnoses out of these
labels (a finding's significance can say what it suggests). Separately, give the interpretation's leading
diagnosis in standard pathological or radiological terms (e.g. "melanoma", "invasive ductal carcinoma",
"pneumonia"), or leave it empty when there is none, and describe the main abnormal (lesional) area to
outline for it. For an image that isn't medical, list the main objects instead."""


class Region(BaseModel):
    label: str = Field(description="Medical term for the finding, used as the annotation label")
    description: str = Field(description="How to recognise it in the image: appearance, colour, location")
    significance: str = Field(description="Why it is concerning, or what it suggests (one short sentence)")


class Regions(BaseModel):
    medical: bool = Field(description="Whether this is a medical image (histology, cytology, radiology, ...)")
    regions: list[Region] = Field(description="At most 6 kinds, most important first")
    leading_diagnosis: str = Field(description="The interpretation's leading diagnosis, or empty if none")
    lesion_area: str = Field(description="The main abnormal area that diagnosis refers to, as it appears in the image")


async def extract_regions(interpretation: str, image_data_url: str) -> Regions:
    """The problematic regions, chosen from the interpretation and checked against the image itself."""
    model = _model().with_structured_output(Regions)
    message = HumanMessage(
        [
            {"type": "text", "text": f"Interpretation of the attached image:\n\n{interpretation}"},
            {"type": "image_url", "image_url": {"url": image_data_url, "detail": "high"}},
        ]
    )
    return await model.ainvoke([SystemMessage(REGIONS_PROMPT), message])
