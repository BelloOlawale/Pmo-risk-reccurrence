// Shared colour / label vocabulary for statuses and ratings.
// Uses Wragby brand colors for corporate elements, and semantic colors for risk indicators.

// ================================================================
// BRAND COLORS — Wragby Corporate Identity
// ================================================================
export const BRAND = {
  red: '#ED1C2E',        // Wragby Red - brand accent
  redDark: '#C41624',
  redMuted: '#E14B57',   // Softer red - secondary/structural accents
  // Grey — neutral open/active status, kept distinct from the red risk palette
  grey: '#64748B',
  greyDark: '#475569',
  greyMid: '#94A3B8',
  greyLight: '#CBD5E1',
} as const;

// ================================================================
// RISK SEVERITY — Semantic colors (separate from brand)
// These are intentionally different from brand colors to maintain
// risk semantics: High = Red, Medium = Orange, Low = Green
// ================================================================
export const RATING_COLORS: Record<string, string> = {
  High: '#DC2626',     // Red - critical risk
  Medium: '#F97316',   // Orange - medium risk
  Low: '#16A34A',      // Green - low risk
};

/** Semantic colours for the portfolio status-group donut. */
export const STATUS_GROUP_COLORS: Record<string, string> = {
  Open: BRAND.grey,
  'In Progress': '#F59E0B',
  'Resolved/Closed': '#22C55E',
};

export const RATING_ORDER = ['High', 'Medium', 'Low'] as const;

// ================================================================
// STATUS COLORS
// ================================================================
export const STATUS_COLORS: Record<string, string> = {
  Active: BRAND.grey,
  Suggested: '#9CA3AF',
  Open: BRAND.grey,
  'In Progress': '#0891B2',
  Escalated: BRAND.red,       // Red accent for escalated status
  Event: '#F59E0B',
  Resolved: '#16A34A',
  Closed: '#64748B',
  Dismissed: '#64748B',
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
  return STATUS_COLORS[status] ?? '#9CA3AF';
}

export function ratingColor(rating: string): string {
  return RATING_COLORS[rating] ?? '#9CA3AF';
}

export function ratingRank(rating: string): number {
  const idx = RATING_ORDER.indexOf(rating as (typeof RATING_ORDER)[number]);
  return idx === -1 ? 99 : idx;
}

export function statusRank(status: string): number {
  const idx = STATUS_ORDER.indexOf(status as (typeof STATUS_ORDER)[number]);
  return idx === -1 ? 99 : idx;
}
