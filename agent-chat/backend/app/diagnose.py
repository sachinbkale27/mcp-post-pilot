"""An AI interpretation of an image, for the "Diagnose" button in the Annotate Images view.

One vision-model call, streamed as token events. The answer is structured like a pathologist's or
radiologist's read (findings, most likely interpretation, differential, what would confirm it), and is
always framed as research and education, not a diagnosis.
"""

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

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
    async for chunk in model.astream([SystemMessage(PROMPT), message]):
        if chunk.text:
            yield {"type": "token", "text": chunk.text}
