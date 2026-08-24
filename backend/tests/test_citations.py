"""Tests for citation parsing, linkification, and groundedness audit."""

from __future__ import annotations

from riskapp.llm.citations import (
    audit_citations,
    extract_citations,
    linkify,
)


class TestExtractCitations:
    def test_extracts_single(self) -> None:
        citations = extract_citations("[RSK-001, a.xlsx]")
        assert [(c.risk_id, c.source_file) for c in citations] == [("RSK-001", "a.xlsx")]

    def test_extracts_multiple_in_order(self) -> None:
        text = "[RSK-1, a.xlsx] and [RSK-2, b.xlsx]"
        citations = extract_citations(text)
        assert [(c.risk_id, c.source_file) for c in citations] == [
            ("RSK-1", "a.xlsx"),
            ("RSK-2", "b.xlsx"),
        ]

    def test_ignores_non_citations(self) -> None:
        assert extract_citations("plain text [not a citation]") == []

    def test_strips_whitespace(self) -> None:
        citations = extract_citations("[ RSK-1 , a.xlsx ]")
        assert (citations[0].risk_id, citations[0].source_file) == ("RSK-1", "a.xlsx")


class TestLinkify:
    def test_converts_to_markdown_link(self) -> None:
        assert linkify("[RSK-1, a.xlsx]") == "[RSK-1](/files/a.xlsx)"

    def test_uses_custom_url_builder(self) -> None:
        result = linkify("[RSK-1, a.xlsx]", url_for=lambda f: f"https://blob/{f}")
        assert result == "[RSK-1](https://blob/a.xlsx)"

    def test_leaves_other_text_untouched(self) -> None:
        assert linkify("See [RSK-1, a.xlsx] for details") == (
            "See [RSK-1](/files/a.xlsx) for details"
        )


class TestAuditCitations:
    def test_all_verified_groundedness_one(self) -> None:
        audit = audit_citations(
            "[RSK-1, a.xlsx] [RSK-2, b.xlsx]",
            [("RSK-1", "a.xlsx"), ("RSK-2", "b.xlsx")],
        )
        assert len(audit.verified) == 2
        assert len(audit.unverified) == 0
        assert audit.groundedness == 1.0

    def test_unknown_risk_marked_unverified(self) -> None:
        audit = audit_citations(
            "[RSK-1, a.xlsx] [RSK-99, ghost.xlsx]",
            [("RSK-1", "a.xlsx")],
        )
        assert len(audit.verified) == 1
        assert len(audit.unverified) == 1
        assert audit.unverified[0].risk_id == "RSK-99"
        assert audit.groundedness == 0.5

    def test_mismatched_file_is_unverified(self) -> None:
        audit = audit_citations(
            "[RSK-1, wrong.xlsx]",
            [("RSK-1", "a.xlsx")],
        )
        assert len(audit.unverified) == 1

    def test_no_citations_is_vacuously_grounded(self) -> None:
        audit = audit_citations("no citations here", [("RSK-1", "a.xlsx")])
        assert audit.groundedness == 1.0
        assert len(audit.verified) == 0
