"""Load configuration into the environment before other modules read it.

Locally: agent-chat/.env. On AWS: every parameter under SSM_PARAMETER_PATH
(e.g. /mcp-post-pilot/OPENAI_API_KEY becomes OPENAI_API_KEY). Variables that
are already set win in both cases.
"""

import os
from pathlib import Path

from dotenv import load_dotenv


def load_settings() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")

    path = os.getenv("SSM_PARAMETER_PATH")
    if not path:
        return
    import boto3

    pages = boto3.client("ssm").get_paginator("get_parameters_by_path").paginate(Path=path, WithDecryption=True)
    for page in pages:
        for param in page["Parameters"]:
            os.environ.setdefault(param["Name"].rsplit("/", 1)[-1], param["Value"])
