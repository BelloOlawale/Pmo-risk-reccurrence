import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { api } from '../api/client';
import type { Project, Risk } from '../api/types';
import { AddRiskModal } from '../components/AddRiskModal';
import { SectionCard, StatusBadge } from '../components/Badges';
import { DonutChart, StackedBarChart, TreemapChart } from '../components/charts';
import { KpiCard } from '../components/KpiCard';
import { RiskTable } from '../components/RiskTable';
import { SlaCountdownList } from '../components/SlaCountdownList';
import { useApi } from '../hooks/useApi';
import { categoryTreemap, computeKpis, ratingDistribution, statusStack } from '../utils/aggregates';
import { formatPercent } from '../utils/format';

export function ProjectDashboardPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const id = Number(projectId);
  const [adding, setAdding] = useState(false);

  const { data: project, error: projectError, reload: reloadProject } = useApi(
    () => api.get<Project>(`/api/projects/${id}`),
    [id],
  );
  const { data: risks, error: risksError, loading, reload: reloadRisks } = useApi(
    () => api.get<Risk[]>(`/api/projects/${id}/risks`),
    [id],
  );

  if (!Number.isFinite(id) || id <= 0) {
    return <div className="error-banner">Invalid project id.</div>;
  }

  const riskList = risks ?? [];
  const kpis = computeKpis(riskList);
  const isClosed = project?.status === 'Closed';
  const backTo = isClosed ? '/risk-history' : '/active-risk';
  const backLabel = isClosed ? '← Risk History' : '← Active Risk';

  function handleRiskCreated() {
    setAdding(false);
    reloadRisks();
    reloadProject();
    // Adding a risk to a closed register reopens it (Active). Move the user
    // to Active Risk where the reopened register now lives.
    if (isClosed) {
      navigate('/active-risk');
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <Link to={backTo} className="muted">
            {backLabel}
          </Link>
          <h1 style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {project?.name ?? 'Project'}
            {project ? <StatusBadge status={project.status} /> : null}
          </h1>
          <div className="subtitle">
            {project ? (
              <>
                <span className="mono">{project.project_code}</span> · {project.department_name} ·{' '}
                {project.project_type_name}
                {project.customer ? ` · ${project.customer}` : ''}
              </>
            ) : (
              'Loading…'
            )}
          </div>
        </div>
        <div className="page-header-actions">
          <button className="btn btn-primary" onClick={() => setAdding(true)}>
            + Add New
          </button>
        </div>
      </div>

      {projectError ? <div className="error-banner">{projectError}</div> : null}
      {risksError ? <div className="error-banner">{risksError}</div> : null}

      {isClosed ? (
        <div className="closed-banner">
          This risk register is closed. Add a new risk to reopen it in Active Risk.
        </div>
      ) : null}

      <div className="kpi-grid">
        <KpiCard label="Total risks" value={kpis.total} />
        <KpiCard label="High rating" value={kpis.high} tone="danger" />
        <KpiCard label="Escalated" value={kpis.escalated} tone="warning" />
        <KpiCard label="SLA compliance" value={formatPercent(kpis.slaCompliance)} tone="success" />
      </div>

      {loading ? (
        <div className="loading">Loading dashboard…</div>
      ) : (
        <>
          <div className="chart-grid">
            <SectionCard title="Risk rating">
              <DonutChart data={ratingDistribution(riskList)} />
            </SectionCard>
            <SectionCard title="Status (stacked by rating)">
              <StackedBarChart data={statusStack(riskList)} />
            </SectionCard>
          </div>

          <div className="chart-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
            <SectionCard title="Risk by category">
              <TreemapChart data={categoryTreemap(riskList)} />
            </SectionCard>
            <SectionCard title="SLA countdown">
              <SlaCountdownList
                risks={riskList}
                onSelect={(r) =>
                  navigate(`/risks/${r.id}?from=${isClosed ? 'risk-history' : 'active-risk'}`)
                }
              />
            </SectionCard>
          </div>

          <div className="chart-grid" style={{ gridTemplateColumns: '1fr' }}>
            <SectionCard title={`Risk Register (${riskList.length})`}>
              <RiskTable
                risks={riskList}
                onSelect={(r) =>
                  navigate(`/risks/${r.id}?from=${isClosed ? 'risk-history' : 'active-risk'}`)
                }
              />
            </SectionCard>
          </div>
        </>
      )}

      {adding ? (
        <AddRiskModal
          projects={project ? [project] : []}
          initialProjectId={id}
          onClose={() => setAdding(false)}
          onCreated={handleRiskCreated}
        />
      ) : null}
    </div>
  );
}
