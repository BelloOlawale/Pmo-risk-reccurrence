import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import type { Me, ResponseStrategy, Risk, RiskAuditLog, RiskSource } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { RatingBadge, SectionCard, StatusBadge } from '../components/Badges';
import { useApi } from '../hooks/useApi';
import { allowedTransitions } from '../utils/status';
import {
  computeRiskEndDate,
  computeRiskRating,
  countdownState,
  formatDate,
  formatDateTime,
  todayISO,
} from '../utils/format';

interface EditForm {
  description: string;
  category: string;
  subcategory: string;
  risk_source: string;
  likelihood: string;
  impact: string;
  response_strategy: string;
  response_plan: string;
  owner_user_id: string;
  risk_start_date: string;
  identified_during: string;
}

const EMPTY_FORM: EditForm = {
  description: '',
  category: '',
  subcategory: '',
  risk_source: '',
  likelihood: 'Medium',
  impact: 'Medium',
  response_strategy: '',
  response_plan: '',
  owner_user_id: '',
  risk_start_date: '',
  identified_during: '',
};

function toForm(risk: Risk): EditForm {
  return {
    description: risk.description,
    category: risk.category ?? '',
    subcategory: risk.subcategory ?? '',
    risk_source: risk.risk_source ?? '',
    likelihood: risk.likelihood,
    impact: risk.impact,
    response_strategy: risk.response_strategy ?? '',
    response_plan: risk.response_plan ?? '',
    owner_user_id: risk.owner_user_id !== null ? String(risk.owner_user_id) : '',
    risk_start_date: risk.risk_start_date ?? '',
    identified_during: risk.identified_during ?? '',
  };
}

function actionLabel(action: string, field: string | null): string {
  switch (action) {
    case 'status_change':
      return 'Status changed';
    case 'acknowledge':
      return 'Acknowledged';
    case 'de_escalate':
      return 'De-escalated';
    case 'field_edit':
      return field ? `Edited ${humanizeField(field)}` : 'Edited';
    default:
      return action;
  }
}

function humanizeField(field: string): string {
  return field.replace(/_/g, ' ');
}

function fmtValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function RiskDetailPage() {
  const { riskId } = useParams();
  const [searchParams] = useSearchParams();
  const fromRiskHistory = searchParams.get('from') === 'risk-history';
  const auth = useAuth();
  const id = Number(riskId);

  const { data: risk, error, reload: reloadRisk } = useApi(
    () => api.get<Risk>(`/api/risks/${id}`),
    [id],
  );
  const { data: history, reload: reloadHistory } = useApi(
    () => api.get<RiskAuditLog[]>(`/api/risks/${id}/history`),
    [id],
  );
  const { data: me } = useApi(() => api.get<Me>('/api/me'), []);

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<EditForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [statusTarget, setStatusTarget] = useState('');
  const [confirmCloseOpen, setConfirmCloseOpen] = useState(false);

  const today = todayISO();
  const editRating = computeRiskRating(form.likelihood, form.impact);
  const editEndDate = computeRiskEndDate(form.risk_start_date, editRating);

  useEffect(() => {
    if (risk && !editing) {
      setForm(toForm(risk));
      setStatusTarget('');
    }
  }, [risk, editing]);

  if (!Number.isFinite(id) || id <= 0) {
    return <div className="error-banner">Invalid risk id.</div>;
  }

  async function runAction(fn: () => Promise<unknown>) {
    setActionError(null);
    try {
      await fn();
      reloadRisk();
      reloadHistory();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (form.risk_start_date && form.risk_start_date < today) {
      setActionError('Risk start date cannot be in the past.');
      return;
    }
    setSaving(true);
    setActionError(null);
    try {
      await api.patch<Risk>(`/api/risks/${id}`, {
        description: form.description,
        category: form.category || null,
        subcategory: form.subcategory || null,
        risk_source: (form.risk_source || null) as RiskSource | null,
        likelihood: form.likelihood,
        impact: form.impact,
        response_strategy: (form.response_strategy || null) as ResponseStrategy | null,
        response_plan: form.response_plan || null,
        owner_user_id: form.owner_user_id === '' ? null : Number(form.owner_user_id),
        risk_start_date: form.risk_start_date || null,
        identified_during: form.identified_during || null,
        actor_user_id: auth.userId,
      });
      setEditing(false);
      reloadRisk();
      reloadHistory();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function applyStatus(target: string) {
    await runAction(() => api.patch<Risk>(`/api/risks/${id}`, { status: target, actor_user_id: auth.userId }));
  }

  /** Apply the selected status; transitions to Closed need explicit confirmation. */
  async function handleApplyStatus() {
    if (!statusTarget) return;
    if (statusTarget === 'Closed') {
      setConfirmCloseOpen(true);
      return;
    }
    await applyStatus(statusTarget);
  }

  function dismiss() {
    void runAction(() =>
      api.post<Risk>(`/api/risks/${id}/dismiss`, { reason: null, actor_user_id: auth.userId }),
    );
  }

  function deEscalate() {
    const rationale = window.prompt('Rationale for de-escalation (required):');
    if (rationale) {
      void runAction(() =>
        api.post<Risk>(`/api/risks/${id}/de-escalate`, {
          rationale,
          actor_user_id: auth.userId,
        }),
      );
    }
  }

  const readOnly = risk?.status === 'Closed' || risk?.status === 'Dismissed';
  const transitions = risk ? allowedTransitions(risk.status) : [];
  // PMO Lead has the final authority to close a risk; System Admin is the app
  // superuser. Everyone else sees the lifecycle without the Closed transition
  // (the backend enforces the same rule regardless of what the UI shows).
  const canCloseRisk = (me?.roles ?? []).some(
    (role) => role === 'PMO Lead' || role === 'System Admin',
  );
  const statusOptions = canCloseRisk
    ? transitions
    : transitions.filter((t) => t !== 'Closed');
  const awaitingPmoClosure =
    risk?.status === 'Resolved' && statusOptions.length === 0;

  return (
    <div>
      <div className="page-header">
        <div>
          <Link
            to={
              fromRiskHistory
                ? `/risk-history/${risk?.project_id ?? ''}`
                : `/active-risk/${risk?.project_id ?? ''}`
            }
            className="muted"
          >
            {fromRiskHistory ? '← Back to Risk History' : '← Back to Active Risk'}
          </Link>
          <h1 style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="mono">{risk?.risk_code ?? 'Risk'}</span>
            {risk ? <StatusBadge status={risk.status} /> : null}
            {risk ? <RatingBadge rating={risk.risk_rating} /> : null}
          </h1>
        </div>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}
      {actionError ? <div className="error-banner">{actionError}</div> : null}

      {risk ? (
        <>
          <div className="btn-group mb-20">
            {!risk.sla_acknowledged && risk.sla_deadline ? (
              <button
                className="btn btn-primary"
                onClick={() =>
                  runAction(() => api.post<Risk>(`/api/risks/${id}/acknowledge`))
                }
              >
                Acknowledge
              </button>
            ) : null}
            {risk.status === 'Suggested' ? (
              <>
                <button
                  className="btn btn-primary"
                  onClick={() => runAction(() => api.post<Risk>(`/api/risks/${id}/accept`))}
                >
                  Accept
                </button>
                <button className="btn btn-danger" onClick={dismiss}>
                  Dismiss
                </button>
              </>
            ) : null}
            {risk.status === 'Escalated' ? (
              <button className="btn" onClick={deEscalate}>
                De-escalate
              </button>
            ) : null}
            {!readOnly ? (
              <button className="btn" onClick={() => setEditing((e) => !e)}>
                {editing ? 'Cancel edit' : 'Edit details'}
              </button>
            ) : null}
          </div>

          <div className="detail-grid">
            <div className="stack">
              <SectionCard title="Description">
                <p className="mt-0">{risk.description}</p>
                {risk.llm_analysis ? (
                  <div className="muted" style={{ whiteSpace: 'pre-wrap' }}>
                    {risk.llm_analysis}
                  </div>
                ) : null}
              </SectionCard>

              {editing ? (
                <SectionCard title="Edit risk">
                  <form onSubmit={handleSave}>
                    <div className="form-grid">
                      <div className="field" style={{ gridColumn: '1 / -1' }}>
                        <label>Description</label>
                        <textarea
                          value={form.description}
                          onChange={(e) => setForm({ ...form, description: e.target.value })}
                        />
                      </div>
                      <div className="field">
                        <label>Category</label>
                        <input
                          value={form.category}
                          onChange={(e) => setForm({ ...form, category: e.target.value })}
                        />
                      </div>
                      <div className="field">
                        <label>Subcategory</label>
                        <input
                          value={form.subcategory}
                          onChange={(e) => setForm({ ...form, subcategory: e.target.value })}
                        />
                      </div>
                      <div className="field">
                        <label>Risk source</label>
                        <select
                          value={form.risk_source}
                          onChange={(e) => setForm({ ...form, risk_source: e.target.value })}
                        >
                          <option value="">—</option>
                          <option value="Human">Human</option>
                          <option value="Environmental">Environmental</option>
                          <option value="Technical">Technical</option>
                        </select>
                      </div>
                      <div className="field">
                        <label>Likelihood</label>
                        <select
                          value={form.likelihood}
                          onChange={(e) => setForm({ ...form, likelihood: e.target.value })}
                        >
                          <option value="Low">Low</option>
                          <option value="Medium">Medium</option>
                          <option value="High">High</option>
                        </select>
                      </div>
                      <div className="field">
                        <label>Impact</label>
                        <select
                          value={form.impact}
                          onChange={(e) => setForm({ ...form, impact: e.target.value })}
                        >
                          <option value="Low">Low</option>
                          <option value="Medium">Medium</option>
                          <option value="High">High</option>
                        </select>
                      </div>
                      <div className="field">
                        <label>Response strategy</label>
                        <select
                          value={form.response_strategy}
                          onChange={(e) => setForm({ ...form, response_strategy: e.target.value })}
                        >
                          <option value="">—</option>
                          <option value="Mitigate">Mitigate</option>
                          <option value="Transfer">Transfer</option>
                          <option value="Avoid">Avoid</option>
                          <option value="Accept">Accept</option>
                        </select>
                      </div>
                      <div className="field" style={{ gridColumn: '1 / -1' }}>
                        <label>Response plan</label>
                        <textarea
                          value={form.response_plan}
                          onChange={(e) => setForm({ ...form, response_plan: e.target.value })}
                        />
                      </div>
                      <div className="field">
                        <label>Owner user ID</label>
                        <input
                          type="number"
                          value={form.owner_user_id}
                          onChange={(e) => setForm({ ...form, owner_user_id: e.target.value })}
                        />
                      </div>
                      <div className="field">
                        <label>Risk start date</label>
                        <input
                          type="date"
                          min={today}
                          value={form.risk_start_date}
                          onChange={(e) => setForm({ ...form, risk_start_date: e.target.value })}
                        />
                      </div>
                      <div className="field">
                        <label>Risk end date</label>
                        <input
                          type="date"
                          value={editEndDate ?? ''}
                          readOnly
                          disabled
                          title="Automatically calculated based on risk rating and SLA."
                        />
                        <span className="field-hint">
                          Automatically calculated based on risk rating and SLA.
                        </span>
                      </div>
                      <div className="field">
                        <label>Project life cycle</label>
                        <input
                          value={form.identified_during}
                          onChange={(e) => setForm({ ...form, identified_during: e.target.value })}
                          placeholder="e.g. Execution, Discovery…"
                        />
                      </div>
                    </div>
                    <div className="btn-group">
                      <button className="btn btn-primary" type="submit" disabled={saving}>
                        {saving ? 'Saving…' : 'Save changes'}
                      </button>
                    </div>
                  </form>
                </SectionCard>
              ) : (
                <SectionCard title="Details">
                  <div className="key-value">
                    <div>
                      <div className="kv-label">Category</div>
                      <div className="kv-value">{risk.category ?? '—'}</div>
                    </div>
                    <div>
                      <div className="kv-label">Subcategory</div>
                      <div className="kv-value">{risk.subcategory ?? '—'}</div>
                    </div>
                    <div>
                      <div className="kv-label">Risk source</div>
                      <div className="kv-value">{risk.risk_source ?? '—'}</div>
                    </div>
                    <div>
                      <div className="kv-label">Likelihood</div>
                      <div className="kv-value">{risk.likelihood}</div>
                    </div>
                    <div>
                      <div className="kv-label">Impact</div>
                      <div className="kv-value">{risk.impact}</div>
                    </div>
                    <div>
                      <div className="kv-label">Response strategy</div>
                      <div className="kv-value">{risk.response_strategy ?? '—'}</div>
                    </div>
                    <div>
                      <div className="kv-label">Owner</div>
                      <div className="kv-value">
                        {risk.owner_user_id !== null ? `User #${risk.owner_user_id}` : '—'}
                      </div>
                    </div>
                    <div>
                      <div className="kv-label">Source</div>
                      <div className="kv-value">{risk.source ?? '—'}</div>
                    </div>
                    <div>
                      <div className="kv-label">Raised by</div>
                      <div className="kv-value">{risk.raised_by ?? '—'}</div>
                    </div>
                    <div>
                      <div className="kv-label">Identified during</div>
                      <div className="kv-value">{risk.identified_during ?? '—'}</div>
                    </div>
                    <div>
                      <div className="kv-label">Risk start</div>
                      <div className="kv-value">{formatDate(risk.risk_start_date)}</div>
                    </div>
                    <div>
                      <div className="kv-label">Risk end</div>
                      <div className="kv-value">{formatDate(risk.risk_end_date)}</div>
                    </div>
                    <div>
                      <div className="kv-label">SLA status</div>
                      <div className="kv-value">
                        <span className={`tone-${countdownState(risk).tone}`}>
                          {countdownState(risk).label}
                        </span>
                      </div>
                    </div>
                    <div>
                      <div className="kv-label">Created</div>
                      <div className="kv-value">{formatDateTime(risk.created_at)}</div>
                    </div>
                  </div>

                  {risk.response_plan ? (
                    <div className="mt-20">
                      <div className="kv-label">Response plan</div>
                      <div className="kv-value">{risk.response_plan}</div>
                    </div>
                  ) : null}

                  {risk.root_cause ? (
                    <div className="mt-20">
                      <div className="kv-label">Root cause</div>
                      <div className="kv-value">{risk.root_cause}</div>
                    </div>
                  ) : null}

                  {risk.what_worked ? (
                    <div className="mt-20">
                      <div className="kv-label">What worked</div>
                      <div className="kv-value">{risk.what_worked}</div>
                    </div>
                  ) : null}
                </SectionCard>
              )}
            </div>

            <div className="stack">
              {risk.source_file_url || risk.source_file_name ? (
                <SectionCard title="Source file">
                  <div className="kv-label">Original register</div>
                  <div className="kv-value">
                    {risk.source_file_url ? (
                      <a href={risk.source_file_url} target="_blank" rel="noreferrer">
                        {risk.source_file_name ?? risk.source_file_url}
                      </a>
                    ) : (
                      risk.source_file_name
                    )}
                  </div>
                  {risk.source_risk_id ? (
                    <div className="mt-20">
                      <div className="kv-label">Source risk ID</div>
                      <div className="kv-value mono">{risk.source_risk_id}</div>
                    </div>
                  ) : null}
                </SectionCard>
              ) : null}

              {statusOptions.length > 0 || awaitingPmoClosure ? (
                <SectionCard title="Change status">
                  {statusOptions.length > 0 ? (
                    <>
                      <div className="field">
                        <select
                          value={statusTarget}
                          onChange={(e) => setStatusTarget(e.target.value)}
                        >
                          <option value="">Select next status…</option>
                          {statusOptions.map((t) => (
                            <option key={t} value={t}>
                              {t}
                            </option>
                          ))}
                        </select>
                      </div>
                      {statusTarget === 'Closed' ? (
                        <p className="muted">
                          Closing a risk is final — you will be asked to confirm.
                        </p>
                      ) : null}
                      <button
                        className="btn"
                        disabled={!statusTarget}
                        onClick={() => void handleApplyStatus()}
                      >
                        Apply
                      </button>
                    </>
                  ) : (
                    <p className="muted">
                      This risk is Resolved and ready to close. Only a PMO Lead can perform the
                      final closure to Closed.
                    </p>
                  )}
                </SectionCard>
              ) : null}

              <SectionCard title="Status history">
                {(history ?? []).length === 0 ? (
                  <div className="empty-state">No history recorded.</div>
                ) : (
                  <ul className="timeline">
                    {[...(history ?? [])]
                      .sort((a, b) => (a.id < b.id ? 1 : -1))
                      .map((entry) => (
                        <li key={entry.id} className={`timeline-item ${entry.action}`}>
                          <div className="timeline-title">
                            {actionLabel(entry.action, entry.field)}
                          </div>
                          <div className="timeline-meta">
                            {entry.user_id !== null ? `User #${entry.user_id} · ` : ''}
                            {formatDateTime(entry.created_at)}
                          </div>
                          {entry.field && (entry.action === 'field_edit' || entry.action === 'status_change') ? (
                            <div className="timeline-change">
                              {humanizeField(entry.field)}: {fmtValue(entry.old_value)} →{' '}
                              {fmtValue(entry.new_value)}
                            </div>
                          ) : null}
                        </li>
                      ))}
                  </ul>
                )}
              </SectionCard>
            </div>
          </div>
        </>
      ) : (
        !error && <div className="loading">Loading risk…</div>
      )}

      {confirmCloseOpen ? (
        <div className="modal-overlay" onClick={() => setConfirmCloseOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Close Risk?</h2>
              <button
                className="btn btn-sm"
                onClick={() => setConfirmCloseOpen(false)}
                aria-label="Close"
              >
                ✕
              </button>
            </div>
            <p>
              Are you sure you want to close this risk? Closing the risk indicates that the risk
              has been formally closed.
            </p>
            {actionError ? <div className="error-banner">{actionError}</div> : null}
            <div className="btn-group">
              <button className="btn" onClick={() => setConfirmCloseOpen(false)}>
                Cancel
              </button>
              <button
                className="btn btn-danger"
                onClick={() => {
                  setConfirmCloseOpen(false);
                  void applyStatus('Closed');
                }}
              >
                Close Risk
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
