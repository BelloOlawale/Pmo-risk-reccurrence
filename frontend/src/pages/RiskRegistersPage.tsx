import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { Me, Project, Risk } from '../api/types';
import { AddRiskModal } from '../components/AddRiskModal';
import { RiskTable } from '../components/RiskTable';
import { useApi } from '../hooks/useApi';

export function RiskRegistersPage() {
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);

  const { data: risks, error, loading, reload } = useApi(
    () => api.get<Risk[]>('/api/risks'),
  );
  const { data: projects } = useApi(() => api.get<Project[]>('/api/projects'));
  const { data: me } = useApi(() => api.get<Me>('/api/me'), []);

  const riskList = risks ?? [];

  async function handleDeleteRisk(risk: Risk) {
    await api.del<void>(`/api/risks/${risk.id}`);
    reload();
  }

  function canDeleteRisk(risk: Risk): boolean {
    if (!me) return false;
    if (me.roles.some((role) => role === 'PMO Lead' || role === 'System Admin')) {
      return true;
    }
    if (!me.roles.includes('Project Manager') || me.user_id === null) return false;
    const project = (projects ?? []).find((p) => p.id === risk.project_id);
    return project?.pm_user_id === me.user_id;
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Risk Registers</h1>
          <div className="subtitle">
            All risks across every project — active, historical, and closed
          </div>
        </div>
        <button className="btn btn-primary" onClick={() => setAdding(true)}>
          + Add risk
        </button>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}

      <div className="mb-20 muted">
        {riskList.length} risk{riskList.length === 1 ? '' : 's'} in the system ·{' '}
        <Link to="/risk-history">Browse risk history</Link>
      </div>

      {loading ? (
        <div className="loading">Loading risk register…</div>
      ) : riskList.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            No risks yet.{' '}
            <button className="link-btn" onClick={() => setAdding(true)}>
              Add your first risk
            </button>{' '}
            or <Link to="/create-risk">create a risk register</Link>.
          </div>
        </div>
      ) : (
        <div className="card">
          <RiskTable
            risks={riskList}
            onSelect={(r) => navigate(`/risks/${r.id}`)}
            onDelete={handleDeleteRisk}
            canDelete={canDeleteRisk}
          />
        </div>
      )}

      {adding ? (
        <AddRiskModal
          projects={projects ?? []}
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
