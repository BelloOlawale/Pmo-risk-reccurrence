// Mirrors of the backend risk-status transition rules, used by the UI to offer
// only valid next statuses (the backend re-validates authoritatively).

export const ALLOWED_TRANSITIONS: Record<string, string[]> = {
  Suggested: ['Open', 'Dismissed'],
  Open: ['In Progress', 'Escalated', 'Event', 'Resolved'],
  'In Progress': ['Escalated', 'Event', 'Resolved'],
  Escalated: ['In Progress', 'Event', 'Resolved'],
  Event: ['Resolved'],
  Resolved: ['Closed'],
  Closed: [],
  Dismissed: [],
};

export function allowedTransitions(status: string): string[] {
  return ALLOWED_TRANSITIONS[status] ?? [];
}
