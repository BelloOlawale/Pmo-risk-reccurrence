import type { Project, Risk } from '../api/types';
import { RATING_ORDER, STATUS_ORDER } from './colors';

export function uniq<T>(items: T[]): T[] {
  return [...new Set(items)];
}

export interface Kpis {
  total: number;
  high: number;
  escalated: number;
  slaCompliance: number;
}

export interface RatingSlice {
  name: string;
  value: number;
}

export interface StackData {
  categories: string[];
  series: { name: string; data: number[] }[];
}

export interface NameValue {
  name: string;
  value: number;
}

export function isActiveStatus(status: string): boolean {
  return status !== 'Closed' && status !== 'Dismissed' && status !== 'Resolved';
}

/** KPI cards for the project dashboard. */
export function computeKpis(risks: Risk[]): Kpis {
  const total = risks.length;
  const high = risks.filter((r) => r.risk_rating === 'High').length;
  const escalated = risks.filter((r) => r.status === 'Escalated').length;

  const withDeadline = risks.filter((r) => r.sla_deadline !== null);
  const compliant = withDeadline.filter((r) => {
    if (r.sla_acknowledged) return true;
    const deadline = new Date(r.sla_deadline!).getTime();
    return deadline > Date.now();
  }).length;
  const slaCompliance =
    withDeadline.length === 0 ? 100 : (compliant / withDeadline.length) * 100;

  return { total, high, escalated, slaCompliance };
}

/** Donut data: risk count per rating. */
export function ratingDistribution(risks: Risk[]): RatingSlice[] {
  return RATING_ORDER.map((name) => ({
    name,
    value: risks.filter((r) => r.risk_rating === name).length,
  })).filter((slice) => slice.value > 0);
}

/** Stacked bar: x = status, stacked segments = rating. */
export function statusStack(risks: Risk[]): StackData {
  const statuses = STATUS_ORDER.filter((s) => risks.some((r) => r.status === s));
  const series = RATING_ORDER.map((name) => ({
    name,
    data: statuses.map(
      (status) =>
        risks.filter((r) => r.status === status && r.risk_rating === name).length,
    ),
  })).filter((s) => s.data.some((n) => n > 0));

  return { categories: [...statuses], series };
}

