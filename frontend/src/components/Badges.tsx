import type { ReactNode } from 'react';

import { ratingColor, statusColor, statusLabel } from '../utils/colors';

function tint(hex: string, alpha: string): string {
  return `${hex}${alpha}`;
}

export function RatingBadge({ rating }: { rating: string }) {
  const color = ratingColor(rating);
  return (
    <span
      className="badge"
      style={{ color, backgroundColor: tint(color, '1a'), borderColor: tint(color, '55') }}
    >
      <span className="badge-dot" />
      {rating}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const color = statusColor(status);
  return (
    <span
      className="badge"
      style={{ color, backgroundColor: tint(color, '1a'), borderColor: tint(color, '55') }}
    >
      <span className="badge-dot" />
      {statusLabel(status)}
    </span>
  );
}

export function SectionCard({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="card">
      <div className="card-header">
        <span>{title}</span>
        {actions}
      </div>
      <div className="card-body">{children}</div>
    </div>
  );
}
