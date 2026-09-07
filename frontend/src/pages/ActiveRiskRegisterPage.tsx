import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { Project, Risk } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { AddRiskModal } from '../components/AddRiskModal';
import { RiskTable } from '../components/RiskTable';
import { useApi } from '../hooks/useApi';
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
  const [blockedProject, setBlockedProject] = useState<Project | null>(null);
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

  function requestClose(p: Project) {
    setCloseError(null);
    const unresolved = activeByProject.get(p.id)?.length ?? 0;
    if (unresolved > 0) {
      setBlockedProject(p);
      return;
    }
    setClosingProject(p);
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
          <h1>Active Risk</h1>
          <div className="subtitle">
            Active risk registers — open a register to view its dashboard and risks
          </div>
        </div>
      </div>

      <div className="mb-20 muted">
        {totalActive} active risk{totalActive === 1 ? '' : 's'} across{' '}
        {projectsWithActive.length} register{projectsWithActive.length === 1 ? '' : 's'}
      </div>

      {error ? <div className="error-banner">{error}</div> : null}

      {loading ? (
        <div className="loading">Loading active risks…</div>
      ) : projectsWithActive.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            No active risk registers yet.{' '}
            <Link to="/create-risk">Create a risk register</Link> to get started.
          </div>
        </div>
      ) : (
        <div className="stack">
          {projectsWithActive.map((p) => {
            const activeRisks = activeByProject.get(p.id) ?? [];
            const isCollapsed = collapsed.has(p.id);
            const countLabel = `${activeRisks.length} Active Risk${activeRisks.length === 1 ? '' : 's'}`;
            return (
              <div className="card" key={p.id}>
                <div className="register-card-header" onClick={() => toggle(p.id)}>
                  <div className="register-card-main">
                    <span className="expand-indicator">{isCollapsed ? '▸' : '▾'}</span>
                    <div className="register-card-text">
                      <Link
                        to={`/active-risk/${p.id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="register-name"
                      >
                        {p.name}
                      </Link>
                      <div className="register-code-line">
                        <span className="mono">{p.project_code}</span>
                        <span className="register-sep">·</span>
                        <span>{p.department_name}</span>
                        <span className="register-sep">·</span>
                        <span>{p.project_type_name}</span>
                      </div>
                    </div>
                  </div>
                  <div className="register-card-actions">
                    <span className="active-count-badge">{countLabel}</span>
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
                        className="btn btn-sm btn-danger-ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          requestClose(p);
                        }}
                      >
                        Close Risk Register
                      </button>
                    ) : null}
                  </div>
                </div>

                {!isCollapsed ? (
                  <RiskTable
                    risks={activeRisks}
                    showToolbar={false}
                    onSelect={(risk) => navigate(`/risks/${risk.id}?from=active-risk`)}
                  />
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

      {blockedProject ? (
        <div className="modal-overlay" onClick={() => setBlockedProject(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Cannot Close Risk Register</h2>
              <button className="btn btn-sm" onClick={() => setBlockedProject(null)} aria-label="Close">
                ✕
              </button>
            </div>
            <p>
              There are unresolved risks in <strong>“{blockedProject.name}”</strong>.
            </p>
            <p className="muted">
              Please resolve or close all outstanding risks before closing the risk register.
            </p>
            <div className="btn-group">
              <button className="btn btn-primary" onClick={() => setBlockedProject(null)}>
                OK
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {closingProject ? (
        <div className="modal-overlay" onClick={() => setClosingProject(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Close Risk Register?</h2>
              <button className="btn btn-sm" onClick={() => setClosingProject(null)} aria-label="Close">
                ✕
              </button>
            </div>
            <p>
              Are you sure you want to close{' '}
              <strong>“{closingProject.name}”</strong>?
            </p>
            <p className="muted">
              Closing this register will move it from Active Risk to Risk History. The register and
              its risk history remain available as historical records.
            </p>
            {closeError ? <div className="error-banner">{closeError}</div> : null}
            <div className="btn-group">
              <button className="btn" onClick={() => setClosingProject(null)}>
                Cancel
              </button>
              <button className="btn btn-danger" disabled={closing} onClick={() => void confirmClose()}>
                {closing ? 'Closing…' : 'Close Risk Register'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
