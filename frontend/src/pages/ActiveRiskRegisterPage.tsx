import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { ActiveRisk, Project } from '../api/types';
import { AddRiskModal } from '../components/AddRiskModal';
import { RatingBadge, StatusBadge } from '../components/Badges';
import { useApi } from '../hooks/useApi';
import { countdownState, formatDate, formatDateTime } from '../utils/format';

interface ActiveProject {
  id: number;
  project_code: string;
  name: string;
  department_name: string;
  project_type_name: string;
  risks: ActiveRisk[];
}

export function ActiveRiskRegisterPage() {
  const navigate = useNavigate();
  const { data: projects } = useApi(() => api.get<Project[]>('/api/projects'));
  const { data: rows, error, loading, reload } = useApi(
    () => api.get<ActiveRisk[]>('/api/active-register'),
  );
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const [addingProjectId, setAddingProjectId] = useState<number | null>(null);

  // The backend already derives the register; here we only group for display.
  const projectsWithActive = useMemo(() => {
    const map = new Map<number, ActiveRisk[]>();
    for (const r of rows ?? []) {
      const list = map.get(r.project_id) ?? [];
      list.push(r);
      map.set(r.project_id, list);
    }
    return [...map.entries()].map(([id, risks]) => ({
      id,
      project_code: risks[0].project_code,
      name: risks[0].project_name,
      department_name: risks[0].department_name,
      project_type_name: risks[0].project_type_name,
      risks,
    })) as ActiveProject[];
  }, [rows]);

  const totalActive = useMemo(
    () => projectsWithActive.reduce((n, p) => n + p.risks.length, 0),
    [projectsWithActive],
  );

  function toggle(id: number) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Active Risk Register</h1>
          <div className="subtitle">
            Active risks mapped by project — expand a project to see its live risks
          </div>
        </div>
      </div>

      <div className="mb-20 muted">
        {totalActive} active risk{totalActive === 1 ? '' : 's'} across{' '}
        {projectsWithActive.length} project{projectsWithActive.length === 1 ? '' : 's'}
      </div>

      {error ? <div className="error-banner">{error}</div> : null}

      {loading ? (
        <div className="loading">Loading active risks…</div>
      ) : projectsWithActive.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            No active risks yet.{' '}
            <Link to="/onboard">Onboard a project</Link> to generate its suggestions, or{' '}
            <Link to="/">add a risk</Link>.
          </div>
        </div>
      ) : (
        <div className="stack">
          {projectsWithActive.map((p) => {
            const isCollapsed = collapsed.has(p.id);
            return (
              <div className="card" key={p.id}>
                <div className="register-project-header" onClick={() => toggle(p.id)}>
                  <span className="expand-indicator">{isCollapsed ? '▸' : '▾'}</span>
                  <span className="mono">{p.project_code}</span>
                  <strong>{p.name}</strong>
                  <span className="register-project-meta">
                    {p.department_name} · {p.project_type_name}
                  </span>
                  <span className="active-count-badge">{p.risks.length} active</span>
                  <button
                    className="btn btn-sm btn-primary"
                    onClick={(e) => {
                      e.stopPropagation();
                      setAddingProjectId(p.id);
                    }}
                  >
                    + Quick add
                  </button>
                </div>

                {!isCollapsed ? (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Name</th>
                          <th>Description</th>
                          <th>Category</th>
                          <th>Likelihood</th>
                          <th>Impact</th>
                          <th>Rating</th>
                          <th>Status</th>
                          <th>Owner</th>
                          <th>SLA deadline</th>
                          <th>Risk start</th>
                          <th>Risk end</th>
                          <th>Project life cycle</th>
                          <th>Response strategy</th>
                          <th>Response plan</th>
                          <th>Source</th>
                        </tr>
                      </thead>
                      <tbody>
                        {p.risks.map((risk) => {
                          const cd = countdownState(risk);
                          return (
                            <tr key={risk.id} onClick={() => navigate(`/risks/${risk.id}`)}>
                              <td className="mono">{risk.name ?? '—'}</td>
                              <td className="cell-ellipsis" title={risk.description}>
                                {risk.description}
                              </td>
                              <td>{risk.category ?? '—'}</td>
                              <td>{risk.likelihood}</td>
                              <td>{risk.impact}</td>
                              <td>
                                <RatingBadge rating={risk.risk_rating} />
                              </td>
                              <td>
                                <StatusBadge status={risk.status} />
                              </td>
                              <td>{risk.owner_user_id !== null ? `User #${risk.owner_user_id}` : '—'}</td>
                              <td>
                                <span
                                  className={`tone-${cd.tone}`}
                                  title={formatDateTime(risk.sla_deadline)}
                                >
                                  {formatDateTime(risk.sla_deadline)}
                                </span>
                              </td>
                              <td>{formatDate(risk.risk_start_date)}</td>
                              <td>{formatDate(risk.risk_end_date)}</td>
                              <td>{risk.identified_during ?? '—'}</td>
                              <td>{risk.response_strategy ?? '—'}</td>
                              <td className="cell-ellipsis" title={risk.response_plan ?? ''}>
                                {risk.response_plan ?? '—'}
                              </td>
                              <td>{risk.source ?? '—'}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      {addingProjectId !== null ? (
        <AddRiskModal
          projects={projects ?? []}
          initialProjectId={addingProjectId}
          onClose={() => setAddingProjectId(null)}
          onCreated={() => {
            setAddingProjectId(null);
            reload();
          }}
        />
      ) : null}
    </div>
  );
}
