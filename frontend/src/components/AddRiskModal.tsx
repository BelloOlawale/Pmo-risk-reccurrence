import { useState } from 'react';
import type { FormEvent } from 'react';

import { api, ApiError } from '../api/client';
import type {
  Impact,
  Likelihood,
  Project,
  ResponseStrategy,
  Risk,
  RiskCatalog,
  RiskSource,
} from '../api/types';
import { useApi } from '../hooks/useApi';

interface AddRiskModalProps {
  projects: Project[];
  /** Pre-select this project when the modal opens (e.g. quick-add from a project). */
  initialProjectId?: number;
  onClose: () => void;
  onCreated: (risk: Risk) => void;
}

interface FormState {
  catalog_risk_id: string;
  project_id: string;
  description: string;
  category: string;
  subcategory: string;
  risk_source: string;
  likelihood: string;
  impact: string;
  response_strategy: string;
  response_plan: string;
  risk_start_date: string;
  risk_end_date: string;
  identified_during: string;
}

const EMPTY: FormState = {
  catalog_risk_id: '',
  project_id: '',
  description: '',
  category: '',
  subcategory: '',
  risk_source: '',
  likelihood: 'Medium',
  impact: 'Medium',
  response_strategy: '',
  response_plan: '',
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

  const { data: catalog } = useApi(() => api.get<RiskCatalog[]>('/api/catalog'));
  const catalogRisks = catalog ?? [];

  const attaching = Number(form.catalog_risk_id) > 0;

  function set<K extends keyof FormState>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function handleCatalogSelect(value: string) {
    const selected = catalogRisks.find((c) => String(c.id) === value);
    setForm((f) => ({
      ...f,
      catalog_risk_id: value,
      description: selected ? selected.description : f.description,
      category: selected ? selected.category ?? '' : f.category,
      subcategory: selected ? selected.subcategory ?? '' : f.subcategory,
      risk_source: selected ? selected.risk_source ?? '' : f.risk_source,
    }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    const projectId = Number(form.project_id);
    if (!Number.isFinite(projectId) || projectId <= 0) {
      setError('Select the project this risk belongs to.');
      return;
    }
    const catalogRiskId = Number(form.catalog_risk_id);
    const isAttaching = Number.isFinite(catalogRiskId) && catalogRiskId > 0;
    if (!isAttaching && !form.description.trim()) {
      setError('Description is required (or attach an existing catalog risk).');
      return;
    }

    setSaving(true);
    try {
      const risk = await api.post<Risk>('/api/risks', {
        project_id: projectId,
        catalog_risk_id: isAttaching ? catalogRiskId : null,
        description: isAttaching ? null : form.description.trim(),
        category: isAttaching ? null : form.category.trim() || null,
        subcategory: isAttaching ? null : form.subcategory.trim() || null,
        risk_source: isAttaching ? null : ((form.risk_source || null) as RiskSource | null),
        likelihood: form.likelihood as Likelihood,
        impact: form.impact as Impact,
        response_strategy: (form.response_strategy || null) as ResponseStrategy | null,
        response_plan: form.response_plan.trim() || null,
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
            </div>

            <div className="field" style={{ gridColumn: '1 / -1' }}>
              <label>Existing catalog risk (optional)</label>
              <select
                value={form.catalog_risk_id}
                onChange={(e) => handleCatalogSelect(e.target.value)}
              >
                <option value="">— New risk —</option>
                {catalogRisks.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name ?? c.description} — {c.description}
                  </option>
                ))}
              </select>
            </div>

            <div className="field" style={{ gridColumn: '1 / -1' }}>
              <label>Description *</label>
              <textarea
                value={form.description}
                onChange={(e) => set('description', e.target.value)}
                placeholder="Describe the risk…"
                disabled={attaching}
              />
            </div>

            <div className="field">
              <label>Category</label>
              <input
                value={form.category}
                onChange={(e) => set('category', e.target.value)}
                disabled={attaching}
              />
            </div>
            <div className="field">
              <label>Subcategory</label>
              <input
                value={form.subcategory}
                onChange={(e) => set('subcategory', e.target.value)}
                disabled={attaching}
              />
            </div>
            <div className="field">
              <label>Risk source</label>
              <select
                value={form.risk_source}
                onChange={(e) => set('risk_source', e.target.value)}
                disabled={attaching}
              >
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
            </div>
            <div className="field">
              <label>Project life cycle</label>
              <input
                value={form.identified_during}
                onChange={(e) => set('identified_during', e.target.value)}
                placeholder="e.g. Execution, Discovery…"
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
