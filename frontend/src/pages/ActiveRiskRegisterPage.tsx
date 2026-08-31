import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { Project, Risk } from '../api/types';
import { AddRiskModal } from '../components/AddRiskModal';
import { RatingBadge, StatusBadge } from '../components/Badges';
import { useApi } from '../hooks/useApi';
import { countdownState, formatDate, formatDateTime } from '../utils/format';
import { isActiveStatus } from '../utils/status';

export function ActiveRiskRegisterPage() {
  const navigate = useNavigate();
  const { data: projects } = useApi(() => api.get<Project[]>('/api/projects'));
  const { data: risks, error, loading, reload } = useApi(() => api.get<Risk[]>('/api/risks'));
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const [addingProject, setAddingProject] = useState<Project | null>(null);

  // Active risks grouped by project id.
  const activeByProject = useMemo(() => {
    const map = new Map<number, Risk[]>();
    for (const r of risks ?? []) {
      if (isActiveStatus(r.status)) {
        const list = map.get(r.project_id) ?? [];
        list.push(r);
        map.set(r.project_id, list);
      }
    }
    return map;
  }, [risks]);

  // Projects that actually have at least one active risk, in list order.
  const projectsWithActive = useMemo(
    () => (projects ?? []).filter((p) => (activeByProject.get(p.id)?.length ?? 0) > 0),
    [projects, activeByProject],
  );

  const totalActive = useMemo(
    () =>
      projectsWithActive.reduce(
        (n, p) => n + (activeByProject.get(p.id)?.length ?? 0),
        0,
      ),
    [projectsWithActive, activeByProject],
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
            const activeRisks = activeByProject.get(p.id) ?? [];
            const isCollapsed = collapsed.has(p.id);
            return (
              <div className="card" key={p.id}>
                <div
                  className="register-project-header"
                  onClick={() => toggle(p.id)}
                >
                  <span className="expand-indicator">{isCollapsed ? '▸' : '▾'}</span>
                  <span className="mono">{p.project_code}</span>
                  <strong>{p.name}</strong>
                  <span className="register-project-meta">
                    {p.department_name} · {p.project_type_name}
                  </span>
                  <span className="active-count-badge">{activeRisks.length} active</span>
                  <button
                    className="btn btn-sm btn-primary"
                    onClick={(e) => {
                      e.stopPropagation();
                      setAddingProject(p);
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
                          <th>Code</th>
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
                        {activeRisks.map((risk) => {
                          const cd = countdownState(risk);
                          return (
                            <tr key={risk.id} onClick={() => navigate(`/risks/${risk.id}`)}>
                              <td className="mono">{risk.risk_code}</td>
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

      {addingProject ? (
        <AddRiskModal
          projects={projects ?? []}
          initialProjectId={addingProject.id}
          onClose={() => setAddingProject(null)}
          onCreated={() => {
            setAddingProject(null);
            reload();
          }}
        />
      ) : null}
    </div>
  );
}
