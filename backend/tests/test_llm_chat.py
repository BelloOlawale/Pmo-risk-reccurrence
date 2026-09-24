"""Tests for the Azure OpenAI chat client.

Focuses on the request shape, which differs between legacy chat models
(``max_tokens`` + ``temperature``) and GPT-5.x / o-series reasoning models
(``max_completion_tokens``, no custom ``temperature``).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from riskapp.llm.chat import AzureOpenAIChat, is_reasoning_model


def _fake_client(content: str = "hello") -> MagicMock:
    fake = MagicMock()
    fake.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=content))]
    )
    return fake


def _chat(deployment: str) -> tuple[AzureOpenAIChat, MagicMock]:
    client = AzureOpenAIChat(
        endpoint="https://example.openai.azure.com",
        api_key="secret",
        deployment=deployment,
    )
    fake = _fake_client()
    client._client = fake  # noqa: SLF001 - inject the underlying client
    return client, fake


class TestIsReasoningModel:
    @pytest.mark.parametrize(
        "model", ["gpt-5.4", "gpt-5.4-mini", "gpt-5", "o1", "o3-mini", "o4-mini"]
    )
    def test_reasoning_models_detected(self, model: str) -> None:
        assert is_reasoning_model(model) is True

    @pytest.mark.parametrize("model", ["gpt-4o", "gpt-4o-mini", "gpt-4.1-mini", "gpt-35-turbo"])
    def test_legacy_models_not_detected(self, model: str) -> None:
        assert is_reasoning_model(model) is False


class TestAzureOpenAIChat:
    def test_missing_credentials_raises(self) -> None:
        client = AzureOpenAIChat(endpoint="", api_key="", deployment="gpt-5.4")
        with pytest.raises(RuntimeError, match="not configured"):
            client.complete([{"role": "user", "content": "hi"}])

    def test_reasoning_model_uses_max_completion_tokens_without_temperature(self) -> None:
        client, fake = _chat("gpt-5.4")

        assert client.complete([{"role": "user", "content": "hi"}], max_tokens=123) == "hello"

        kwargs = fake.chat.completions.create.call_args.kwargs
        assert kwargs["model"] == "gpt-5.4"
        assert kwargs["max_completion_tokens"] == 123
        assert "max_tokens" not in kwargs
        assert "temperature" not in kwargs

    def test_legacy_model_uses_max_tokens_and_temperature(self) -> None:
        client, fake = _chat("gpt-4o-mini")

        client.complete([{"role": "user", "content": "hi"}], temperature=0.2, max_tokens=99)

        kwargs = fake.chat.completions.create.call_args.kwargs
        assert kwargs["max_tokens"] == 99
        assert kwargs["temperature"] == 0.2
        assert "max_completion_tokens" not in kwargs

    def test_empty_content_returns_empty_string(self) -> None:
        client, fake = _chat("gpt-5.4")
        fake.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=None))]
        )

        assert client.complete([{"role": "user", "content": "hi"}]) == ""
