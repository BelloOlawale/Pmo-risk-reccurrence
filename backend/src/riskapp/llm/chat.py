"""Azure OpenAI chat completions client.

Mirrors the embedding client: a Protocol defines the contract callers depend
on, and the concrete client wraps the Azure OpenAI SDK. Tests inject fakes.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from openai import AzureOpenAI

from riskapp.config import settings


class ChatProvider(Protocol):
    """Contract for producing a chat completion for a message list."""

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1500,
    ) -> str:
        """Return the assistant's completion text for ``messages``."""
        ...


class AzureOpenAIChat:
    """Chat client backed by an Azure OpenAI chat deployment."""

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        deployment: str | None = None,
        api_version: str | None = None,
    ) -> None:
        self._endpoint = settings.azure_openai_endpoint if endpoint is None else endpoint
        self._api_key = settings.azure_openai_api_key if api_key is None else api_key
        self._deployment = (
            settings.azure_openai_chat_deployment if deployment is None else deployment
        )
        self._api_version = (
            settings.azure_openai_api_version if api_version is None else api_version
        )
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

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1500,
    ) -> str:
        """Run a chat completion and return the assistant message text."""
        response = self._ensure_client().chat.completions.create(
            model=self._deployment,
            messages=cast(Any, messages),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content
        return content or ""
