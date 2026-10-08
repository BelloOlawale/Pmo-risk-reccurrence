import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import type { ExternalAcknowledge } from '../api/types';
import { RatingBadge, StatusBadge } from '../components/Badges';
import { formatDate, formatDateTime } from '../utils/format';

const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? '';

/** Shown for bad or revoked links — leaks nothing internal. */
const LINK_INVALID_MESSAGE = 'This risk link is not valid or is no longer available.';

/**
 * Public, token-scoped page for an external Risk Owner.
 *
 * The secure, persistent token in the URL grants access to exactly one risk,
 * so this page deliberately uses a bare `fetch` (no session/auth headers) and is
 * mounted outside the application shell — an external owner has no Wragby
 * account and must never reach the internal app. The link does not expire while
 * the risk stays assigned to this owner, so they can acknowledge, resolve, and
 * act again if the Project Manager sends the resolution back.
 */
export function ExternalAcknowledgePage() {
  const { token } = useParams();
  const [risk, setRisk] = useState<ExternalAcknowledge | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [acknowledging, setAcknowledging] = useState(false);
  const [resolving, setResolving] = useState(false);

  const load = useCallback(async () => {
    if (!token) {
      setError(LINK_INVALID_MESSAGE);
      setLoading(false);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/external/acknowledge/${token}`);
      if (!res.ok) {
        throw new Error(LINK_INVALID_MESSAGE);
      }
      setRisk((await res.json()) as ExternalAcknowledge);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  async function acknowledge() {
    if (!token) return;
    setAcknowledging(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/external/acknowledge/${token}`, {
        method: 'POST',
      });
      if (!res.ok) {
        throw new Error('We could not record your acknowledgement. Please try again.');
      }
      setRisk((await res.json()) as ExternalAcknowledge);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAcknowledging(false);
    }
  }

  async function resolve() {
    if (!token) return;
    setResolving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/external/acknowledge/${token}/resolve`, {
        method: 'POST',
      });
      if (!res.ok) {
        throw new Error('We could not submit your resolution. Please try again.');
      }
      setRisk((await res.json()) as ExternalAcknowledge);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setResolving(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-accent-bar" aria-hidden="true" />

      <header className="auth-brand">
        <img className="auth-logo" src="/wragby-logo.png" alt="Wragby" />
        <div className="auth-brand-rule" aria-hidden="true" />
        <h1 className="auth-product-name">
          <span className="brand-wragby">WRAGBY</span>{' '}
          <span className="brand-intell">RiskIntel</span>
        </h1>
        <p className="auth-product-subtitle">PMO Risk Management</p>
      </header>

      <main className="auth-main">
        <section className="auth-card" aria-labelledby="ack-heading">
          <h2 id="ack-heading" className="auth-card-heading">
            Risk acknowledgement
          </h2>

          {loading ? <p className="muted">Loading the assigned risk…</p> : null}
          {error && !risk ? (
            <div className="ack-invalid">
              <div className="auth-error">{error}</div>
              <p className="muted">
                If you believe you should still have access to this risk, please contact the
                project or risk manager who assigned it to you.
              </p>
            </div>
          ) : null}

          {risk ? (
            <div className="ack-panel">
              <div className="ack-headline">
                <span className="mono">{risk.risk_code}</span>
                <RatingBadge rating={risk.risk_rating} />
                <StatusBadge status={risk.status} />
              </div>
              <p className="ack-description">{risk.description}</p>

              <div className="key-value">
                <div>
                  <div className="kv-label">Project</div>
                  <div className="kv-value">{risk.project_name}</div>
                </div>
                <div>
                  <div className="kv-label">Severity</div>
                  <div className="kv-value">{risk.risk_rating}</div>
                </div>
                <div>
                  <div className="kv-label">Category</div>
                  <div className="kv-value">{risk.category ?? '—'}</div>
                </div>
                <div>
                  <div className="kv-label">Response strategy</div>
                  <div className="kv-value">{risk.response_strategy ?? '—'}</div>
                </div>
                <div>
                  <div className="kv-label">Risk start</div>
                  <div className="kv-value">{formatDate(risk.risk_start_date)}</div>
                </div>
                <div>
                  <div className="kv-label">SLA deadline</div>
                  <div className="kv-value">{formatDateTime(risk.sla_deadline)}</div>
                </div>
                <div>
                  <div className="kv-label">Assigned to</div>
                  <div className="kv-value">
                    {risk.owner_name}
                    <div className="muted owner-email">{risk.owner_email}</div>
                  </div>
                </div>
                {risk.project_manager ? (
                  <div>
                    <div className="kv-label">Project Manager</div>
                    <div className="kv-value">{risk.project_manager}</div>
                  </div>
                ) : null}
                <div>
                  <div className="kv-label">Your acknowledgement</div>
                  <div className="kv-value">
                    {risk.acknowledged ? 'Acknowledged' : 'Not yet acknowledged'}
                  </div>
                </div>
                <div>
                  <div className="kv-label">Current status</div>
                  <div className="kv-value">{risk.status}</div>
                </div>
              </div>

              {risk.response_plan ? (
                <div className="mt-20">
                  <div className="kv-label">Response plan</div>
                  <div className="kv-value">{risk.response_plan}</div>
                </div>
              ) : null}

              {error ? <div className="auth-error">{error}</div> : null}

              {risk.resolution_rejected_reason && risk.status === 'In Progress' ? (
                <div className="auth-error" role="alert">
                  <strong>Your previous resolution was rejected by the Project Manager.</strong>{' '}
                  Reason: {risk.resolution_rejected_reason}
                </div>
              ) : null}

              {!risk.acknowledged ? (
                <button
                  type="button"
                  className="btn btn-primary auth-primary-btn"
                  disabled={acknowledging}
                  onClick={() => void acknowledge()}
                >
                  {acknowledging ? 'Acknowledging…' : 'Acknowledge Risk'}
                </button>
              ) : risk.status === 'Pending Resolution' ? (
                <div className="ack-confirmed">
                  <strong>Resolution submitted.</strong> Awaiting Project Manager review.
                  Thank you — you can close this page.
                </div>
              ) : risk.status === 'Resolved' ? (
                <div className="ack-confirmed">
                  <strong>Resolution accepted.</strong> The Project Manager has approved your
                  resolution. No further action is required.
                </div>
              ) : risk.status === 'Closed' ? (
                <div className="ack-confirmed">
                  <strong>This risk is closed.</strong> No further action is required.
                </div>
              ) : risk.status === 'Dismissed' ? (
                <div className="ack-confirmed">
                  <strong>This risk was dismissed.</strong> No further action is required.
                </div>
              ) : (
                <>
                  <div className="ack-confirmed">
                    <strong>Acknowledged.</strong>{' '}
                    {risk.acknowledged_at
                      ? `Recorded ${formatDateTime(risk.acknowledged_at)}.`
                      : ''}{' '}
                    When the risk has been addressed, mark it as resolved for the Project
                    Manager to review.
                  </div>
                  <button
                    type="button"
                    className="btn btn-primary auth-primary-btn"
                    disabled={resolving}
                    onClick={() => void resolve()}
                  >
                    {resolving ? 'Submitting…' : 'Mark as Resolved'}
                  </button>
                </>
              )}
            </div>
          ) : null}
        </section>
      </main>

      <footer className="auth-footer">
        <span>© {new Date().getFullYear()} Wragby</span>
        <span className="auth-footer-dot" aria-hidden="true">
          •
        </span>
        <span>PMO Risk Management</span>
      </footer>
    </div>
  );
}
