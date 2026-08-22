"""Azure OpenAI ``text-embedding-3-small`` embedding client.

The provider is a small Protocol so callers (the seed step and, later, the
suggestion engine) can depend on the contract and tests can inject
deterministic vectors without hitting Azure.
"""

from __future__ import annotations

from typing import Protocol

from openai import AzureOpenAI

from riskapp.config import settings

# text-embedding-3-small produces 1536-dimension vectors.
EMBEDDING_DIM = 1536


class EmbeddingProvider(Protocol):
    """Contract for producing text embeddings."""

    def embed_text(self, text: str) -> list[float]:
        """Embed a single text into a vector."""
        ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts, returning one vector per input (same order)."""
        ...


class AzureOpenAIEmbeddings:
    """Embedding client backed by an Azure OpenAI deployment."""

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        deployment: str | None = None,
        api_version: str | None = None,
    ) -> None:
        self._endpoint = endpoint or settings.azure_openai_endpoint
        self._api_key = api_key or settings.azure_openai_api_key
        self._deployment = deployment or settings.azure_openai_embedding_deployment
        self._api_version = api_version or settings.azure_openai_api_version
        self._client: AzureOpenAI | None = None

    def _ensure_client(self) -> AzureOpenAI:
        if not self._endpoint or not self._api_key:
            raise RuntimeError(
                "Azure OpenAI is not configured; set "
                "RISKAPP_AZURE_OPENAI_ENDPOINT and RISKAPP_AZURE_OPENAI_API_KEY."
            )
        if self._client is None:
            self._client = AzureOpenAI(
                api_key=self._api_key,
                api_version=self._api_version,
                azure_endpoint=self._endpoint,
            )
        return self._client

    def embed_text(self, text: str) -> list[float]:
        """Embed a single text into a vector."""
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts, returning one vector per input (same order)."""
        if not texts:
            return []
        response = self._ensure_client().embeddings.create(
            model=self._deployment,
            input=texts,
        )
        return [item.embedding for item in response.data]
