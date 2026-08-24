"""Risk suggestion service — hybrid retrieval + LLM analysis + citation audit.

SPEC §7. The deterministic retrieval (exact department/project-type match,
keyword token match, pgvector semantic match) is the source of truth for the
suggested risks; the LLM only analyses and summarises what was retrieved. Its
text is audited so no citation can reference a risk outside the payload.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from riskapp import models, schemas
from riskapp.domain.retrieval import (
    ExactMatch,
    KeywordMatch,
    RetrievedCandidate,
    merge_candidates,
)
from riskapp.domain.scoring import compute_risk_rating
from riskapp.domain.status import RiskStatus
from riskapp.embeddings import EmbeddingProvider
from riskapp.llm.chat import ChatProvider
from riskapp.llm.citations import audit_citations, linkify
from riskapp.llm.prompts import SYSTEM_PROMPT, build_user_prompt, parse_llm_response
from riskapp.services import accept_risk, next_risk_code
from riskapp.vector_store import semantic_search

HISTORICAL_SOURCE = "Historical"
DEFAULT_SEMANTIC_THRESHOLD = 0.75
DEFAULT_SEMANTIC_LIMIT = 20
DEFAULT_CANDIDATE_LIMIT = 12

_STOPWORDS = frozenset(
    {"the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "with", "at", "by"}
)
_TOKEN_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class SuggestionResult:
    """Structured suggestion payload (shapes the API response)."""

    project_id: int
    overview: str
    recommendations: list[str]
    suggested_risks: list[dict[str, Any]]
    evaluation: dict[str, Any] = field(default_factory=dict)


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, drop stopwords/short tokens."""
    return [
        token
        for token in _TOKEN_RE.split(text.lower())
        if len(token) > 1 and token not in _STOPWORDS
    ]


def build_query_text(project: models.Project) -> str:
    """Text used to embed the new project for semantic retrieval."""
    return " | ".join(
        filter(
            None,
            [project.name, project.department_name, project.project_type_name],
        )
    )


def _historical_risks(db: Session) -> list[models.Risk]:
    return list(
        db.scalars(
            select(models.Risk)
            .options(selectinload(models.Risk.project))
            .where(models.Risk.source == HISTORICAL_SOURCE)
            .order_by(models.Risk.id)
        ).all()
    )


def exact_candidates(
    project: models.Project, historical: list[models.Risk]
) -> list[ExactMatch]:
    """Historical risks from the same department and project type."""
    matches: list[ExactMatch] = []
    for risk in historical:
        if (
            risk.project.department_id == project.department_id
            and risk.project.project_type_id == project.project_type_id
        ):
            matches.append(
                ExactMatch(
                    risk_id=risk.risk_code,
                    source_file=risk.source_file_name or "",
                    source_risk_id=risk.source_risk_id,
                    description=risk.description,
                )
            )
    return matches


def keyword_candidates(
    project: models.Project,
    historical: list[models.Risk],
    *,
    tokens: list[str] | None = None,
) -> list[KeywordMatch]:
    """Historical risks whose category/subcategory/description share tokens."""
    query_tokens = tokens or _tokenize(build_query_text(project))
    if not query_tokens:
        return []

    matches: list[KeywordMatch] = []
    for risk in historical:
        haystack = " ".join(
            filter(None, [risk.category or "", risk.subcategory or "", risk.description])
        ).lower()
        match_count = sum(1 for token in query_tokens if token in haystack)
        if match_count > 0:
            matches.append(
                KeywordMatch(
                    risk_id=risk.risk_code,
                    source_file=risk.source_file_name or "",
                    match_count=match_count,
                    source_risk_id=risk.source_risk_id,
                    description=risk.description,
                )
            )
    return matches


