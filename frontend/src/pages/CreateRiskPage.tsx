import { useMemo, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type { Project, ProjectCreatePayload, Risk } from '../api/types';
import { AddRiskModal } from '../components/AddRiskModal';
import { RatingBadge, StatusBadge } from '../components/Badges';
import { SuggestionsPanel } from '../components/SuggestionsPanel';
import { useApi } from '../hooks/useApi';
import { todayISO } from '../utils/format';

const DEPARTMENTS: string[] = [
  'Business Solutions',
  'Datazone',
  'Tss',
  'Finance',
  'Digital advisory',
  'Marketing',
  'Sales',
  'Software Engineering',
  'Managed technology and advisory',
  'SAP',
  'Customer success',
];

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

function DepartmentField({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(-1);
  const rootRef = useRef<HTMLDivElement>(null);

  const matches = useMemo(() => {
    const q = value.trim().toLowerCase();
    if (!q) return DEPARTMENTS;
    return DEPARTMENTS.filter((d) => d.toLowerCase().includes(q));
  }, [value]);

  function commit(next: string) {
    onChange(next);
    setOpen(false);
    setHighlight(-1);
  }

  function onKeyDown(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (!open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      setOpen(true);
      setHighlight(0);
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, matches.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === 'Enter') {
      if (open && highlight >= 0 && matches[highlight]) {
        e.preventDefault();
        commit(matches[highlight]);
      } else {
        setOpen(false);
      }
    } else if (e.key === 'Escape') {
      setOpen(false);
      setHighlight(-1);
    }
  }

  return (
    <div className="combobox" ref={rootRef}>
      <input
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
          setHighlight(-1);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        onKeyDown={onKeyDown}
        placeholder="Select or type a department…"
        autoComplete="off"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
      />
      {open && matches.length > 0 ? (
        <ul className="combobox-menu" role="listbox">
          {matches.map((d, i) => (
            <li
              key={d}
              role="option"
              aria-selected={d === value}
              className={`combobox-option${i === highlight ? ' is-highlighted' : ''}`}
              onMouseDown={(e) => {
                e.preventDefault();
                commit(d);
              }}
              onMouseEnter={() => setHighlight(i)}
            >
              {d}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function CreateRiskForm({ onCreate }: { onCreate: (project: Project) => void }) {
  const [form, setForm] = useState<FormState>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<Record<string, string>>({});
  const today = todayISO();

  function set<K extends keyof FormState>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
    setFieldError((fe) => ({ ...fe, [key]: '' }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const nextFieldError: Record<string, string> = {};

    if (!form.name.trim()) nextFieldError.name = 'Name is required.';
    if (!form.department.trim()) nextFieldError.department = 'Department is required.';
    if (!form.project_type.trim()) nextFieldError.project_type = 'Project type is required.';
    if (!form.customer.trim()) nextFieldError.customer = 'Customer is required.';
    if (form.start_date && form.start_date < today) {
      nextFieldError.start_date = 'Start date cannot be in the past.';
    }

    if (Object.keys(nextFieldError).length > 0) {
      setFieldError(nextFieldError);
      return;
    }

    const payload: ProjectCreatePayload = {
      name: form.name.trim(),
      department: form.department.trim(),
      project_type: form.project_type.trim(),
      customer: form.customer.trim(),
      start_date: form.start_date || null,
      end_date: form.end_date || null,
      stage_gate: form.stage_gate.trim() || null,
      pm_upn: form.pm_upn.trim() || null,
    };

    setSaving(true);
    try {
      const project = await api.post<Project>('/api/projects', payload);
      onCreate(project);
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
          <h1>Create New Risk Register</h1>
          <div className="subtitle">
            Enter the project information, then review the suggested risks before completing the
            register.
          </div>
        </div>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}

      <div className="card" style={{ maxWidth: 720 }}>
        <div className="card-body">
          <form onSubmit={handleSubmit} noValidate>
            <div className="form-grid">
              <div className="form-section-title">Project information</div>
              <div className="field" style={{ gridColumn: '1 / -1' }}>
                <label>Project / register name *</label>
                <input
                  value={form.name}
                  onChange={(e) => set('name', e.target.value)}
                  placeholder="e.g. NHIA AWS Migration"
                />
                {fieldError.name ? <span className="field-error">{fieldError.name}</span> : null}
              </div>
              <div className="field">
                <label>Department *</label>
                <DepartmentField value={form.department} onChange={(v) => set('department', v)} />
                {fieldError.department ? (
                  <span className="field-error">{fieldError.department}</span>
                ) : null}
              </div>
              <div className="field">
                <label>Project type *</label>
                <input
                  value={form.project_type}
                  onChange={(e) => set('project_type', e.target.value)}
                  placeholder="e.g. Cloud Migration"
                />
                {fieldError.project_type ? (
                  <span className="field-error">{fieldError.project_type}</span>
                ) : null}
              </div>
              <div className="field" style={{ gridColumn: '1 / -1' }}>
                <label>Customer *</label>
                <input
                  value={form.customer}
                  onChange={(e) => set('customer', e.target.value)}
                  placeholder="e.g. NHIA"
                />
                {fieldError.customer ? (
                  <span className="field-error">{fieldError.customer}</span>
                ) : null}
              </div>
              <div className="form-section-title">Schedule &amp; ownership</div>
              <div className="field">
                <label>Start date</label>
                <input
                  type="date"
                  min={today}
                  value={form.start_date}
                  onChange={(e) => set('start_date', e.target.value)}
                />
                {fieldError.start_date ? (
                  <span className="field-error">{fieldError.start_date}</span>
                ) : null}
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
                {saving ? 'Creating…' : 'Create Risk Register'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

function RegisterBuilder({ project }: { project: Project }) {
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);
  const { data: risks, loading, reload } = useApi(
    () => api.get<Risk[]>(`/api/projects/${project.id}/risks`),
    [project.id],
  );

  const riskList = risks ?? [];

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="step-indicator">
            <span className="step done">1. Register details</span>
            <span className="step-arrow">→</span>
            <span className="step current">2. Suggested risks</span>
            <span className="step-arrow">→</span>
            <span className="step">3. Review &amp; Done</span>
          </div>
          <h1>Suggested Risks</h1>
          <div className="subtitle">
            Review the risks identified for <strong>{project.name}</strong> before completing the
            risk register.
          </div>
        </div>
        <div className="page-header-actions">
          <button className="btn btn-primary" onClick={() => navigate(`/active-risk/${project.id}`)}>
            Done
          </button>
        </div>
      </div>

      <div className="stack">
        <SuggestionsPanel projectId={project.id} onChanged={reload} />

        <div className="card">
          <div className="card-header">
            <span className="card-header-title">
              Risk Register ({riskList.length})
            </span>
            <span className="card-header-actions">
              <button className="btn btn-sm btn-primary" onClick={() => setAdding(true)}>
                + Add New
              </button>
            </span>
          </div>
          <div className="card-body">
            {loading ? (
              <div className="loading">Loading register…</div>
            ) : riskList.length === 0 ? (
              <div className="empty-state">
                No risks in this register yet. Accept suggestions above or add new risks.
              </div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Risk Description</th>
                      <th>Risk Rating</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {riskList.map((r) => (
                      <tr key={r.id}>
                        <td className="cell-ellipsis" title={r.description}>
                          {r.description}
                        </td>
                        <td>
                          <RatingBadge rating={r.risk_rating} />
                        </td>
                        <td>
                          <StatusBadge status={r.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>

      {adding ? (
        <AddRiskModal
          projects={[project]}
          initialProjectId={project.id}
          onClose={() => setAdding(false)}
          onCreated={() => {
            setAdding(false);
            reload();
          }}
        />
      ) : null}
    </div>
  );
}

export function CreateRiskPage() {
  const [project, setProject] = useState<Project | null>(null);
  return project ? (
    <RegisterBuilder project={project} />
  ) : (
    <CreateRiskForm onCreate={setProject} />
  );
}
