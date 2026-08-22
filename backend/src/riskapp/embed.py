"""Seed embeddings for all risks that don't have one yet.

Usage:
    python -m riskapp.embed

Reads Azure OpenAI settings from the environment:
    RISKAPP_AZURE_OPENAI_ENDPOINT, RISKAPP_AZURE_OPENAI_API_KEY,
    RISKAPP_AZURE_OPENAI_EMBEDDING_DEPLOYMENT (default text-embedding-3-small),
    RISKAPP_AZURE_OPENAI_API_VERSION (default 2024-02-01).
"""

from __future__ import annotations

from riskapp.db import SessionLocal
from riskapp.embeddings import AzureOpenAIEmbeddings
from riskapp.vector_store import embed_all_risks


def main() -> None:
    client = AzureOpenAIEmbeddings()
    with SessionLocal() as db:
        count = embed_all_risks(db, client)
    print(f"Embedded {count} risk(s).")


if __name__ == "__main__":
    main()