def retrieve_candidates(
    db: Session,
    project: models.Project,
    embedding_provider: EmbeddingProvider,
    *,
    semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> list[RetrievedCandidate]:
    """Run hybrid retrieval and return the deduplicated, ranked candidates."""
    historical = _historical_risks(db)
    historical_codes = {risk.risk_code for risk in historical}

    exact = exact_candidates(project, historical)
    keyword = keyword_candidates(project, historical)

    query_vector = embedding_provider.embed_text(build_query_text(project))
    semantic = [
        match
        for match in semantic_search(
            db,
            query_vector,
            limit=DEFAULT_SEMANTIC_LIMIT,
            threshold=semantic_threshold,
        )
        if match.risk_id in historical_codes
    ]

    merged = merge_candidates(
        exact, keyword, semantic, semantic_threshold=semantic_threshold
    )

    # Drop risks the PM has already dismissed for this project.
    dismissed = {
        row[0]
        for row in db.execute(
            select(models.SuggestionDismissal.historical_risk_key).where(
                models.SuggestionDismissal.project_id == project.id
            )
        ).all()
    }
    merged = [candidate for candidate in merged if candidate.risk_id not in dismissed]

    return merged[:candidate_limit]


def generate_suggestions(
    db: Session,
    project: models.Project,
    chat: ChatProvider,
    embedding_provider: EmbeddingProvider,
    *,
    semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> SuggestionResult:
    """Retrieve candidate risks, run the LLM analysis, and audit its citations."""
    candidates = retrieve_candidates(
        db,
        project,
        embedding_provider,
        semantic_threshold=semantic_threshold,
        candidate_limit=candidate_limit,
    )

    # URL per source file, preferring a stored blob URL when present.
    historical = _historical_risks(db)
    url_by_file: dict[str, str] = {}
    for risk in historical:
        if risk.source_file_name:
            url_by_file[risk.source_file_name] = (
                risk.source_file_url or f"/files/{risk.source_file_name}"
            )

    def url_for(source_file: str) -> str:
        return url_by_file.get(source_file, f"/files/{source_file}")

    candidate_keys = {
        (candidate.risk_id, candidate.source_file) for candidate in candidates
    }

    payload = [
        {
            "risk_id": candidate.risk_id,
            "source_file": candidate.source_file,
            "description": candidate.description,
        }
        for candidate in candidates
    ]

    parsed: dict[str, Any] = {}
    try:
        llm_text = chat.complete(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_user_prompt(
                        project.name,
                        project.department_name,
                        project.project_type_name,
                        payload,
                    ),
                },
            ]
        )
        parsed = parse_llm_response(llm_text)
    except Exception:
        parsed = {}

    overview_raw = str(parsed.get("overview", ""))
    recommendations_raw = [
        item for item in parsed.get("recommendations", []) if isinstance(item, str)
    ]
    analyses_raw = [
        item for item in parsed.get("analyses", []) if isinstance(item, Mapping)
    ]

    # Audit citations against the retrieved payload, over the plain text
    # content (never the raw JSON envelope, whose array brackets are not
    # citations).
    citation_text = "\n".join(
        [overview_raw, *recommendations_raw]
        + [str(item.get("analysis", "")) for item in analyses_raw]
    )
    audit = audit_citations(citation_text, candidate_keys)

    overview = linkify(overview_raw, url_for) or (
        f"{len(candidates)} historical risks retrieved across the "
        f"{project.department_name} / {project.project_type_name} portfolio."
    )
    recommendations = [
        linkify(item, url_for) for item in recommendations_raw if item.strip()
    ]

    analyses = {
        str(item.get("risk_id", "")): linkify(str(item.get("analysis", "")), url_for)
        for item in analyses_raw
        if item.get("risk_id")
    }

    suggested_risks: list[dict[str, Any]] = []
    for candidate in candidates:
        suggested_risks.append(
            {
                "risk_id": candidate.risk_id,
                "source_file": candidate.source_file,
                "source_file_url": url_for(candidate.source_file),
                "source_risk_id": candidate.source_risk_id,
                "description": candidate.description,
                "match_type": candidate.match_type.value,
                "match_count": candidate.match_count,
                "similarity": candidate.similarity,
                "citation": f"[{candidate.risk_id}, {candidate.source_file}]",
                "analysis": analyses.get(candidate.risk_id),
            }
        )

    evaluation = {
        "groundedness": audit.groundedness,
        "verified_citations": [
            {"risk_id": c.risk_id, "source_file": c.source_file}
            for c in audit.verified
        ],
        "unverified_citations": [
            {"risk_id": c.risk_id, "source_file": c.source_file}
            for c in audit.unverified
        ],
    }

    return SuggestionResult(
        project_id=project.id,
        overview=overview,
        recommendations=recommendations,
        suggested_risks=suggested_risks,
        evaluation=evaluation,
    )


