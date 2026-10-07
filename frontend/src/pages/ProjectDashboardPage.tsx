import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { api } from '../api/client';
import type { Issue, Me, Project, Risk } from '../api/types';
import { ownerName, useUsers } from '../api/users';
import { AddRiskModal } from '../components/AddRiskModal';
import { SectionCard, StatusBadge } from '../components/Badges';
import { DonutChart, StackedBarChart, TreemapChart } from '../components/charts';
import { IssueTable } from '../components/IssueTable';
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
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const users = useUsers();

  const { data: me } = useApi(() => api.get<Me>('/api/me'), []);
  const { data: project, error: projectError, reload: reloadProject } = useApi(
    () => api.get<Project>(`/api/projects/${id}`),
    [id],
  );
  const { data: risks, error: risksError, loading, reload: reloadRisks } = useApi(
    () => api.get<Risk[]>(`/api/projects/${id}/risks`),
    [id],
  );
  const { data: issues, error: issuesError, reload: reloadIssues } = useApi(
    () => api.get<Issue[]>(`/api/projects/${id}/issues`),
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

  async function handleDeleteRisk(risk: Risk) {
    await api.del<void>(`/api/risks/${risk.id}`);
    reloadRisks();
    reloadIssues();
    reloadProject();
  }

  function canManageRisks(): boolean {
    if (!me || !project) return false;
    if (me.roles.some((role) => role === 'PMO Lead' || role === 'System Admin')) {
      return true;
    }
    return (
      me.roles.includes('Project Manager') &&
      me.user_id !== null &&
      project.pm_user_id === me.user_id
    );
  }

  function handleRiskCreated() {
    setAdding(false);
    reloadRisks();
    reloadIssues();
    reloadProject();
    // Adding a risk to a closed register reopens it (Active). Move the user
    // to Active Risk where the reopened register now lives.
    if (isClosed) {
      navigate('/active-risk');
    }
  }

  /** Download this register as a formatted .xlsx (current DB data). */
  async function handleExport() {
    setExporting(true);
    setExportError(null);
    try {
      const { blob, filename } = await api.download(`/api/projects/${id}/risks/export`);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename ?? `Risk_Register_${project?.project_code ?? id}.xlsx`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
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
                {' · '}PM: {project.pm_name ?? ownerName(users, project.pm_user_id)}
              </>
            ) : (
              'Loading…'
            )}
          </div>
        </div>
        <div className="page-header-actions">
          <button
            className="btn"
            onClick={() => void handleExport()}
            disabled={exporting || !project}
          >
            {exporting ? 'Exporting…' : 'Export to Excel'}
          </button>
          <button className="btn btn-primary" onClick={() => setAdding(true)}>
            + Add New
          </button>
        </div>
      </div>

      {exportError ? <div className="error-banner">{exportError}</div> : null}

      {projectError ? <div className="error-banner">{projectError}</div> : null}
      {risksError ? <div className="error-banner">{risksError}</div> : null}
      {issuesError ? <div className="error-banner">{issuesError}</div> : null}

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
                onDelete={handleDeleteRisk}
                canDelete={canManageRisks}
              />
            </SectionCard>
          </div>

          <div className="chart-grid" style={{ gridTemplateColumns: '1fr' }}>
            <SectionCard title={`Issues (${(issues ?? []).length})`}>
              <IssueTable
                issues={issues ?? []}
                onSelect={(issue) =>
                  navigate(`/issues/${issue.id}?from=${isClosed ? 'risk-history' : 'active-risk'}`)
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
