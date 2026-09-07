#!/usr/bin/env python3
"""Build an Azure deployment parameters JSON for infra/main.bicep.

Values come from (highest priority first):
  1. Explicit CLI options (--acr-name, --image-tag, etc.)
  2. Environment variables (RISKAPP_*, RISKAPP_APP_BASE_URL, RISKAPP_CORS_ORIGINS)
  3. backend/.env (same RISKAPP_* names) so a local run needs no manual export

The RISKAPP_* values become container-app secrets (and env vars of the same
name) on every deployed container app. Non-secret app env vars come from
RISKAPP_APP_BASE_URL / RISKAPP_CORS_ORIGINS if set.

Usage:
    python make_params.py \
        --environment-name dev --prefix riskapp --acr-name <acr> \
        --image-tag latest --deploy-apps true --output params.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / "backend" / ".env"

# Secret env vars: passed as container-app secrets and referenced as env vars.
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

# Plain env vars (not secret-bearing) applied as app env vars.
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment-name", required=True)
    parser.add_argument("--prefix", default="riskapp")
    parser.add_argument("--location", default="eastus")
    parser.add_argument("--acr-name", required=True)
    parser.add_argument("--image-tag", default="latest")
    parser.add_argument("--deploy-apps", choices=["true", "false"], default="true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    file_values = _parse_env_file(ENV_FILE)
    env = os.environ

    def value(name: str) -> str:
        return env.get(name, file_values.get(name, "")).strip()

    secrets = []
    for name in SECRET_VARS:
        v = value(name)
        if v:
            secrets.append({"name": name, "value": v})

    plain_env = []
    for name in PLAIN_ENV_VARS:
        v = value(name)
        if v:
            plain_env.append({"name": name, "value": v})

    missing = [name for name in REQUIRED if not value(name)]
    if missing:
        print("WARNING: missing required values for: " + ", ".join(missing))
        print("         (set env vars or populate backend/.env)")
        print("         The deploy will still run but apps may fail at runtime.")

    parameters = {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {
            "environmentName": {"value": args.environment_name},
            "prefix": {"value": args.prefix},
            "location": {"value": args.location},
            "acrName": {"value": args.acr_name},
            "imageTag": {"value": args.image_tag},
            "deployApps": {"value": args.deploy_apps == "true"},
            "appSecrets": {"value": secrets},
            "appEnv": {"value": plain_env},
        },
    }
    Path(args.output).write_text(json.dumps(parameters, indent=2), encoding="utf-8")
    print(f"wrote {args.output} "
          f"(secrets: {len(secrets)}, plain env: {len(plain_env)}, "
          f"deployApps: {args.deploy_apps})")


if __name__ == "__main__":
    main()
