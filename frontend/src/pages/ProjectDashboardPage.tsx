import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type { Project, ProjectRisk, Risk } from '../api/types';
import { SectionCard } from '../components/Badges';
import { DonutChart, StackedBarChart, TreemapChart } from '../components/charts';
import { KpiCard } from '../components/KpiCard';
import { RiskTable } from '../components/RiskTable';
import { SlaCountdownList } from '../components/SlaCountdownList';
import { SuggestionsPanel } from '../components/SuggestionsPanel';
import { useApi } from '../hooks/useApi';
import { categoryTreemap, computeKpis, ratingDistribution, statusStack } from '../utils/aggregates';
import { formatPercent } from '../utils/format';

function toRisk(pr: ProjectRisk): Risk {
  return {
    id: pr.id,
    risk_id: pr.risk_id,
    name: pr.name,
    project_id: pr.project_id,
    description: pr.description,
    category: pr.category,
    subcategory: pr.subcategory,
    risk_source: pr.risk_source,
    likelihood: pr.likelihood,
    impact: pr.impact,
    risk_rating: pr.risk_rating,
    response_strategy: pr.response_strategy,
    response_plan: pr.response_plan,
    owner_user_id: pr.owner_user_id,
    status: pr.status,
    source: pr.source,
    raised_by: pr.raised_by,
    identified_during: pr.identified_during,
    source_file_name: null,
    source_file_url: null,
    source_risk_id: null,
    llm_analysis: null,
    risk_start_date: pr.risk_start_date,
    risk_end_date: pr.risk_end_date,
    sla_deadline: pr.sla_deadline,
    sla_acknowledged: pr.sla_acknowledged,
    sla_manual_override: pr.sla_manual_override,
    accepted_date: null,
    resolved_date: null,
    closed_date: null,
    root_cause: null,
    what_worked: null,
    resolution_category: null,
    created_at: pr.created_at,
  };
}

export function ProjectDashboardPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const id = Number(projectId);

  const { data: project, error: projectError, reload: reloadProject } = useApi(
    () => api.get<Project>(`/api/projects/${id}`),
    [id],
  );
  const { data: risks, error: risksError, loading, reload: reloadRisks } = useApi(
    () => api.get<ProjectRisk[]>(`/api/projects/${id}/risks`),
    [id],
  );
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  if (!Number.isFinite(id) || id <= 0) {
    return <div className="error-banner">Invalid project id.</div>;
  }

  const riskList = (risks ?? []).map(toRisk);
  const kpis = computeKpis(riskList);

  function failAction(err: unknown) {
    setActionError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
  }

  async function handleClose() {
    setActionError(null);
    setBusy(true);
    try {
      await api.post<Project>(`/api/projects/${id}/close`);
      reloadProject();
    } catch (err) {
      failAction(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleReopen() {
    setActionError(null);
    setBusy(true);
    try {
      await api.post<Project>(`/api/projects/${id}/reopen`);
      reloadProject();
    } catch (err) {
      failAction(err);
    } finally {
      setBusy(false);
    }
  }

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
        {project?.status === 'Active' ? (
          <button className="btn btn-danger" onClick={() => void handleClose()} disabled={busy}>
            {busy ? 'Closing…' : 'Close project'}
          </button>
        ) : project?.status === 'Closed' ? (
          <button className="btn btn-primary" onClick={() => void handleReopen()} disabled={busy}>
            {busy ? 'Reopening…' : 'Reopen project'}
          </button>
        ) : null}
      </div>

      {projectError ? <div className="error-banner">{projectError}</div> : null}
      {actionError ? <div className="error-banner">{actionError}</div> : null}
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
            <SectionCard title="Risk by category">
              <TreemapChart data={categoryTreemap(riskList)} />
            </SectionCard>
          </div>

          <div className="chart-grid" style={{ gridTemplateColumns: '1fr 2fr' }}>
            <SectionCard title="SLA countdown">
              <SlaCountdownList risks={riskList} onSelect={(r) => navigate(`/risks/${r.id}`)} />
            </SectionCard>
            <SectionCard title={`Risk Register (${riskList.length})`}>
              <RiskTable risks={riskList} onSelect={(r) => navigate(`/risks/${r.id}`)} />
            </SectionCard>
          </div>
        </>
      )}
    </div>
  );
}
