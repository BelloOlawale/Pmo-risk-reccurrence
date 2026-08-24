"""Prompt construction and LLM response parsing for risk suggestions."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

SYSTEM_PROMPT = (
    "You are a PMO risk analyst at Wragby. A project manager is about to start "
    "a new engagement and has asked for a risk landscape analysis.\n"
    "You are given a list of retrieved historical risks from past projects. "
    "Work ONLY from those risks. Never invent risks, files, or statistics.\n"
    "Every time you mention a historical risk, cite it inline using the exact "
    "format [RiskID, file.xlsx]. Use the RiskID and source file exactly as "
    "listed.\n"
    "Respond with a single JSON object with exactly these keys:\n"
    '  "overview": a 2-4 sentence risk-landscape overview,\n'
    '  "recommendations": an array of 2-4 short, concrete recommendations,\n'
    '  "analyses": an array of {"risk_id": "<RiskID>", "analysis": "<1 sentence>"} '
    "for the most important retrieved risks.\n"
    "Do not wrap the JSON in prose or code fences."
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def build_user_prompt(
    project_name: str,
    department: str,
    project_type: str,
    candidates: Sequence[Mapping[str, str]],
) -> str:
    """Render the project context and retrieved candidates for the LLM.

    Each candidate must expose at least ``risk_id``, ``source_file``, and
    ``description`` keys.
    """
    lines = [
        "New project context:",
        f"- Project: {project_name}",
        f"- Department: {department}",
        f"- Project type: {project_type}",
        "",
        "Retrieved historical risks (cite these exactly):",
    ]
    if not candidates:
        lines.append("(none)")
    for i, candidate in enumerate(candidates, start=1):
        risk_id = candidate.get("risk_id", "")
        source_file = candidate.get("source_file", "")
        description = candidate.get("description", "")
        lines.append(f"{i}. [{risk_id}, {source_file}] {description}")
    lines.append("")
    lines.append("Return the JSON risk landscape now.")
    return "\n".join(lines)


def parse_llm_response(text: str) -> dict[str, Any]:
    """Parse the LLM's JSON payload, tolerating code fences and stray prose.

    Returns an empty dict when no JSON object can be recovered, so callers can
    fall back to the deterministic retrieval results.
    """
    cleaned = text.strip()

    fenced = _FENCE_RE.search(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()

    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass

    # Fall back to the first balanced {...} block in the text.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            value = json.loads(cleaned[start : end + 1])
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
