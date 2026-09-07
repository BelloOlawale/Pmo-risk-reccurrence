import { useCallback, useEffect, useMemo, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { SuggestedRisk } from '../api/types';
import { RatingBadge, SectionCard } from './Badges';

interface SuggestionsPanelProps {
  projectId: number;
  /** Called after any accept/dismiss so the parent can refresh the register preview. */
  onChanged?: () => void;
}

/**
 * Suggested recurring risks for a project (from historical data). Accepting a
 * suggestion creates an Open risk in the register; dismissing excludes it from
 * future suggestions for this project.
 *
 * Only the information a PMO manager needs to review a suggestion is shown:
 * description, rating and actions. Technical retrieval metadata (risk id,
 * match type, source file, similarity) stays internal.
 */
export function SuggestionsPanel({ projectId, onChanged }: SuggestionsPanelProps) {
  const [suggestions, setSuggestions] = useState<SuggestedRisk[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSuggestions(await api.get<SuggestedRisk[]>(`/api/projects/${projectId}/suggestions`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
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

  async function acceptOne(s: SuggestedRisk) {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/projects/${projectId}/suggestions/accept`, { risk_id: s.risk_id });
      setSelected((prev) => {
        const next = new Set(prev);
        next.delete(s.risk_id);
        return next;
      });
      notifyChanged();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function dismissOne(s: SuggestedRisk) {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/projects/${projectId}/suggestions/dismiss`, { risk_id: s.risk_id });
      setSelected((prev) => {
        const next = new Set(prev);
        next.delete(s.risk_id);
        return next;
      });
      notifyChanged();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function runMass(action: 'accept' | 'dismiss') {
    const ids = suggestions.filter((s) => selected.has(s.risk_id)).map((s) => s.risk_id);
    if (ids.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      for (const id of ids) {
        if (action === 'accept') {
          await api.post(`/api/projects/${projectId}/suggestions/accept`, { risk_id: id });
        } else {
          await api.post(`/api/projects/${projectId}/suggestions/dismiss`, { risk_id: id });
        }
      }
      setSelected(new Set());
      notifyChanged();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const selectedCount = useMemo(
    () => suggestions.filter((s) => selected.has(s.risk_id)).length,
    [suggestions, selected],
  );

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
      {loading ? (
        <div className="loading">Loading suggestions…</div>
      ) : suggestions.length === 0 ? (
        <div className="empty-state">
          No recurring risks to suggest for this project. You can still add risks manually with
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
            <span className="muted">
              {selectedCount} selected
            </span>
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
                  <tr key={s.risk_id} className={selected.has(s.risk_id) ? 'row-selected' : undefined}>
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
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
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
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
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
    </SectionCard>
  );
}