def list_suggestions(
    db: Session,
    project: models.Project,
    *,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> list[schemas.SuggestedRiskRead]:
    """Return deterministic suggestions for ``project`` (exact + keyword retrieval).

    Pure local retrieval — no LLM or embeddings — so it works immediately after
    onboarding. Already-dismissed or already-accepted candidates are excluded.
    """
    historical = _historical_risks(db)
    by_code = {risk.risk_code: risk for risk in historical}

    exact = exact_candidates(project, historical)
    keyword = keyword_candidates(project, historical)
    candidates = merge_candidates(exact, keyword, [], semantic_threshold=0.0)

    dismissed = {
        row[0]
        for row in db.execute(
            select(models.SuggestionDismissal.historical_risk_key).where(
                models.SuggestionDismissal.project_id == project.id
            )
        ).all()
    }

    suggestions: list[schemas.SuggestedRiskRead] = []
    for candidate in candidates:
        if candidate.risk_id in dismissed:
            continue
        source = by_code.get(candidate.risk_id)
        if source is None:
            continue
        suggestions.append(
            schemas.SuggestedRiskRead(
                risk_id=candidate.risk_id,
                source_file=candidate.source_file,
                source_file_url=source.source_file_url or f"/files/{candidate.source_file}",
                source_risk_id=candidate.source_risk_id,
                description=candidate.description,
                match_type=candidate.match_type.value,
                match_count=candidate.match_count,
                similarity=candidate.similarity,
                citation=f"[{candidate.risk_id}, {candidate.source_file}]",
                analysis=None,
                likelihood=source.likelihood,
                impact=source.impact,
                risk_rating=source.risk_rating,
                category=source.category,
            )
        )
        if len(suggestions) >= candidate_limit:
            break

    return suggestions


def accept_suggestion(
    db: Session,
    project: models.Project,
    risk_id: str,
    *,
    likelihood: str | None = None,
    impact: str | None = None,
    actor_user_id: int | None = None,
) -> models.Risk:
    """Accept a suggested historical risk into ``project`` as an Open risk.

    Copies the source risk's fields (with optional likelihood/impact override),
    transitions it straight to Open via the normal accept flow, and records an
    exclusion so the same historical risk is never suggested again.
    """
    source = db.scalar(select(models.Risk).where(models.Risk.risk_code == risk_id))
    if source is None:
        raise ValueError(f"Unknown historical risk {risk_id!r}")

    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    final_likelihood = likelihood or source.likelihood
    final_impact = impact or source.impact

    risk = models.Risk(
        project_id=project.id,
        risk_code=next_risk_code(db),
        description=source.description,
        category=source.category,
        subcategory=source.subcategory,
        risk_source=source.risk_source,
        likelihood=final_likelihood,
        impact=final_impact,
        risk_rating=compute_risk_rating(final_likelihood, final_impact),
        response_strategy=source.response_strategy,
        status=RiskStatus.SUGGESTED.value,
        source=HISTORICAL_SOURCE,
        source_file_name=source.source_file_name,
        source_file_url=source.source_file_url,
        source_risk_id=source.source_risk_id,
        created_at=now,
        updated_at=now,
    )
    risk.project = project
    db.add(risk)
    db.commit()
    db.refresh(risk)

    accepted = accept_risk(db, risk, actor_user_id=actor_user_id)

    db.add(
        models.SuggestionDismissal(
            project_id=project.id,
            historical_risk_key=risk_id,
            reason="Accepted",
        )
    )
    db.commit()
    return accepted


def dismiss_suggestion(
    db: Session,
    project: models.Project,
    risk_id: str,
    *,
    reason: str | None = None,
) -> None:
    """Dismiss a suggested historical risk so it is never suggested again."""
    if db.scalar(select(models.Risk).where(models.Risk.risk_code == risk_id)) is None:
        raise ValueError(f"Unknown historical risk {risk_id!r}")

    existing = db.scalar(
        select(models.SuggestionDismissal).where(
            models.SuggestionDismissal.project_id == project.id,
            models.SuggestionDismissal.historical_risk_key == risk_id,
        )
    )
    if existing is None:
        db.add(
            models.SuggestionDismissal(
                project_id=project.id,
                historical_risk_key=risk_id,
                reason=reason,
            )
        )
        db.commit()
