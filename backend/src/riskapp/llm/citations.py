"""Grounded citation handling.

Suggestions must be grounded: every claim the LLM makes about a historical
risk carries a ``[RiskID, file.xlsx]`` citation, and that citation is audited
against the exact retrieved payload before it is shown to a user. This module
owns the citation grammar, linkification, and the audit that computes a
groundedness score.

The citation grammar is deliberately strict — ``[risk_id, source_file]`` —
so it can be parsed deterministically. Unknown citations are surfaced as
``[unverified]`` rather than silently trusted.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

# [RiskID, file.xlsx]  (no nesting; risk_id never contains a comma)
_CITATION_RE = re.compile(r"\[([^,\]]+),\s*([^\]]+)\]")


@dataclass(frozen=True)
class Citation:
    """A single parsed citation."""

    risk_id: str
    source_file: str


@dataclass(frozen=True)
class CitationAudit:
    """The outcome of auditing the citations in an LLM response."""

    verified: tuple[Citation, ...]
    unverified: tuple[Citation, ...]

    @property
    def groundedness(self) -> float:
        """Fraction of citations grounded in the retrieved payload (0.0–1.0).

        A response with no citations is vacuously grounded (nothing to verify),
        so it scores 1.0.
        """
        total = len(self.verified) + len(self.unverified)
        if total == 0:
            return 1.0
        return len(self.verified) / total


def extract_citations(text: str) -> list[Citation]:
    """Parse every ``[RiskID, file.xlsx]`` citation out of ``text`` (in order)."""
    return [
        Citation(risk_id=m.group(1).strip(), source_file=m.group(2).strip())
        for m in _CITATION_RE.finditer(text)
    ]


def _default_url(source_file: str) -> str:
    """Default citation target: a relative app route for the source register."""
    return f"/files/{source_file}"


def linkify(text: str, url_for: Callable[[str], str] = _default_url) -> str:
    """Rewrite citations as Markdown links, e.g. ``[RSK-1](/files/a.xlsx)``.

    ``url_for`` receives the source file name and returns the URL to embed.
    """

    def repl(m: re.Match[str]) -> str:
        risk_id = m.group(1).strip()
        source_file = m.group(2).strip()
        return f"[{risk_id}]({url_for(source_file)})"

    return _CITATION_RE.sub(repl, text)


def audit_citations(
    text: str, candidate_keys: Iterable[tuple[str, str]]
) -> CitationAudit:
    """Audit every citation in ``text`` against the retrieved candidate set.

    ``candidate_keys`` is an iterable of ``(risk_id, source_file)`` tuples that
    were actually retrieved and handed to the LLM. A citation is verified only
    when both the risk id and the source file match a retrieved candidate.
    """
    keys = {(risk_id.strip(), source_file.strip()) for risk_id, source_file in candidate_keys}
    verified: list[Citation] = []
    unverified: list[Citation] = []

    for citation in extract_citations(text):
        if (citation.risk_id, citation.source_file) in keys:
            verified.append(citation)
        else:
            unverified.append(citation)

    return CitationAudit(verified=tuple(verified), unverified=tuple(unverified))
