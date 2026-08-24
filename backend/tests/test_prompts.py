"""Tests for prompt construction and LLM response parsing."""

from __future__ import annotations

from riskapp.llm.prompts import SYSTEM_PROMPT, build_user_prompt, parse_llm_response


class TestBuildUserPrompt:
    def test_includes_project_context(self) -> None:
        prompt = build_user_prompt(
            "NHIA AWS", "Digital Advisory", "Cloud Migration", []
        )
        assert "NHIA AWS" in prompt
        assert "Digital Advisory" in prompt
        assert "Cloud Migration" in prompt

    def test_lists_candidates_with_citations(self) -> None:
        prompt = build_user_prompt(
            "P", "D", "T",
            [{"risk_id": "RSK-1", "source_file": "a.xlsx", "description": "data loss"}],
        )
        assert "[RSK-1, a.xlsx]" in prompt
        assert "data loss" in prompt

    def test_empty_candidates_renders_none(self) -> None:
        prompt = build_user_prompt("P", "D", "T", [])
        assert "(none)" in prompt

    def test_system_prompt_instructs_json(self) -> None:
        assert "JSON" in SYSTEM_PROMPT
        assert "risk landscape" in SYSTEM_PROMPT


class TestParseLlmResponse:
    def test_parses_plain_json(self) -> None:
        assert parse_llm_response('{"overview": "hi"}') == {"overview": "hi"}

    def test_strips_code_fences(self) -> None:
        text = '```json\n{"overview": "hi"}\n```'
        assert parse_llm_response(text) == {"overview": "hi"}

    def test_recovers_json_from_stray_prose(self) -> None:
        text = 'Sure! Here it is:\n{"overview": "hi"}'
        assert parse_llm_response(text) == {"overview": "hi"}

    def test_invalid_returns_empty_dict(self) -> None:
        assert parse_llm_response("not json at all") == {}

    def test_non_object_returns_empty_dict(self) -> None:
        assert parse_llm_response("[1, 2, 3]") == {}
