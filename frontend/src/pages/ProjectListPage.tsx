import { Link } from 'react-router-dom';

import { api } from '../api/client';
import type { Project } from '../api/types';
import { StatusBadge } from '../components/Badges';
import { useApi } from '../hooks/useApi';
import { formatDate } from '../utils/format';

export function ProjectListPage() {
  const { data, error, loading } = useApi(() => api.get<Project[]>('/api/projects'));

  // "Active risk registers" = ongoing projects (status Active).
  const projects = (data ?? []).filter((p) => p.status === 'Active');

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Risk Registers</h1>
          <div className="subtitle">Active and ongoing projects — open one to see its risk register</div>
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
            No active projects yet.{' '}
            <Link to="/onboard">Onboard your first project</Link> to generate its risk register.
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
                <th>Start date</th>
                <th>Stage gate</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id}>
                  <td className="mono">
                    <Link to={`/projects/${p.id}`}>{p.project_code}</Link>
                  </td>
                  <td>
                    <Link to={`/projects/${p.id}`}>{p.name}</Link>
                  </td>
                  <td>{p.department_name}</td>
                  <td>{p.project_type_name}</td>
                  <td>{p.customer ?? '—'}</td>
                  <td>
                    <StatusBadge status={p.status} />
                  </td>
                  <td>{formatDate(p.start_date)}</td>
                  <td>{p.stage_gate ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