/** Treemap data: risk count per category. */
export function categoryTreemap(risks: Risk[]): NameValue[] {
  const counts = new Map<string, number>();
  for (const risk of risks) {
    const category = risk.category ?? 'Uncategorized';
    counts.set(category, (counts.get(category) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
}

/** Portfolio KPI cards. */
export function computePortfolioKpis(projects: Project[], risks: Risk[]) {
  const open = risks.filter((r) => isActiveStatus(r.status)).length;
  const escalated = risks.filter((r) => r.status === 'Escalated').length;

  const withDeadline = risks.filter((r) => r.sla_deadline !== null);
  const compliant = withDeadline.filter((r) => {
    if (r.sla_acknowledged) return true;
    return new Date(r.sla_deadline!).getTime() > Date.now();
  }).length;
  const slaCompliance =
    withDeadline.length === 0 ? 100 : (compliant / withDeadline.length) * 100;

  return {
    projects: projects.length,
    risks: risks.length,
    open,
    escalated,
    slaCompliance,
    withDeadline: withDeadline.length,
    high: risks.filter((r) => r.risk_rating === 'High').length,
  };
}

/** Projects ordered by their risk count (descending), ties broken by id. */
export function projectsByRisk(projects: Project[], risks: Risk[]): Project[] {
  const counts = new Map<number, number>();
  for (const r of risks) {
    counts.set(r.project_id, (counts.get(r.project_id) ?? 0) + 1);
  }
  return [...projects].sort(
    (a, b) => (counts.get(b.id) ?? 0) - (counts.get(a.id) ?? 0) || a.id - b.id,
  );
}

/** Risk-by-project bar (stacked by rating): categories = project codes. */
export function riskByProject(
  projects: Project[],
  risks: Risk[],
  maxProjects = 10,
): StackData {
  const shown = projectsByRisk(projects, risks).slice(0, maxProjects);
  const names = shown.map((p) => p.project_code);
  const series = RATING_ORDER.map((name) => ({
    name,
    data: shown.map(
      (p) =>
        risks.filter((r) => r.project_id === p.id && r.risk_rating === name).length,
    ),
  })).filter((s) => s.data.some((n) => n > 0));
  return { categories: names, series };
}

export interface HeatmapData {
  categories: string[];
  projects: string[];
  data: [number, number, number][];
}

/**
 * Project × category heatmap: value = number of risks in that cell.
 *
 * Projects are limited to the top ``maxProjects`` by risk count, and categories
 * are grouped to the top ``maxCategories`` plus an ``Other`` bucket so the
 * matrix stays readable instead of rendering dozens of sparsely-populated
 * columns.
 */
export function heatmapData(
  projects: Project[],
  risks: Risk[],
  opts: { maxProjects?: number; maxCategories?: number } = {},
): HeatmapData {
  const maxProjects = opts.maxProjects ?? 12;
  const maxCategories = opts.maxCategories ?? 6;

  // Highest-risk projects at the top (y-axis renders first item at the bottom).
  const shownProjects = projectsByRisk(projects, risks)
    .slice(0, maxProjects)
    .reverse();

  // Group categories: top N by volume, everything else into "Other".
  const catCounts = new Map<string, number>();
  for (const r of risks) {
    const cat = r.category ?? 'Uncategorized';
    catCounts.set(cat, (catCounts.get(cat) ?? 0) + 1);
  }
  const sortedCats = [...catCounts.entries()].sort((a, b) => b[1] - a[1]);
  const topCats = sortedCats.slice(0, maxCategories).map(([c]) => c);
  const categories = sortedCats.length > maxCategories ? [...topCats, 'Other'] : topCats;

  const categoryIndex = new Map(categories.map((c, i) => [c, i]));
  const projectIndex = new Map(shownProjects.map((p, i) => [p.id, i]));

  const cells = new Map<string, number>();
  for (const r of risks) {
    const yi = projectIndex.get(r.project_id);
    if (yi === undefined) continue;
    const raw = r.category ?? 'Uncategorized';
    const label = categoryIndex.has(raw) ? raw : 'Other';
    const xi = categoryIndex.get(label)!;
    const key = `${xi}:${yi}`;
    cells.set(key, (cells.get(key) ?? 0) + 1);
  }

  const data: [number, number, number][] = [];
  cells.forEach((value, key) => {
    const [x, y] = key.split(':').map(Number);
    data.push([x, y, value]);
  });

  return { categories, projects: shownProjects.map((p) => p.project_code), data };
}

/** Risk count per category, top ``topN`` + an "Other" bucket. */
export function categoryDistribution(risks: Risk[], topN = 10): NameValue[] {
  const counts = new Map<string, number>();
  for (const r of risks) {
    const cat = r.category ?? 'Uncategorized';
    counts.set(cat, (counts.get(cat) ?? 0) + 1);
  }
  const entries = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  if (entries.length <= topN) {
    return entries.map(([name, value]) => ({ name, value }));
  }
  const top = entries.slice(0, topN).map(([name, value]) => ({ name, value }));
  const other = entries.slice(topN).reduce((sum, [, v]) => sum + v, 0);
  return [...top, { name: 'Other', value: other }];
}

/** Escalated vs non-escalated split for a compact donut. */
export function escalatedSplit(risks: Risk[]): NameValue[] {
  const escalated = risks.filter((r) => r.status === 'Escalated').length;
  return [
    { name: 'Escalated', value: escalated },
    { name: 'Not escalated', value: risks.length - escalated },
  ];
}

export interface EscalationTrend {
  months: string[];
  values: number[];
}

/**
 * Escalation trend: number of currently-Escalated risks bucketed by the month
 * their SLA deadline passed (falling back to creation month when absent).
 */
export function escalationTrend(risks: Risk[]): EscalationTrend {
  const buckets = new Map<string, number>();
  for (const risk of risks) {
    if (risk.status !== 'Escalated') continue;
    const anchor = risk.sla_deadline ?? risk.created_at;
    const d = new Date(anchor);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    buckets.set(key, (buckets.get(key) ?? 0) + 1);
  }
  const months = [...buckets.keys()].sort();
  return { months, values: months.map((m) => buckets.get(m) ?? 0) };
}

/** Portfolio-level executive insights, derived strictly from the data. */
export function portfolioInsights(projects: Project[], risks: Risk[]): string[] {
  const insights: string[] = [];
  if (risks.length === 0) return insights;

  const open = risks.filter((r) => isActiveStatus(r.status)).length;
  const escalated = risks.filter((r) => r.status === 'Escalated').length;
  const high = risks.filter((r) => r.risk_rating === 'High').length;

  if (open > 0) {
    insights.push(`${open} open risk${open === 1 ? '' : 's'} require${open === 1 ? 's' : ''} attention.`);
  }
  if (escalated > 0) {
    insights.push(`${escalated} risk${escalated === 1 ? ' is' : 's are'} currently escalated.`);
  }
  if (high > 0) {
    insights.push(`${high} of ${risks.length} risks are rated High.`);
  }

  // Highest-risk (non-null) category.
  const catCounts = new Map<string, number>();
  for (const r of risks) {
    if (!r.category) continue;
    catCounts.set(r.category, (catCounts.get(r.category) ?? 0) + 1);
  }
  const topCat = [...catCounts.entries()].sort((a, b) => b[1] - a[1])[0];
  if (topCat) {
    insights.push(`${topCat[0]} is the highest-risk category across the portfolio (${topCat[1]}).`);
  }

  // Project with the highest concentration of high + escalated risks.
  const concentration = new Map<number, number>();
  for (const r of risks) {
    if (r.risk_rating === 'High' || r.status === 'Escalated') {
      concentration.set(r.project_id, (concentration.get(r.project_id) ?? 0) + 1);
    }
  }
  let worstProject: Project | undefined;
  let worstCount = 0;
  for (const p of projects) {
    const c = concentration.get(p.id) ?? 0;
    if (c > worstCount) {
      worstCount = c;
      worstProject = p;
    }
  }
  if (worstProject && worstCount > 0) {
    insights.push(
      `Project ${worstProject.project_code} has the highest concentration of high and escalated risks (${worstCount}).`,
    );
  }

  return insights;
}

export interface SlaRow {
  risk: Risk;
  deadlineMs: number;
}

/** Risks with an active SLA deadline, sorted soonest-first. */
export function activeSlaRows(risks: Risk[]): SlaRow[] {
  return risks
    .filter(
      (r) =>
        r.sla_deadline !== null &&
        !r.sla_acknowledged &&
        ['Open', 'In Progress', 'Escalated'].includes(r.status),
    )
    .map((risk) => ({ risk, deadlineMs: new Date(risk.sla_deadline!).getTime() }))
    .sort((a, b) => a.deadlineMs - b.deadlineMs);
}
