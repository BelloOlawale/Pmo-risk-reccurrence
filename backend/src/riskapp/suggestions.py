"""Risk suggestion service — hybrid retrieval + LLM analysis + citation audit.

SPEC §7. The deterministic retrieval (exact department/project-type match,
keyword token match, pgvector semantic match) is the source of truth for the
suggested risks; the LLM only analyses and summarises what was retrieved. Its
text is audited so no citation can reference a risk outside the payload.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from riskapp import models, schemas
from riskapp.config import settings
from riskapp.domain.retrieval import (
    ExactMatch,
    KeywordMatch,
    RetrievedCandidate,
    SemanticMatch,
    merge_candidates,
)
from riskapp.domain.scoring import compute_risk_rating
from riskapp.domain.sla import deadline_from_end_date
from riskapp.domain.status import RiskStatus
from riskapp.embeddings import EmbeddingProvider
from riskapp.llm.chat import ChatProvider
from riskapp.llm.citations import audit_citations, linkify
from riskapp.llm.prompts import SYSTEM_PROMPT, build_user_prompt, parse_llm_response
from riskapp.services import accept_risk, next_risk_code
from riskapp.vector_store import semantic_search

logger = logging.getLogger(__name__)

HISTORICAL_SOURCE = "Historical"
ACCEPTED_REASON = "Accepted"
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


@dataclass
class RetrievalResult:
    """Outcome of hybrid retrieval: ranked candidates plus any degradation.

    Semantic search is best-effort. When the embedding provider or pgvector is
    unavailable, retrieval still returns the deterministic exact + keyword
    matches and records the failure in ``semantic_error`` instead of raising.
    That keeps the one suggestion pipeline usable offline while making the
    degradation visible to the caller.
    """

    candidates: list[RetrievedCandidate]
    semantic_error: str | None = None


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


def _historical_risks(
    db: Session, *, exclude_project_id: int | None = None
) -> list[models.Risk]:
    """All historical-source risks, optionally excluding one project's own rows.

    Risks accepted into a register keep ``source="Historical"`` so they can be
    re-suggested to *other* future registers (recurrence). Excluding the current
    project stops a register from suggesting its own accepted risks back to
    itself, which previously surfaced the just-accepted risk again and allowed
    it to be accepted a second time.
    """
    stmt = (
        select(models.Risk)
        .options(selectinload(models.Risk.project))
        .where(models.Risk.source == HISTORICAL_SOURCE)
    )
    if exclude_project_id is not None:
        stmt = stmt.where(models.Risk.project_id != exclude_project_id)
    return list(db.scalars(stmt.order_by(models.Risk.id)).all())


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
    embedding_provider: EmbeddingProvider | None = None,
    *,
    semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> RetrievalResult:
    """Run the single hybrid-retrieval pipeline for ``project``.

    Exact and keyword matching always run (pure, offline). Semantic matching is
    best-effort: pass ``embedding_provider`` to enable it; when it is ``None``
    or the provider/pgvector fails, retrieval still returns the deterministic
    matches and records the reason in ``RetrievalResult.semantic_error``.
    """
    historical = _historical_risks(db, exclude_project_id=project.id)
    historical_codes = {risk.risk_code for risk in historical}

    exact = exact_candidates(project, historical)
    keyword = keyword_candidates(project, historical)

    semantic: list[SemanticMatch] = []
    semantic_error: str | None = None
    if embedding_provider is not None:
        try:
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
        except Exception as exc:  # noqa: BLE001 — degrade to exact + keyword
            semantic_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Semantic retrieval failed for project %s: %s",
                project.id,
                semantic_error,
                exc_info=True,
            )

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

    return RetrievalResult(
        candidates=merged[:candidate_limit], semantic_error=semantic_error
    )


def _candidate_payload(
    candidate: RetrievedCandidate, source: models.Risk | None
) -> dict[str, Any]:
    """Project a retrieved candidate (plus its historical source) for the API.

    Shared by the deterministic and LLM-backed paths so their suggestion rows
    can never drift apart.
    """
    return {
        "risk_id": candidate.risk_id,
        "source_file": candidate.source_file,
        "source_file_url": (
            source.source_file_url
            if source and source.source_file_url
            else f"/files/{candidate.source_file}"
        ),
        "source_risk_id": candidate.source_risk_id,
        "description": candidate.description,
        "match_type": candidate.match_type.value,
        "match_count": candidate.match_count,
        "similarity": candidate.similarity,
        "citation": f"[{candidate.risk_id}, {candidate.source_file}]",
        # Rating/category come from the historical source so the review table
        # can show them on both paths.
        "likelihood": source.likelihood if source else None,
        "impact": source.impact if source else None,
        "risk_rating": source.risk_rating if source else None,
        "category": source.category if source else None,
    }


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
    retrieval = retrieve_candidates(
        db,
        project,
        embedding_provider,
        semantic_threshold=semantic_threshold,
        candidate_limit=candidate_limit,
    )
    candidates = retrieval.candidates
    semantic_error = retrieval.semantic_error

    # URL per source file, preferring a stored blob URL when present.
    historical = _historical_risks(db, exclude_project_id=project.id)
    source_by_code = {risk.risk_code: risk for risk in historical}
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

    # A failing chat deployment must not silently masquerade as "the LLM had
    # nothing to say": log it and surface it in the evaluation payload so the
    # retrieval-only fallback is visibly a fallback.
    parsed: dict[str, Any] = {}
    llm_error: str | None = None
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
    except Exception as exc:  # noqa: BLE001 — any provider failure degrades gracefully
        llm_error = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "LLM risk-analysis failed for project %s: %s",
            project.id,
            llm_error,
            exc_info=True,
        )

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
        source = source_by_code.get(candidate.risk_id)
        suggested_risks.append(
            {
                **_candidate_payload(candidate, source),
                "analysis": analyses.get(candidate.risk_id),
            }
        )

    evaluation = {
        "groundedness": audit.groundedness,
        "llm_error": llm_error,
        "semantic_error": semantic_error,
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
    """Return deterministic suggestions for ``project`` (exact + keyword).

    A thin projection over :func:`retrieve_candidates` with semantic search
    disabled, so it shares one retrieval pipeline with the LLM-backed path.
    Pure local retrieval — no LLM or embeddings — so it works immediately after
    onboarding. Already-dismissed or already-accepted candidates are excluded.
    """
    historical = _historical_risks(db, exclude_project_id=project.id)
    source_by_code = {risk.risk_code: risk for risk in historical}

    retrieval = retrieve_candidates(
        db, project, embedding_provider=None, candidate_limit=candidate_limit
    )

    return [
        schemas.SuggestedRiskRead(
            **_candidate_payload(candidate, source_by_code.get(candidate.risk_id)),
            analysis=None,
        )
        for candidate in retrieval.candidates
    ]


def _existing_accepted_risk(
    db: Session, project: models.Project, source: models.Risk
) -> models.Risk | None:
    """Return a risk already created in ``project`` from this source suggestion.

    Accepted risks copy the historical record's provenance fields, so a risk
    created from the same suggestion is identifiable by source file plus source
    risk id (or, for id-less rows, exact description — mirroring the importer's
    own dedupe semantics). When no source file is recorded the suggestion has no
    usable provenance identifier, so ``None`` is returned and the exact
    ``(project, historical_risk_key)`` processed marker is relied on instead.
    """
    if not source.source_file_name:
        return None
    query = select(models.Risk).where(
        models.Risk.project_id == project.id,
        models.Risk.source == HISTORICAL_SOURCE,
        models.Risk.source_file_name == source.source_file_name,
    )
    if source.source_risk_id:
        query = query.where(models.Risk.source_risk_id == source.source_risk_id)
    else:
        query = query.where(models.Risk.description == source.description)
    return db.scalar(query.order_by(models.Risk.id.asc()))


def accept_suggestion(
    db: Session,
    project: models.Project,
    risk_id: str,
    *,
    likelihood: str | None = None,
    impact: str | None = None,
    analysis: str | None = None,
    actor_user_id: int | None = None,
) -> models.Risk:
    """Accept a suggested historical risk into ``project`` as an Open risk.

    Copies the source risk's fields (with optional likelihood/impact override),
    transitions it straight to Open via the normal accept flow, and records an
    exclusion so the same historical risk is never suggested again.

    Acceptance is idempotent and atomic:

    * A suggestion that was already accepted for this register returns the
      previously created risk instead of creating a duplicate.
    * A suggestion that was dismissed for this register is refused.
    * The "processed" marker (a :class:`SuggestionDismissal` with reason
      ``"Accepted"``) is committed together with the new risk, so the unique
      ``(project_id, historical_risk_key)`` constraint is a hard backstop
      against double-acceptance even under concurrent requests. A lost race
      rolls back the partial risk and returns the winner's risk.
    """
    source = db.scalar(select(models.Risk).where(models.Risk.risk_code == risk_id))
    if source is None:
        raise ValueError(f"Unknown historical risk {risk_id!r}")

    def dismissal_record() -> models.SuggestionDismissal | None:
        return db.scalar(
            select(models.SuggestionDismissal).where(
                models.SuggestionDismissal.project_id == project.id,
                models.SuggestionDismissal.historical_risk_key == risk_id,
            )
        )

    # Already processed for this register? Accepted -> return the existing risk
    # (idempotent re-acceptance); dismissed -> refuse to resurrect the row.
    processed = dismissal_record()
    if processed is not None:
        if processed.reason == ACCEPTED_REASON:
            existing = _existing_accepted_risk(db, project, source)
            if existing is not None:
                return existing
        raise ValueError(
            "This suggested risk has already been processed for this register "
            "(accepted or dismissed)."
        )

    # Register-level guard: never create a second risk from the same source
    # suggestion, even if the processed marker is missing (e.g. legacy rows).
    existing = _existing_accepted_risk(db, project, source)
    if existing is not None:
        try:
            db.add(
                models.SuggestionDismissal(
                    project_id=project.id,
                    historical_risk_key=risk_id,
                    reason=ACCEPTED_REASON,
                )
            )
            db.commit()
        except IntegrityError:
            # Another request marked it processed in the meantime; the marker
            # (and risk) is already in place, nothing more to do.
            db.rollback()
        return existing

    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    final_likelihood = likelihood or source.likelihood
    final_impact = impact or source.impact
    final_rating = compute_risk_rating(final_likelihood, final_impact)

    # Enrich the accepted risk from the matched historical record. Dates are
    # copied only when they are not in the past (the PM can always set them
    # explicitly on the accepted risk). The end date is never derived from the
    # rating: it is copied from the source register as-is. The owner is
    # deliberately *not* copied: every risk gets its owner assigned manually.
    source_start = None
    if source.risk_start_date is not None and source.risk_start_date >= dt.date.today():
        source_start = source.risk_start_date
    source_end = source.risk_end_date
    # A risk cannot start before its project: clamp an automatically-enriched
    # start date up to the project start (and drop an end date that is now out
    # of order). The PM can always set the dates explicitly afterwards.
    if project.start_date is not None and (
        source_start is None or source_start < project.start_date
    ):
        source_start = project.start_date
    if source_end is not None and source_start is not None and source_end < source_start:
        source_end = None

    risk = models.Risk(
        project_id=project.id,
        risk_code=next_risk_code(db),
        description=source.description,
        category=source.category,
        subcategory=source.subcategory,
        risk_source=source.risk_source,
        likelihood=final_likelihood,
        impact=final_impact,
        risk_rating=final_rating,
        response_strategy=source.response_strategy,
        response_plan=source.response_plan,
        owner_user_id=None,
        identified_during=source.identified_during,
        risk_start_date=source_start,
        risk_end_date=source_end,
        sla_deadline=deadline_from_end_date(source_end, settings.tz),
        status=RiskStatus.SUGGESTED.value,
        source=HISTORICAL_SOURCE,
        source_file_name=source.source_file_name,
        source_file_url=source.source_file_url,
        source_risk_id=source.source_risk_id,
        # Persist the LLM's per-risk analysis so it is available on the risk
        # detail page after acceptance (it is otherwise generated and dropped).
        llm_analysis=analysis,
        created_at=now,
        updated_at=now,
    )
    risk.project = project
    db.add(risk)
    # Mark the suggestion processed in the same transaction as the risk so the
    # unique (project_id, historical_risk_key) constraint is enforced before
    # the risk row is committed. Previously the risk was committed first and a
    # second acceptance persisted a duplicate risk before erroring on the
    # constraint.
    db.add(
        models.SuggestionDismissal(
            project_id=project.id,
            historical_risk_key=risk_id,
            reason=ACCEPTED_REASON,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Lost a concurrent acceptance race: the other request committed the
        # processed marker and its risk first. Roll back our partial risk and
        # return the winner's risk instead of creating a duplicate.
        db.rollback()
        winner = _existing_accepted_risk(db, project, source)
        if winner is not None:
            return winner
        raise ValueError(
            "This suggested risk has already been processed for this register."
        ) from None
    db.refresh(risk)

    accepted = accept_risk(db, risk, actor_user_id=actor_user_id)
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
