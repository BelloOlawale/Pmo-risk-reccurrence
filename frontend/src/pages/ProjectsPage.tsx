import { Fragment, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api/client';
import type { Project } from '../api/types';
import { StatusBadge } from '../components/Badges';
import { useApi } from '../hooks/useApi';
import { formatDate } from '../utils/format';

export function ProjectsPage() {
  const { data, error, loading } = useApi(() => api.get<Project[]>('/api/projects'));
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const projects = data ?? [];

  function toggle(id: number) {
    setExpandedId((cur) => (cur === id ? null : id));
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Projects</h1>
          <div className="subtitle">Every project in the system — expand a row to see its risks</div>
        </div>
        <Link to="/onboard" className="btn btn-primary">
          + Onboard project
        </Link>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}
      {loading ? (
        <div className="loading">Loading projects…</div>
      ) : projects.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            No projects yet.{' '}
            <Link to="/onboard">Onboard your first project</Link> to start its risk register.
          </div>
        </div>
      ) : (
        <div className="card table-wrap">
          <table>
            <thead>
              <tr>
                <th>Code</th>
                <th>Name</th>
                <th>Department</th>
                <th>Type</th>
                <th>Customer</th>
                <th>Status</th>
                <th>Risks</th>
                <th>Start date</th>
                <th>Stage gate</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => {
                const expanded = expandedId === p.id;
                return (
                  <Fragment key={p.id}>
                    <tr className="row-expandable" onClick={() => toggle(p.id)}>
                      <td className="mono">
                        <span className="expand-indicator">{expanded ? '▾' : '▸'}</span>
                        <Link to={`/projects/${p.id}`} onClick={(e) => e.stopPropagation()}>
                          {p.project_code}
                        </Link>
                      </td>
                      <td>
                        <Link to={`/projects/${p.id}`} onClick={(e) => e.stopPropagation()}>
                          {p.name}
                        </Link>
                      </td>
                      <td>{p.department_name}</td>
                      <td>{p.project_type_name}</td>
                      <td>{p.customer ?? '—'}</td>
                      <td>
                        <StatusBadge status={p.status} />
                      </td>
                      <td>
                        <Link to={`/projects/${p.id}`} onClick={(e) => e.stopPropagation()}>
                          {p.risk_count}
                        </Link>
                      </td>
                      <td>{formatDate(p.start_date)}</td>
                      <td>{p.stage_gate ?? '—'}</td>
                    </tr>
                    {expanded ? (
                      <tr className="expanded-row">
                        <td colSpan={9}>
                          <div className="expanded-panel">
                            <div className="expanded-title">Risk IDs ({p.risk_codes.length})</div>
                            {p.risk_codes.length === 0 ? (
                              <span className="muted">No risks yet.</span>
                            ) : (
                              <div className="risk-tags">
                                {p.risk_codes.map((code, i) => (
                                  <Link
                                    key={p.risk_ids[i]}
                                    to={`/risks/${p.risk_ids[i]}`}
                                    className="tag"
                                  >
                                    {code}
                                  </Link>
                                ))}
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
