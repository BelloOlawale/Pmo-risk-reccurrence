import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type { Project, Risk } from '../api/types';
import { SectionCard } from '../components/Badges';
import {
  CategoryBarChart,
  DonutChart,
  EscalatedDonutChart,
  EscalationTrendChart,
  HeatmapChart,
  ProjectStackedBarChart,
} from '../components/charts';
import { KpiCard } from '../components/KpiCard';
import {
  categoryDistribution,
  computePortfolioKpis,
  escalationTrend,
  escalatedSplit,
  heatmapData,
  portfolioInsights,
  ratingDistribution,
  riskByProject,
} from '../utils/aggregates';
import { formatPercent } from '../utils/format';

const PERIODS: { value: string; label: string }[] = [
  { value: 'all', label: 'All time' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
  { value: '365', label: 'Last 12 months' },
];

const RATINGS = ['High', 'Medium', 'Low'];

function percent(part: number, total: number): string {
  if (total === 0) return '0% of total';
  return `${Math.round((part / total) * 100)}% of total`;
}

export function PortfolioDashboardPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [risks, setRisks] = useState<Risk[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters (all client-side over the already-loaded portfolio).
  const [period, setPeriod] = useState('all');
  const [projectId, setProjectId] = useState('');
  const [rating, setRating] = useState('');
  const [category, setCategory] = useState('');
  const [showAllHeatmap, setShowAllHeatmap] = useState(false);
  const [showAllBars, setShowAllBars] = useState(false);

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const projectList = await api.get<Project[]>('/api/projects');
      const riskLists = await Promise.all(
        projectList.map((p) => api.get<Risk[]>(`/api/projects/${p.id}/risks`)),
      );
      setProjects(projectList);
      setRisks(riskLists.flat());
      setError(null);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : String(err),
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const r of risks) set.add(r.category ?? 'Uncategorized');
    return [...set].sort();
  }, [risks]);

  // Apply filters to risks.
  const filteredRisks = useMemo(() => {
    const now = Date.now();
    const days = period === 'all' ? null : Number(period);
    return risks.filter((r) => {
      if (days !== null) {
        const created = new Date(r.created_at).getTime();
        if (Number.isFinite(created) && created < now - days * 86_400_000) {
          return false;
        }
      }
      if (projectId && r.project_id !== Number(projectId)) return false;
      if (rating && r.risk_rating !== rating) return false;
      if (category && (r.category ?? 'Uncategorized') !== category) return false;
      return true;
    });
  }, [risks, period, projectId, rating, category]);

  const filteredProjects = useMemo(() => {
    if (!projectId) return projects;
    return projects.filter((p) => p.id === Number(projectId));
  }, [projects, projectId]);

  const kpis = computePortfolioKpis(filteredProjects, filteredRisks);

  const departmentCount = useMemo(
    () => new Set(filteredProjects.map((p) => p.department_name)).size,
    [filteredProjects],
  );

  const trend = escalationTrend(filteredRisks);
  const hasTrend = trend.months.length >= 2;

  const heatmapLimit = showAllHeatmap ? filteredProjects.length : 12;
  const barLimit = showAllBars ? filteredProjects.length : 10;

  const navigateToProject = useCallback(
    (code: string) => {
      const project = filteredProjects.find((p) => p.project_code === code);
      if (project) navigate(`/projects/${project.id}`);
    },
    [filteredProjects, navigate],
  );

  const insights = portfolioInsights(filteredProjects, filteredRisks);

  const hasFilters = period !== 'all' || projectId !== '' || rating !== '' || category !== '';

  const periodLabel = PERIODS.find((p) => p.value === period)?.label ?? 'All time';

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div>
          <h1>Portfolio</h1>
          <div className="subtitle">Cross-project risk landscape (PMO view)</div>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="btn"
            onClick={() => void load(true)}
            disabled={refreshing}
          >
            {refreshing ? 'Refreshing…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}

      {/* Filters */}
      <div className="filter-bar">
        <label className="filter-field">
          <span>Period</span>
          <select value={period} onChange={(e) => setPeriod(e.target.value)}>
            {PERIODS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label className="filter-field">
          <span>Project</span>
          <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">All projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.project_code} — {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="filter-field">
          <span>Category</span>
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="filter-field">
          <span>Rating</span>
          <select value={rating} onChange={(e) => setRating(e.target.value)}>
            <option value="">All ratings</option>
            {RATINGS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        {hasFilters ? (
          <button
            type="button"
            className="link-btn filter-clear"
            onClick={() => {
              setPeriod('all');
              setProjectId('');
              setRating('');
              setCategory('');
            }}
          >
            Clear filters
          </button>
        ) : null}
      </div>

      {/* KPI cards */}
      <div className="kpi-grid kpi-grid-5">
        <KpiCard label="Projects" value={kpis.projects} hint={`${departmentCount} departments`} />
        <KpiCard label="Total risks" value={kpis.risks} hint={`${kpis.high} rated High`} />
        <KpiCard label="Open risks" value={kpis.open} tone="info" hint={percent(kpis.open, kpis.risks)} />
        <KpiCard label="Escalated" value={kpis.escalated} tone="danger" hint={percent(kpis.escalated, kpis.risks)} />
        <KpiCard
          label="SLA compliance"
          value={formatPercent(kpis.slaCompliance)}
          tone="success"
          hint={`${kpis.withDeadline} risks with deadlines`}
        />
      </div>

      {loading ? (
        <div className="loading">Loading portfolio…</div>
      ) : (
        <>
          {/* Risk Overview */}
          <h2 className="section-title">Risk Overview</h2>
          <div className="overview-grid">
            <SectionCard title="Risk rating distribution">
              <DonutChart data={ratingDistribution(filteredRisks)} />
            </SectionCard>
            <SectionCard title="Risks by category">
              <CategoryBarChart data={categoryDistribution(filteredRisks)} />
            </SectionCard>
            <SectionCard title="Escalated vs not escalated">
              <EscalatedDonutChart data={escalatedSplit(filteredRisks)} />
            </SectionCard>
          </div>

          {/* Detailed Risk Analysis */}
          <h2 className="section-title">Detailed Risk Analysis</h2>
          <div className="analysis-grid">
            <SectionCard
              title="Project × category heatmap"
              actions={
                filteredProjects.length > 12 ? (
                  <button type="button" className="btn btn-sm" onClick={() => setShowAllHeatmap((s) => !s)}>
                    {showAllHeatmap ? 'Top 12' : 'View all'}
                  </button>
                ) : undefined
              }
            >
              <HeatmapChart
                data={heatmapData(filteredProjects, filteredRisks, { maxProjects: heatmapLimit })}
                onSelect={navigateToProject}
              />
            </SectionCard>
            <SectionCard
              title="Risk by project"
              actions={
                filteredProjects.length > 10 ? (
                  <button type="button" className="btn btn-sm" onClick={() => setShowAllBars((s) => !s)}>
                    {showAllBars ? 'Top 10' : 'View all'}
                  </button>
                ) : undefined
              }
            >
              <ProjectStackedBarChart
                data={riskByProject(filteredProjects, filteredRisks, barLimit)}
                onSelect={navigateToProject}
              />
            </SectionCard>
          </div>

          {/* Escalation trend */}
          <SectionCard title="Escalation trend" actions={<span className="muted">{periodLabel}</span>}>
            {hasTrend ? (
              <EscalationTrendChart data={trend} />
            ) : (
              <div className="empty-trend">
                <div className="empty-trend-title">No historical escalation data available</div>
                <div className="empty-trend-sub">
                  Escalation trends will appear as more project risk data is recorded.
                </div>
              </div>
            )}
          </SectionCard>

          {/* Portfolio insights */}
          <h2 className="section-title">Portfolio Insights</h2>
          {insights.length > 0 ? (
            <div className="insights-list">
              {insights.map((insight, i) => (
                <div className="insight-item" key={i}>
                  <span className="insight-icon" aria-hidden="true">
                    i
                  </span>
                  <span>{insight}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="card">
              <div className="empty-state">No insights available for the current selection.</div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
