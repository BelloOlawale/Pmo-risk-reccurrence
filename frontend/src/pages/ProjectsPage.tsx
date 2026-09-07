import { Fragment, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api/client';
import type { Project } from '../api/types';
import { StatusBadge } from '../components/Badges';
import { useApi } from '../hooks/useApi';
import { formatDate } from '../utils/format';

export function ProjectsPage() {
  const { data, error, loading } = useApi(() => api.get<Project[]>('/api/projects'));
  const [expandedId, setExpandedId] = useState<number | null>(null);

  // Risk History shows only closed registers — completed/historical work.
  const projects = useMemo(
    () => (data ?? []).filter((p) => p.status === 'Closed'),
    [data],
  );

  function toggle(id: number) {
    setExpandedId((cur) => (cur === id ? null : id));
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Risk History</h1>
          <div className="subtitle">
            Closed risk registers — open a register to inspect its historical risks
          </div>
        </div>
        <Link to="/create-risk" className="btn btn-primary">
          + Create Risk
        </Link>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}
      {loading ? (
        <div className="loading">Loading risk history…</div>
      ) : projects.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            No closed risk registers yet.{' '}
            <Link to="/create-risk">Create a risk register</Link> to get started.
          </div>
        </div>
      ) : (
        <div className="card table-wrap">
          <table>
            <thead>
              <tr>
                <th>Register</th>
                <th>Department</th>
                <th>Type</th>
                <th>Customer</th>
                <th>Status</th>
                <th>Risks</th>
                <th>Closed</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => {
                const expanded = expandedId === p.id;
                return (
                  <Fragment key={p.id}>
                    <tr className="row-expandable" onClick={() => toggle(p.id)}>
                      <td>
                        <span className="expand-indicator">{expanded ? '▾' : '▸'}</span>
                        <Link
                          to={`/risk-history/${p.id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="history-name"
                        >
                          {p.name}
                        </Link>
                        <div className="history-code mono">{p.project_code}</div>
                      </td>
                      <td>{p.department_name}</td>
                      <td>{p.project_type_name}</td>
                      <td>{p.customer ?? '—'}</td>
                      <td>
                        <StatusBadge status={p.status} />
                      </td>
                      <td>{p.risk_count}</td>
                      <td>{formatDate(p.closed_date)}</td>
                    </tr>
                    {expanded ? (
                      <tr className="expanded-row">
                        <td colSpan={7}>
                          <div className="expanded-panel">
                            <div className="expanded-title">Risks ({p.risk_codes.length})</div>
                            {p.risk_codes.length === 0 ? (
                              <span className="muted">No risks recorded.</span>
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
