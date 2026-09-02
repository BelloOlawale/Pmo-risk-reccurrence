import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { SuggestedRisk } from '../api/types';
import { RatingBadge, SectionCard } from './Badges';

interface SuggestionsPanelProps {
  projectId: number;
  onAccepted: () => void;
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
export function SuggestionsPanel({ projectId, onAccepted }: SuggestionsPanelProps) {
  const [suggestions, setSuggestions] = useState<SuggestedRisk[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

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

  async function accept(s: SuggestedRisk) {
    setBusyId(s.risk_id);
    setError(null);
    try {
      await api.post(`/api/projects/${projectId}/suggestions/accept`, { risk_id: s.risk_id });
      onAccepted();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function dismiss(s: SuggestedRisk) {
    const reason = window.prompt('Reason for dismissing this suggested risk (optional):');
    if (reason === null) return;
    setBusyId(s.risk_id);
    setError(null);
    try {
      await api.post(`/api/projects/${projectId}/suggestions/dismiss`, {
        risk_id: s.risk_id,
        reason: reason || null,
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <SectionCard
      title={`Suggested risks (${suggestions.length})`}
      collapsible
      actions={
        <button className="btn btn-sm" onClick={() => void load()} disabled={loading}>
          Refresh
        </button>
      }
    >
      {error ? <div className="error-banner">{error}</div> : null}
      {loading ? (
        <div className="loading">Loading suggestions…</div>
      ) : suggestions.length === 0 ? (
        <div className="empty-state">
          No recurring risks to suggest for this project. Accepting/dismissing happens here once
          historical matches are found.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="suggested-table">
            <thead>
              <tr>
                <th className="suggested-desc-col">Risk Description</th>
                <th className="suggested-rating-col">Risk Rating</th>
                <th className="suggested-actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {suggestions.map((s) => (
                <tr key={s.risk_id}>
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
                    <div className="btn-group suggested-actions">
                      <button
                        className="btn btn-primary btn-sm"
                        disabled={busyId === s.risk_id}
                        onClick={() => void accept(s)}
                      >
                        Accept
                      </button>
                      <button
                        className="btn btn-danger btn-sm"
                        disabled={busyId === s.risk_id}
                        onClick={() => void dismiss(s)}
                      >
                        Dismiss
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}
