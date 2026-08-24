import { useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { Project, Risk } from '../api/types';
import { SectionCard } from '../components/Badges';
import {
  EscalationTrendChart,
  HeatmapChart,
  ProjectBarChart,
} from '../components/charts';
import { KpiCard } from '../components/KpiCard';
import {
  computePortfolioKpis,
  escalationTrend,
  heatmapData,
  riskByProject,
} from '../utils/aggregates';
import { formatPercent } from '../utils/format';

export function PortfolioDashboardPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [risks, setRisks] = useState<Risk[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const projectList = await api.get<Project[]>('/api/projects');
        const riskLists = await Promise.all(
          projectList.map((p) => api.get<Risk[]>(`/api/projects/${p.id}/risks`)),
        );
        if (!cancelled) {
          setProjects(projectList);
          setRisks(riskLists.flat());
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.message
              : err instanceof Error
                ? err.message
                : String(err),
          );
          setLoading(false);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const kpis = computePortfolioKpis(projects, risks);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Portfolio</h1>
          <div className="subtitle">Cross-project risk landscape (PMO view)</div>
        </div>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}

      <div className="kpi-grid">
        <KpiCard label="Projects" value={kpis.projects} />
        <KpiCard label="Total risks" value={kpis.risks} />
        <KpiCard label="Open risks" value={kpis.open} tone="info" />
        <KpiCard label="Escalated" value={kpis.escalated} tone="warning" />
        <KpiCard label="SLA compliance" value={formatPercent(kpis.slaCompliance)} tone="success" />
      </div>

      {loading ? (
        <div className="loading">Loading portfolio…</div>
      ) : (
        <>
          <div className="chart-grid">
            <SectionCard title="Project × category heatmap">
              <HeatmapChart data={heatmapData(projects, risks)} />
            </SectionCard>
            <SectionCard title="Risk by project (stacked by rating)">
              <ProjectBarChart data={riskByProject(projects, risks)} />
            </SectionCard>
            <SectionCard title="Escalation trend">
              <EscalationTrendChart data={escalationTrend(risks)} />
            </SectionCard>
          </div>
        </>
      )}
    </div>
  );
}
