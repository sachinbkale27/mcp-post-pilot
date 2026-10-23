"""Hand an image analysis to the genetics assistant ("Ask AI" in Annotate Images).

The browser sends the summary here; this server stores it with genapi.sachin-kale.com using the handoff key,
which only the two servers know (the genetics stack generates it in Secrets Manager; nobody types it), and
returns the address that opens a chat about it: genetics.sachin-kale.com/?results=<id>.
"""

import asyncio
import os
from typing import Literal

import httpx
from pydantic import BaseModel, Field

GENETICS_API_URL = os.getenv("GENETICS_API_URL", "https://genapi.sachin-kale.com")
GENETICS_URL = os.getenv("GENETICS_URL", "https://genetics.sachin-kale.com")
SECRET_REGION = os.getenv("GENETICS_HANDOFF_REGION", "us-east-1")


class Finding(BaseModel):
    label: str = Field(max_length=120)
    count: int = Field(1, ge=0, le=10000)
    significance: str = Field("", max_length=400)


class Nuclei(BaseModel):
    count: int = Field(ge=0)
    per_megapixel: float = Field(ge=0)
    median_area: float = Field(ge=0)
    area_variation: float = Field(ge=0)
    enlarged: int = Field(ge=0)


class Quality(BaseModel):
    verdict: Literal["good", "check", "poor"]
    warnings: list[str] = Field(default_factory=list, max_length=8)


class ResultsHandoff(BaseModel):
    """What genapi's POST /api/v1/results accepts."""

    image_url: str | None = Field(None, max_length=500, pattern=r"^https://[\w.-]+(/[\w./%-]*)?$")
    image_name: str = Field("", max_length=200)
    suspected_diagnosis: str = Field("", max_length=200)
    findings: list[Finding] = Field(default_factory=list, max_length=20)
    nuclei: Nuclei | None = None
    quality: Quality | None = None
    interpretation: str = Field("", max_length=8000)
    report: str = Field("", max_length=4000)


class HandoffError(Exception):
    pass


_key: str | None = None


async def handoff_key() -> str:
    """GENETICS_HANDOFF_KEY locally; in AWS, the genetics stack's secret (read once per container)."""
    global _key
    if _key is None:
        if os.getenv("GENETICS_HANDOFF_KEY"):
            _key = os.environ["GENETICS_HANDOFF_KEY"]
        elif secret := os.getenv("GENETICS_HANDOFF_SECRET"):
            import boto3

            client = boto3.client("secretsmanager", region_name=SECRET_REGION)
            _key = (await asyncio.to_thread(client.get_secret_value, SecretId=secret))["SecretString"]
        else:
            raise HandoffError("Ask AI isn't configured on this server.")
    return _key


async def hand_off(results: ResultsHandoff) -> str:
    """Store the results with the genetics assistant; returns the address of a chat about them."""
    key = await handoff_key()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GENETICS_API_URL}/api/v1/results",
            json=results.model_dump(exclude_none=True),
            headers={"X-Handoff-Key": key},
        )
    if resp.status_code != 201:
        raise HandoffError(f"The genetics assistant didn't accept the results (HTTP {resp.status_code}).")
    return f"{GENETICS_URL}/?results={resp.json()['results_id']}"
