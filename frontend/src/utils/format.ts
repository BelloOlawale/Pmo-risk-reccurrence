import type { Risk } from '../api/types';

export type Tone = 'danger' | 'warning' | 'ok' | 'muted';

const DATE_FMT = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
});

const DATETIME_FMT = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return DATE_FMT.format(d);
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return DATETIME_FMT.format(d);
}

export function formatPercent(value: number): string {
  if (!Number.isFinite(value)) return '—';
  return `${Math.round(value)}%`;
}

/** SLA warning window (hours) per rating, per SPEC §6. */
export function warningHours(rating: string): number {
  switch (rating) {
    case 'High':
      return 4;
    case 'Medium':
      return 12;
    case 'Low':
      return 24;
    default:
      return 12;
  }
}

export function humanizeDuration(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m`;
  return `${seconds}s`;
}

export interface Countdown {
  label: string;
  tone: Tone;
}

/** Human-friendly SLA countdown state for a risk. */
export function countdownState(risk: Risk): Countdown {
  if (!risk.sla_deadline) return { label: 'No deadline', tone: 'muted' };
  if (risk.sla_acknowledged) return { label: 'Satisfied', tone: 'ok' };

  const deadline = new Date(risk.sla_deadline).getTime();
  const diff = deadline - Date.now();

  if (diff <= 0) {
    return { label: `Breached ${humanizeDuration(-diff)} ago`, tone: 'danger' };
  }
  const warningMs = warningHours(risk.risk_rating) * 3_600_000;
  if (diff <= warningMs) {
    return { label: `Due in ${humanizeDuration(diff)}`, tone: 'warning' };
  }
  return { label: `Due in ${humanizeDuration(diff)}`, tone: 'ok' };
}
