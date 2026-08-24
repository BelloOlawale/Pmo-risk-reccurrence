"""LLM layer: Azure OpenAI chat, prompt building, and citation grounding.

All I/O lives behind small Protocols so the suggestion service and its tests
can inject deterministic fakes and never touch Azure.
"""

from riskapp.llm.chat import AzureOpenAIChat, ChatProvider
from riskapp.llm.citations import (
    Citation,
    CitationAudit,
    audit_citations,
    extract_citations,
    linkify,
)
from riskapp.llm.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    parse_llm_response,
)

__all__ = [
    "AzureOpenAIChat",
    "ChatProvider",
    "Citation",
    "CitationAudit",
    "SYSTEM_PROMPT",
    "audit_citations",
    "build_user_prompt",
    "extract_citations",
    "linkify",
    "parse_llm_response",
]
