import { useState } from 'react';
import type { FormEvent } from 'react';

import { api, ApiError } from '../api/client';
import type { Project, ResponseStrategy, Risk, RiskMeta, RiskSource } from '../api/types';
import { useUsers } from '../api/users';
import { useApi } from '../hooks/useApi';
import { PickOrTypeField } from './PickOrTypeField';
import { UserPicker } from './UserPicker';

interface AddRiskModalProps {
  projects: Project[];
  /** Pre-select this project when the modal opens (e.g. quick-add from a project). */
  initialProjectId?: number;
  onClose: () => void;
  onCreated: (risk: Risk) => void;
}

interface FormState {
  project_id: string;
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

const EMPTY: FormState = {
  project_id: '',
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

export function AddRiskModal({ projects, initialProjectId, onClose, onCreated }: AddRiskModalProps) {
  const [form, setForm] = useState<FormState>(() => ({
    ...EMPTY,
    project_id: initialProjectId !== undefined ? String(initialProjectId) : '',
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { data: meta } = useApi(() => api.get<RiskMeta>('/api/risk-meta'), []);
  const users = useUsers();
  const categoryOptions = meta?.categories ?? [];
  const lifecycleOptions = meta?.lifecycle ?? [];

  // When the modal is opened from a register, the project is fixed to that
  // register — Quick Add can never place the risk elsewhere.
  const fixedProject =
    initialProjectId !== undefined
      ? projects.find((p) => p.id === initialProjectId) ?? null
      : null;

  function set<K extends keyof FormState>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    const projectId = fixedProject ? fixedProject.id : Number(form.project_id);
    if (!Number.isFinite(projectId) || projectId <= 0) {
      setError('Select the project this risk belongs to.');
      return;
    }
    if (!form.description.trim()) {
      setError('Description is required.');
      return;
    }
    if (
      form.risk_start_date &&
      form.risk_end_date &&
      form.risk_end_date < form.risk_start_date
    ) {
      setError('Risk end date cannot be earlier than the risk start date.');
      return;
    }

    setSaving(true);
    try {
      const risk = await api.post<Risk>('/api/risks', {
        project_id: projectId,
        description: form.description.trim(),
        category: form.category.trim() || null,
        risk_source: (form.risk_source || null) as RiskSource | null,
        likelihood: form.likelihood,
        impact: form.impact,
        response_strategy: (form.response_strategy || null) as ResponseStrategy | null,
        response_plan: form.response_plan.trim() || null,
        owner_user_id: form.owner_user_id === '' ? null : Number(form.owner_user_id),
        risk_start_date: form.risk_start_date || null,
        risk_end_date: form.risk_end_date || null,
        identified_during: form.identified_during.trim() || null,
        source: 'Custom',
      });
      onCreated(risk);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Add risk</h2>
          <button className="btn btn-sm" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}

        <form onSubmit={handleSubmit}>
          <div className="form-grid">
            <div className="field" style={{ gridColumn: '1 / -1' }}>
              <label>Project *</label>
              {fixedProject ? (
                <div className="readonly-field">
                  <span className="mono">{fixedProject.project_code}</span>
                  <span style={{ marginLeft: 8 }}>{fixedProject.name}</span>
                </div>
              ) : (
                <select
                  value={form.project_id}
                  onChange={(e) => set('project_id', e.target.value)}
                >
                  <option value="">Select project…</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.project_code} — {p.name}
                    </option>
                  ))}
                </select>
              )}
            </div>

            <div className="field" style={{ gridColumn: '1 / -1' }}>
              <label>Description *</label>
              <textarea
                value={form.description}
                onChange={(e) => set('description', e.target.value)}
                placeholder="Describe the risk…"
              />
            </div>

            <PickOrTypeField
              label="Category"
              value={form.category}
              onChange={(v) => set('category', v)}
              options={categoryOptions}
            />
            <div className="field">
              <label>Risk source</label>
              <select value={form.risk_source} onChange={(e) => set('risk_source', e.target.value)}>
                <option value="">—</option>
                <option value="Human">Human</option>
                <option value="Environmental">Environmental</option>
                <option value="Technical">Technical</option>
              </select>
            </div>
            <div className="field">
              <label>Likelihood</label>
              <select value={form.likelihood} onChange={(e) => set('likelihood', e.target.value)}>
                <option value="Low">Low</option>
                <option value="Medium">Medium</option>
                <option value="High">High</option>
              </select>
            </div>
            <div className="field">
              <label>Impact</label>
              <select value={form.impact} onChange={(e) => set('impact', e.target.value)}>
                <option value="Low">Low</option>
                <option value="Medium">Medium</option>
                <option value="High">High</option>
              </select>
            </div>
            <div className="field">
              <label>Response strategy</label>
              <select
                value={form.response_strategy}
                onChange={(e) => set('response_strategy', e.target.value)}
              >
                <option value="">—</option>
                <option value="Mitigate">Mitigate</option>
                <option value="Transfer">Transfer</option>
                <option value="Avoid">Avoid</option>
                <option value="Accept">Accept</option>
              </select>
            </div>
            <div className="field">
              <label>Risk start date</label>
              <input
                type="date"
                value={form.risk_start_date}
                onChange={(e) => set('risk_start_date', e.target.value)}
              />
            </div>
            <div className="field">
              <label>Risk end date</label>
              <input
                type="date"
                value={form.risk_end_date}
                onChange={(e) => set('risk_end_date', e.target.value)}
              />
              <span className="field-hint">
                The risk end date is the SLA deadline.
              </span>
            </div>
            <PickOrTypeField
              label="Project life cycle"
              value={form.identified_during}
              onChange={(v) => set('identified_during', v)}
              options={lifecycleOptions}
              placeholder="e.g. Execution, Discovery…"
            />
            <div className="field">
              <label>Owner</label>
              <UserPicker
                users={users}
                includeExternal
                selectedUserId={
                  form.owner_user_id === '' ? null : Number(form.owner_user_id)
                }
                onSelect={(user) =>
                  set('owner_user_id', user === null ? '' : String(user.id))
                }
              />
            </div>
            <div className="field" style={{ gridColumn: '1 / -1' }}>
              <label>Response plan</label>
              <textarea
                value={form.response_plan}
                onChange={(e) => set('response_plan', e.target.value)}
                placeholder="How will this risk be addressed?"
              />
            </div>
          </div>

          <div className="btn-group">
            <button className="btn btn-primary" type="submit" disabled={saving}>
              {saving ? 'Adding…' : 'Add risk'}
            </button>
            <button className="btn" type="button" onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
