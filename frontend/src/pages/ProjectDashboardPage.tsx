import { Link, useNavigate, useParams } from 'react-router-dom';

import { api } from '../api/client';
import type { Project, Risk } from '../api/types';
import { SectionCard } from '../components/Badges';
import { DonutChart, StackedBarChart, TreemapChart } from '../components/charts';
import { KpiCard } from '../components/KpiCard';
import { RiskTable } from '../components/RiskTable';
import { SlaCountdownList } from '../components/SlaCountdownList';
import { SuggestionsPanel } from '../components/SuggestionsPanel';
import { useApi } from '../hooks/useApi';
import { categoryTreemap, computeKpis, ratingDistribution, statusStack } from '../utils/aggregates';
import { formatPercent } from '../utils/format';

export function ProjectDashboardPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const id = Number(projectId);

  const { data: project, error: projectError } = useApi(
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

  return (
    <div>
      <div className="page-header">
        <div>
          <Link to="/projects" className="muted">
            ← Projects
          </Link>
          <h1>{project?.name ?? 'Project'}</h1>
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
      </div>

      {projectError ? <div className="error-banner">{projectError}</div> : null}
      {risksError ? <div className="error-banner">{risksError}</div> : null}

      <SuggestionsPanel projectId={id} onAccepted={reloadRisks} />

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
              <SlaCountdownList risks={riskList} onSelect={(r) => navigate(`/risks/${r.id}`)} />
            </SectionCard>
          </div>

          <div className="chart-grid" style={{ gridTemplateColumns: '1fr' }}>
            <SectionCard title={`Risk Register (${riskList.length})`}>
              <RiskTable risks={riskList} onSelect={(r) => navigate(`/risks/${r.id}`)} />
            </SectionCard>
          </div>
        </>
      )}
    </div>
  );
}
