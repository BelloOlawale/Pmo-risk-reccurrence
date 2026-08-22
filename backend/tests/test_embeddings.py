"""Tests for the Azure OpenAI embedding client."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from riskapp.embeddings import AzureOpenAIEmbeddings


class TestAzureOpenAIEmbeddings:
    def test_missing_credentials_raises(self) -> None:
        client = AzureOpenAIEmbeddings(endpoint="", api_key="", deployment="d")
        with pytest.raises(RuntimeError, match="not configured"):
            client.embed_text("hello")

    def test_embed_text_delegates_to_client(self) -> None:
        client = AzureOpenAIEmbeddings(
            endpoint="https://example.openai.azure.com",
            api_key="secret",
            deployment="text-embedding-3-small",
        )
        fake = MagicMock()
        item = MagicMock()
        item.embedding = [0.1, 0.2, 0.3]
        fake.embeddings.create.return_value = MagicMock(data=[item])
        client._client = fake  # noqa: SLF001 — inject the underlying client

        assert client.embed_text("hello") == [0.1, 0.2, 0.3]
        fake.embeddings.create.assert_called_once()

    def test_embed_texts_returns_one_vector_per_input(self) -> None:
        client = AzureOpenAIEmbeddings(
            endpoint="https://example.openai.azure.com",
            api_key="secret",
            deployment="text-embedding-3-small",
        )
        fake = MagicMock()
        fake.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=[1.0]), MagicMock(embedding=[2.0])]
        )
        client._client = fake  # noqa: SLF001

        assert client.embed_texts(["a", "b"]) == [[1.0], [2.0]]

    def test_embed_texts_empty_returns_empty(self) -> None:
        client = AzureOpenAIEmbeddings(
            endpoint="https://example.openai.azure.com",
            api_key="secret",
            deployment="text-embedding-3-small",
        )
        assert client.embed_texts([]) == []
