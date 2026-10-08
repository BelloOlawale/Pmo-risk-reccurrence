// Mirrors of the backend risk-status transition rules, used by the UI to offer
// only valid next statuses (the backend re-validates authoritatively).

export const ALLOWED_TRANSITIONS: Record<string, string[]> = {
  Suggested: ['Open', 'Dismissed'],
  Open: ['In Progress', 'Escalated', 'Event', 'Pending Resolution'],
  'In Progress': ['Escalated', 'Event', 'Pending Resolution'],
  Escalated: ['In Progress', 'Event', 'Pending Resolution'],
  Event: ['Pending Resolution'],
  'Pending Resolution': ['Resolved', 'In Progress'],
  Resolved: ['Closed'],
  Closed: [],
  Dismissed: [],
};

export function allowedTransitions(status: string): string[] {
  return ALLOWED_TRANSITIONS[status] ?? [];
}

/** Statuses that count as "active" — still being managed, not yet resolved/closed. */
export const ACTIVE_STATUSES = new Set([
  'Suggested',
  'Open',
  'In Progress',
  'Escalated',
  'Event',
  'Pending Resolution',
]);

export function isActiveStatus(status: string): boolean {
  return ACTIVE_STATUSES.has(status);
}
