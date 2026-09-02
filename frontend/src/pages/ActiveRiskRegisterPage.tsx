import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { Project, Risk } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { AddRiskModal } from '../components/AddRiskModal';
import { RatingBadge, StatusBadge } from '../components/Badges';
import { useApi } from '../hooks/useApi';
import { formatDate } from '../utils/format';
import { isActiveStatus } from '../utils/status';

export function ActiveRiskRegisterPage() {
  const navigate = useNavigate();
  const auth = useAuth();
  const { data: projects, reload: reloadProjects } = useApi(() =>
    api.get<Project[]>('/api/projects?status=Active'),
  );
  const { data: risks, error, loading, reload } = useApi(() => api.get<Risk[]>('/api/risks'));
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const [addingProject, setAddingProject] = useState<Project | null>(null);
  const [closingProject, setClosingProject] = useState<Project | null>(null);
  const [closing, setClosing] = useState(false);
  const [closeError, setCloseError] = useState<string | null>(null);

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

  // Project Status is the source of truth for the Active Risk Register.
  // The backend query already filters to Active; this guard keeps the rule explicit.
  const projectsWithActive = useMemo(
    () => (projects ?? []).filter((p) => p.status === 'Active'),
    [projects],
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

  function canCloseProject(p: Project): boolean {
    // In dev mode the role/user are known locally, so only the assigned
    // Project Manager sees the action. In Entra (production) mode roles are
    // resolved server-side; the button stays visible and the backend enforces
    // the same rule with a 403 for anyone else.
    if (!auth.isDevMode) return true;
    return auth.role === 'Project Manager' && auth.userId !== null && p.pm_user_id === auth.userId;
  }

  async function confirmClose() {
    if (!closingProject) return;
    setClosing(true);
    setCloseError(null);
    try {
      await api.post<Project>(`/api/projects/${closingProject.id}/close`);
      setClosingProject(null);
      reloadProjects();
    } catch (err) {
      setCloseError(err instanceof Error ? err.message : String(err));
    } finally {
      setClosing(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Active Risk Register</h1>
          <div className="subtitle">
            Active projects — expand a project to see its active risks
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
            No active projects yet.{' '}
            <Link to="/onboard">Onboard a project</Link> to start its risk register.
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
                    + Add New
                  </button>
                  {canCloseProject(p) ? (
                    <button
                      className="btn btn-sm btn-danger"
                      onClick={(e) => {
                        e.stopPropagation();
                        setClosingProject(p);
                        setCloseError(null);
                      }}
                    >
                      Close Project
                    </button>
                  ) : null}
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
                          return (
                            <tr
                              key={risk.id}
                              onClick={() => navigate(`/risks/${risk.id}?from=active-register`)}
                            >
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
                        {activeRisks.length === 0 ? (
                          <tr>
                            <td colSpan={14} className="empty-state">
                              No active risks for this project.
                            </td>
                          </tr>
                        ) : null}
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

      {closingProject ? (
        <div className="modal-overlay" onClick={() => setClosingProject(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Close Project?</h2>
              <button className="btn btn-sm" onClick={() => setClosingProject(null)} aria-label="Close">
                ✕
              </button>
            </div>
            <p>
              Are you sure you want to close{' '}
              <strong>“{closingProject.name}”</strong>?
            </p>
            <p className="muted">
              Closing this project will remove it from the Active Risk Register. The project and
              its risk history will remain available in the Projects area.
            </p>
            {closeError ? <div className="error-banner">{closeError}</div> : null}
            <div className="btn-group">
              <button className="btn" onClick={() => setClosingProject(null)}>
                Cancel
              </button>
              <button className="btn btn-danger" disabled={closing} onClick={() => void confirmClose()}>
                {closing ? 'Closing…' : 'Close Project'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
