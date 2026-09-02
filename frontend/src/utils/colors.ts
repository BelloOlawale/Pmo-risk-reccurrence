// Shared colour / label vocabulary for statuses and ratings, used by both the
// badges and the ECharts visualisations so they never drift apart.

export const RATING_COLORS: Record<string, string> = {
  High: '#ef4444',
  Medium: '#f59e0b',
  Low: '#22c55e',
};

export const RATING_ORDER = ['High', 'Medium', 'Low'] as const;

export const STATUS_COLORS: Record<string, string> = {
  Active: '#3b82f6',
  Suggested: '#94a3b8',
  Open: '#3b82f6',
  'In Progress': '#8b5cf6',
  Escalated: '#ef4444',
  Event: '#f59e0b',
  Resolved: '#22c55e',
  Closed: '#64748b',
  Dismissed: '#64748b',
};

export const STATUS_ORDER = [
  'Suggested',
  'Open',
  'In Progress',
  'Escalated',
  'Event',
  'Resolved',
  'Closed',
  'Dismissed',
] as const;

/** User-facing label overrides (the backend renders "Event" as "Materialized"). */
const STATUS_LABELS: Record<string, string> = {
  Event: 'Materialized',
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? '#94a3b8';
}

export function ratingColor(rating: string): string {
  return RATING_COLORS[rating] ?? '#94a3b8';
}

export function ratingRank(rating: string): number {
  const idx = RATING_ORDER.indexOf(rating as (typeof RATING_ORDER)[number]);
  return idx === -1 ? 99 : idx;
}

export function statusRank(status: string): number {
  const idx = STATUS_ORDER.indexOf(status as (typeof STATUS_ORDER)[number]);
  return idx === -1 ? 99 : idx;
}
