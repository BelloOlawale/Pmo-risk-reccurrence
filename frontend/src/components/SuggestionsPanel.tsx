import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import { api, ApiError } from '../api/client';
import type { SuggestedRisk, SuggestionResult } from '../api/types';
import { RatingBadge, SectionCard } from './Badges';

interface SuggestionsPanelProps {
  projectId: number;
  /** Called after any accept/dismiss so the parent can refresh the register preview. */
  onChanged?: () => void;
}

/** Matches the Markdown links the backend `linkify` step writes for citations. */
const LINK_RE = /\[([^\]]+)\]\(([^)]+)\)/g;

/** Render text, turning `[label](url)` citations into real links. */
function LinkedText({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(LINK_RE)) {
    const index = match.index ?? 0;
    if (index > last) parts.push(text.slice(last, index));
    parts.push(
      <a key={`${index}-${match[1]}`} href={match[2]} target="_blank" rel="noreferrer">
        {match[1]}
      </a>,
    );
    last = index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

/**
 * Suggested recurring risks for a project (from historical data). Accepting a
 * suggestion creates an Open risk in the register and immediately removes the
 * suggestion from the available list; dismissing it excludes it from future
 * suggestions for this project.
 *
 * The list comes from the single `POST /suggest` endpoint: one candidate
 * pipeline (exact + keyword retrieval, with best-effort semantic matching)
 * followed by a best-effort GPT risk-landscape analysis. When an AI layer is
 * unavailable the backend still returns the same shape and reports it via
 * `evaluation`, which the panel surfaces as a banner.
 *
 * Only the information a PMO manager needs to review a suggestion is shown:
 * description, rating and actions. Technical retrieval metadata (risk id,
 * match type, source file, similarity) stays internal.
 */
export function SuggestionsPanel({ projectId, onChanged }: SuggestionsPanelProps) {
  const [suggestions, setSuggestions] = useState<SuggestedRisk[]>([]);
  const [overview, setOverview] = useState<string | null>(null);
  const [recommendations, setRecommendations] = useState<string[]>([]);
  const [llmError, setLlmError] = useState<string | null>(null);
  const [semanticError, setSemanticError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const errMessage = (err: unknown) =>
    err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // One endpoint, one candidate pipeline: exact + keyword retrieval, with
      // semantic matching and GPT analysis applied best-effort. Degradation is
      // reported in `evaluation` rather than by failing the request, so there is
      // no second route to reconcile against.
      const result = await api.post<SuggestionResult>(`/api/projects/${projectId}/suggest`);
      setSuggestions(result.suggested_risks);
      setOverview(result.overview);
      setRecommendations(result.recommendations);
      setLlmError(result.evaluation.llm_error ?? null);
      setSemanticError(result.evaluation.semantic_error ?? null);
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const allSelected =
    suggestions.length > 0 && suggestions.every((s) => selected.has(s.risk_id));

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected((prev) => {
      if (prev.size === suggestions.length) return new Set();
      return new Set(suggestions.map((s) => s.risk_id));
    });
  }

  const notifyChanged = useCallback(() => onChanged?.(), [onChanged]);

  /**
   * Drop processed suggestions from the local list and the current selection.
   * Only ever called after the backend confirms the accept/dismiss succeeded,
   * so a failed request leaves the suggestion fully available for a retry.
   */
  const removeSuggestions = useCallback((ids: Iterable<string>) => {
    const gone = new Set(ids);
    setSuggestions((prev) => prev.filter((s) => !gone.has(s.risk_id)));
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of gone) next.delete(id);
      return next;
    });
  }, []);

  async function acceptOne(s: SuggestedRisk) {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/projects/${projectId}/suggestions/accept`, {
        risk_id: s.risk_id,
        analysis: s.analysis,
      });
      // Backend confirmed: the suggestion is now part of the register and can
      // never be accepted again — drop it from the available list immediately.
      removeSuggestions([s.risk_id]);
      notifyChanged();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function dismissOne(s: SuggestedRisk) {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/projects/${projectId}/suggestions/dismiss`, { risk_id: s.risk_id });
      removeSuggestions([s.risk_id]);
      notifyChanged();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function runMass(action: 'accept' | 'dismiss') {
    const rows = suggestions.filter((s) => selected.has(s.risk_id));
    if (rows.length === 0) return;
    setBusy(true);
    setError(null);
    // Process every selected row individually so one failure does not abort the
    // rest. Only the rows the backend confirms are removed; failed rows stay
    // visible and remain selected so the user can retry them.
    const succeeded: string[] = [];
    const failed: string[] = [];
    for (const s of rows) {
      try {
        if (action === 'accept') {
          await api.post(`/api/projects/${projectId}/suggestions/accept`, {
            risk_id: s.risk_id,
            analysis: s.analysis,
          });
        } else {
          await api.post(`/api/projects/${projectId}/suggestions/dismiss`, { risk_id: s.risk_id });
        }
        succeeded.push(s.risk_id);
      } catch {
        failed.push(s.risk_id);
      }
    }
    if (succeeded.length > 0) {
      removeSuggestions(succeeded);
      notifyChanged();
    }
    if (failed.length > 0) {
      setError(
        failed.length === rows.length
          ? `Could not ${action} the selected suggestion${rows.length > 1 ? 's' : ''}. Please try again.`
          : `${failed.length} of ${rows.length} suggestion${rows.length > 1 ? 's' : ''} could not be ${action}ed and remain selected. Please try again.`,
      );
    }
    setBusy(false);
  }

  const selectedCount = useMemo(
    () => suggestions.filter((s) => selected.has(s.risk_id)).length,
    [suggestions, selected],
  );

  const hasAnalysis = Boolean(overview) || recommendations.length > 0;

  return (
    <SectionCard
      title={`Suggested risks (${suggestions.length})`}
      collapsible={false}
      actions={
        <button className="btn btn-sm" onClick={() => void load()} disabled={loading || busy}>
          Refresh
        </button>
      }
    >
      {error ? <div className="error-banner">{error}</div> : null}
      {semanticError ? (
        <div className="info-banner">
          Similarity search is unavailable right now — showing keyword matches only.
        </div>
      ) : null}
      {llmError ? (
        <div className="error-banner">
          AI analysis could not be generated ({llmError}). Showing retrieval-only suggestions.
        </div>
      ) : null}
      {loading ? (
        <div className="loading">Analysing historical risks…</div>
      ) : (
        <>
          {hasAnalysis ? (
            <div className="suggestion-overview">
              {overview ? (
                <p className="suggestion-overview-text">
                  <LinkedText text={overview} />
                </p>
              ) : null}
              {recommendations.length > 0 ? (
                <ul className="suggestion-recommendations">
                  {recommendations.map((item, index) => (
                    <li key={index}>
                      <LinkedText text={item} />
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}

          {suggestions.length === 0 ? (
            <div className="empty-state">
              No suggested risks remain for this register. You can still add risks manually with
              “+ Add New”.
            </div>
          ) : (
            <>
              <div className="suggested-mass-bar">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleAll}
                    disabled={busy}
                  />{' '}
                  Select All
                </label>
                <span className="muted">{selectedCount} selected</span>
                <div className="btn-group">
                  <button
                    className="btn btn-sm btn-primary"
                    disabled={busy || selectedCount === 0}
                    onClick={() => void runMass('accept')}
                  >
                    ✓ Accept Selected
                  </button>
                  <button
                    className="btn btn-sm btn-danger"
                    disabled={busy || selectedCount === 0}
                    onClick={() => void runMass('dismiss')}
                  >
                    ✕ Dismiss Selected
                  </button>
                </div>
              </div>
              <div className="table-wrap">
                <table className="suggested-table">
                  <thead>
                    <tr>
                      <th className="suggested-check-col" aria-label="Select"></th>
                      <th className="suggested-desc-col">Risk Description</th>
                      <th className="suggested-rating-col">Risk Rating</th>
                      <th className="suggested-actions-col">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {suggestions.map((s) => (
                      <tr
                        key={s.risk_id}
                        className={selected.has(s.risk_id) ? 'row-selected' : undefined}
                      >
                        <td className="suggested-check-cell">
                          <input
                            type="checkbox"
                            checked={selected.has(s.risk_id)}
                            onChange={() => toggle(s.risk_id)}
                            disabled={busy}
                            aria-label={`Select ${s.description}`}
                          />
                        </td>
                        <td className="suggested-desc-cell">
                          <span className="suggested-desc" title={s.description}>
                            {s.description}
                          </span>
                          {s.analysis ? (
                            <span className="suggested-analysis">
                              <LinkedText text={s.analysis} />
                            </span>
                          ) : null}
                        </td>
                        <td className="suggested-rating-cell">
                          {s.risk_rating ? (
                            <RatingBadge rating={s.risk_rating} />
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td className="suggested-actions-cell">
                          <div className="icon-actions">
                            <button
                              className="icon-btn icon-btn-accept"
                              disabled={busy}
                              onClick={() => void acceptOne(s)}
                              aria-label="Accept risk"
                              title="Accept risk"
                            >
                              <svg
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="2.5"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                              >
                                <path d="M20 6 9 17l-5-5" />
                              </svg>
                            </button>
                            <button
                              className="icon-btn icon-btn-dismiss"
                              disabled={busy}
                              onClick={() => void dismissOne(s)}
                              aria-label="Dismiss risk"
                              title="Dismiss risk"
                            >
                              <svg
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="2.5"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                              >
                                <path d="M18 6 6 18M6 6l12 12" />
                              </svg>
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </SectionCard>
  );
}
