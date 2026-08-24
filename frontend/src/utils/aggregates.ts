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
  };
}

/** Risk-by-project bar (stacked by rating): x = project, segments = rating. */
export function riskByProject(projects: Project[], risks: Risk[]): StackData {
  const names = projects.map((p) => p.project_code);
  const series = RATING_ORDER.map((name) => ({
    name,
    data: projects.map(
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

/** Project × category heatmap: value = number of risks in that cell. */
export function heatmapData(projects: Project[], risks: Risk[]): HeatmapData {
  const categories = uniq(
    risks.map((r) => r.category).filter((c): c is string => c !== null),
  ).sort();
  const projectNames = projects.map((p) => p.project_code);

  const cells = new Map<string, number>();
  for (const risk of risks) {
    const category = risk.category ?? 'Uncategorized';
    const xi = categories.indexOf(category);
    const yi = projects.findIndex((p) => p.id === risk.project_id);
    if (xi < 0) {
      categories.push(category);
    }
    const x = xi < 0 ? categories.length - 1 : xi;
    const key = `${x}:${yi}`;
    cells.set(key, (cells.get(key) ?? 0) + 1);
  }

  const data: [number, number, number][] = [];
  cells.forEach((value, key) => {
    const [x, y] = key.split(':').map(Number);
    if (y >= 0) data.push([x, y, value]);
  });

  return { categories, projects: projectNames, data };
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
