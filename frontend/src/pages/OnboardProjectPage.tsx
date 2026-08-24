import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type { Project, ProjectCreatePayload } from '../api/types';

interface FormState {
  name: string;
  department: string;
  project_type: string;
  customer: string;
  start_date: string;
  end_date: string;
  stage_gate: string;
  pm_upn: string;
}

const EMPTY: FormState = {
  name: '',
  department: '',
  project_type: '',
  customer: '',
  start_date: '',
  end_date: '',
  stage_gate: '',
  pm_upn: '',
};

export function OnboardProjectPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof FormState>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.name.trim() || !form.department.trim() || !form.project_type.trim()) {
      setError('Name, department, and project type are required.');
      return;
    }

    const payload: ProjectCreatePayload = {
      name: form.name.trim(),
      department: form.department.trim(),
      project_type: form.project_type.trim(),
      customer: form.customer.trim() || null,
      start_date: form.start_date || null,
      end_date: form.end_date || null,
      stage_gate: form.stage_gate.trim() || null,
      pm_upn: form.pm_upn.trim() || null,
    };

    setSaving(true);
    try {
      const project = await api.post<Project>('/api/projects', payload);
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <Link to="/" className="muted">
            ← Risk Registers
          </Link>
          <h1>Onboard Project</h1>
          <div className="subtitle">
            Create a project and its risk register will be populated with recurring risks from
            historical data for you to accept or dismiss.
          </div>
        </div>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}

      <div className="card" style={{ maxWidth: 720 }}>
        <div className="card-body">
          <form onSubmit={handleSubmit}>
            <div className="form-grid">
              <div className="field" style={{ gridColumn: '1 / -1' }}>
                <label>Project name *</label>
                <input
                  value={form.name}
                  onChange={(e) => set('name', e.target.value)}
                  placeholder="e.g. NHIA AWS Migration"
                />
              </div>
              <div className="field">
                <label>Department *</label>
                <input
                  value={form.department}
                  onChange={(e) => set('department', e.target.value)}
                  placeholder="e.g. Digital Advisory"
                />
              </div>
              <div className="field">
                <label>Project type *</label>
                <input
                  value={form.project_type}
                  onChange={(e) => set('project_type', e.target.value)}
                  placeholder="e.g. Cloud Migration"
                />
              </div>
              <div className="field">
                <label>Customer</label>
                <input
                  value={form.customer}
                  onChange={(e) => set('customer', e.target.value)}
                  placeholder="e.g. NHIA"
                />
              </div>
              <div className="field">
                <label>Start date</label>
                <input
                  type="date"
                  value={form.start_date}
                  onChange={(e) => set('start_date', e.target.value)}
                />
              </div>
              <div className="field">
                <label>End date</label>
                <input
                  type="date"
                  value={form.end_date}
                  onChange={(e) => set('end_date', e.target.value)}
                />
              </div>
              <div className="field">
                <label>Stage gate</label>
                <input
                  value={form.stage_gate}
                  onChange={(e) => set('stage_gate', e.target.value)}
                  placeholder="e.g. Discovery"
                />
              </div>
              <div className="field">
                <label>PM UPN</label>
                <input
                  type="email"
                  value={form.pm_upn}
                  onChange={(e) => set('pm_upn', e.target.value)}
                  placeholder="pm@company.com"
                />
              </div>
            </div>
            <div className="btn-group">
              <button className="btn btn-primary" type="submit" disabled={saving}>
                {saving ? 'Creating…' : 'Create project'}
              </button>
              <Link to="/" className="btn">
                Cancel
              </Link>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
