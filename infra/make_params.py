#!/usr/bin/env python3
"""Build an Azure deployment parameters JSON for infra/main.bicep.

Note: for normal deployments prefer ``infra/deploy-service.sh`` (or ``.ps1``),
which renders these parameters from the environment / ``backend/.env`` and also
supplies registry credentials and the per-service toggles. This helper is kept
for scripts that only need a parameters file.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / "backend" / ".env"

SECRET_VARS = [
    "RISKAPP_DATABASE_URL",
    "RISKAPP_REDIS_URL",
    "RISKAPP_AZURE_OPENAI_ENDPOINT",
    "RISKAPP_AZURE_OPENAI_API_KEY",
    "RISKAPP_AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    "RISKAPP_AZURE_OPENAI_CHAT_DEPLOYMENT",
    "RISKAPP_AZURE_OPENAI_API_VERSION",
    "RISKAPP_ACS_ENDPOINT",
    "RISKAPP_ACS_ACCESS_KEY",
    "RISKAPP_ACS_SENDER_EMAIL",
    "RISKAPP_BLOB_ACCOUNT_NAME",
    "RISKAPP_BLOB_ACCOUNT_KEY",
    "RISKAPP_BLOB_CONTAINER",
    "RISKAPP_ENTRA_TENANT_ID",
    "RISKAPP_ENTRA_CLIENT_ID",
    "RISKAPP_ENTRA_CLIENT_SECRET",
    "RISKAPP_ENTRA_ROLE_GROUP_IDS",
]

PLAIN_ENV_VARS = [
    "RISKAPP_APP_BASE_URL",
    "RISKAPP_CORS_ORIGINS",
]

REQUIRED = [
    "RISKAPP_DATABASE_URL",
    "RISKAPP_REDIS_URL",
    "RISKAPP_AZURE_OPENAI_ENDPOINT",
    "RISKAPP_AZURE_OPENAI_API_KEY",
]


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def _normalize_secret_name(name: str) -> str:
    """Convert secret name to Container Apps compatible format."""
    # Replace RISKAPP_ prefix with lowercase riskapp-
    if name.startswith("RISKAPP_"):
        name = "riskapp-" + name[8:]
    # Replace underscores with dashes
    return name.lower().replace("_", "-")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment-name", required=True)
    parser.add_argument("--prefix", default="riskapp")
    parser.add_argument("--location", default="eastus")
    parser.add_argument("--acr-name", required=True)
    parser.add_argument("--image-tag", default="latest")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    file_values = _parse_env_file(ENV_FILE)
    env = os.environ

    def value(name: str) -> str:
        return env.get(name, file_values.get(name, "")).strip()

    secrets_list = []
    for name in SECRET_VARS:
        v = value(name)
        if v:
            secrets_list.append({
                "name": _normalize_secret_name(name),
                "value": v
            })

    plain_env = []
    for name in PLAIN_ENV_VARS:
        v = value(name)
        if v:
            plain_env.append({"name": name, "value": v})

    missing = [name for name in REQUIRED if not value(name)]
    if missing:
        print("WARNING: missing required values for: " + ", ".join(missing))
        print("         (set env vars or populate backend/.env)")

    parameters = {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {
            "environmentName": {"value": args.environment_name},
            "prefix": {"value": args.prefix},
            "location": {"value": args.location},
            "acrName": {"value": args.acr_name},
            "imageTag": {"value": args.image_tag},
            "appSecrets": {"value": secrets_list},
            "appEnv": {"value": plain_env},
        },
    }
    Path(args.output).write_text(json.dumps(parameters, indent=2), encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
