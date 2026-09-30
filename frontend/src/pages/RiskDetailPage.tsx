import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type { Issue, Me, Risk, RiskAuditLog, RiskSource } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { ownerName, useUsers } from '../api/users';
import { RatingBadge, SectionCard, StatusBadge } from '../components/Badges';
import { UserPicker } from '../components/UserPicker';
import { useApi } from '../hooks/useApi';
import { allowedTransitions } from '../utils/status';
import { countdownState, formatDate, formatDateTime } from '../utils/format';

interface EditForm {
  description: string;
  category: string;
  risk_source: string;
  likelihood: string;
  impact: string;
  response_strategy: string;
  response_plan: string;
  owner_user_id: string;
  risk_start_date: string;
  risk_end_date: string;
  identified_during: string;
}

const EMPTY_FORM: EditForm = {
  description: '',
  category: '',
  risk_source: '',
  likelihood: 'Medium',
  impact: 'Medium',
  response_strategy: '',
  response_plan: '',
  owner_user_id: '',
  risk_start_date: '',
  risk_end_date: '',
  identified_during: '',
};

function toForm(risk: Risk): EditForm {
  return {
    description: risk.description,
    category: risk.category ?? '',
    risk_source: risk.risk_source ?? '',
    likelihood: risk.likelihood,
    impact: risk.impact,
    response_strategy: risk.response_strategy ?? '',
    response_plan: risk.response_plan ?? '',
    owner_user_id: risk.owner_user_id !== null ? String(risk.owner_user_id) : '',
    risk_start_date: risk.risk_start_date ?? '',
    risk_end_date: risk.risk_end_date ?? '',
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
    case 'issue_created':
      return 'Issue created';
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

/** Banner shown on a materialized (Event) risk, linking to its single Issue. */
function MaterializedIssueCard({ riskId, from }: { riskId: number; from: string }) {
  const [issue, setIssue] = useState<Issue | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'pending'>('loading');

  useEffect(() => {
    let cancelled = false;
    setState('loading');
    api
      .get<Issue>(`/api/risks/${riskId}/issue`)
      .then((data) => {
        if (!cancelled) {
          setIssue(data);
          setState('ready');
        }
      })
      .catch((err: unknown) => {
        // 404 = Event risk whose Issue the automation has not generated yet
        // (e.g. just transitioned manually before the next scheduler run).
        if (!cancelled && !(err instanceof ApiError && err.status === 404)) {
          setIssue(null);
        }
        if (!cancelled) setState('pending');
      });
    return () => {
      cancelled = true;
    };
  }, [riskId]);

  if (state === 'loading') return null;
  if (issue) {
    return (
      <div className="materialized-banner">
        <div className="materialized-banner-main">
          <strong>This risk has materialized.</strong>{' '}
          <span>
            It passed its Risk End Date without being resolved. Issue{' '}
            <span className="mono">{issue.issue_code}</span> was created from this risk.
          </span>
        </div>
        <Link className="btn btn-sm btn-primary" to={`/issues/${issue.id}?from=${from}`}>
          View Issue {issue.issue_code}
        </Link>
      </div>
    );
  }
  return (
    <div className="materialized-banner">
      <strong>This risk has materialized.</strong>{' '}
      <span>An Issue will be generated automatically on the next scheduler run.</span>
    </div>
  );
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
  const users = useUsers();

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<EditForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [statusTarget, setStatusTarget] = useState('');
  const [confirmCloseOpen, setConfirmCloseOpen] = useState(false);

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
    if (
      form.risk_start_date &&
      form.risk_end_date &&
      form.risk_end_date < form.risk_start_date
    ) {
      setActionError('Risk end date cannot be earlier than the risk start date.');
      return;
    }
    setSaving(true);
    setActionError(null);
    try {
      // Likelihood, Impact, Category, Response Strategy and Project Lifecycle
      // are fixed at creation; only the still-editable fields are sent.
      await api.patch<Risk>(`/api/risks/${id}`, {
        description: form.description,
        risk_source: (form.risk_source || null) as RiskSource | null,
        response_plan: form.response_plan || null,
        owner_user_id: form.owner_user_id === '' ? null : Number(form.owner_user_id),
        risk_start_date: form.risk_start_date || null,
        risk_end_date: form.risk_end_date || null,
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
    (role) =>
      role === 'Project Manager' || role === 'PMO Lead' || role === 'System Admin',
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

      {risk?.status === 'Event' ? (
        <MaterializedIssueCard
          riskId={risk.id}
          from={fromRiskHistory ? 'risk-history' : 'active-risk'}
        />
      ) : null}

      {risk ? (
        <>
          <div className="btn-group mb-20">
            {risk.owner_user_id !== null && !risk.sla_acknowledged ? (
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
                    <p className="muted" style={{ marginTop: 0 }}>
                      Likelihood, Impact, Category, Response strategy and Project life cycle are
                      fixed when the risk is created and cannot be edited here.
                    </p>
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
                        <div className="readonly-field">{form.category || '—'}</div>
                      </div>
                      <div className="field">
                        <label>Likelihood</label>
                        <div className="readonly-field">{form.likelihood}</div>
                      </div>
                      <div className="field">
                        <label>Impact</label>
                        <div className="readonly-field">{form.impact}</div>
                      </div>
                      <div className="field">
                        <label>Response strategy</label>
                        <div className="readonly-field">{form.response_strategy || '—'}</div>
                      </div>
                      <div className="field">
                        <label>Project life cycle</label>
                        <div className="readonly-field">{form.identified_during || '—'}</div>
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
                      <div className="field" style={{ gridColumn: '1 / -1' }}>
                        <label>Response plan</label>
                        <textarea
                          value={form.response_plan}
                          onChange={(e) => setForm({ ...form, response_plan: e.target.value })}
                        />
                      </div>
                      <div className="field">
                        <label>Owner</label>
                        <UserPicker
                          users={users}
                          includeExternal
                          selectedUserId={
                            form.owner_user_id === '' ? null : Number(form.owner_user_id)
                          }
                          onSelect={(user) =>
                            setForm({
                              ...form,
                              owner_user_id: user === null ? '' : String(user.id),
                            })
                          }
                        />
                      </div>
                      <div className="field">
                        <label>Risk start date</label>
                        <input
                          type="date"
                          value={form.risk_start_date}
                          onChange={(e) => setForm({ ...form, risk_start_date: e.target.value })}
                        />
                      </div>
                      <div className="field">
                        <label>Risk end date</label>
                        <input
                          type="date"
                          value={form.risk_end_date}
                          onChange={(e) => setForm({ ...form, risk_end_date: e.target.value })}
                        />
                        <span className="field-hint">
                          The risk end date is the SLA deadline.
                        </span>
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
                        <span className="owner-cell">
                          {risk.owner_name ?? 'Unassigned'}
                          {risk.owner_type === 'External' ? (
                            <span className="owner-type-tag">External</span>
                          ) : null}
                        </span>
                        {risk.owner_email ? (
                          <div className="muted owner-email">{risk.owner_email}</div>
                        ) : null}
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
                      This risk is Resolved and ready to close. You do not have permission to
                      close it.
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
                            {entry.user_id !== null ? `${ownerName(users, entry.user_id)} · ` : ''}
                            {formatDateTime(entry.created_at)}
                          </div>
                          {entry.field &&
                          (entry.action === 'field_edit' ||
                            entry.action === 'status_change' ||
                            entry.action === 'issue_created') ? (
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
