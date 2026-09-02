import { useState, type ReactNode } from 'react';

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
  collapsible = false,
  defaultCollapsed = false,
  children,
}: {
  title: string;
  actions?: ReactNode;
  collapsible?: boolean;
  defaultCollapsed?: boolean;
  children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const isCollapsed = collapsible && collapsed;

  return (
    <div className="card">
      <div
        className={`card-header${collapsible ? ' card-header-toggle' : ''}`}
        onClick={collapsible ? () => setCollapsed((c) => !c) : undefined}
      >
        <span className="card-header-title">
          {collapsible ? (
            <span className="expand-indicator">{isCollapsed ? '▸' : '▾'}</span>
          ) : null}
          {title}
        </span>
        {actions ? (
          <span className="card-header-actions" onClick={(e) => e.stopPropagation()}>
            {actions}
          </span>
        ) : null}
      </div>
      {!isCollapsed ? <div className="card-body">{children}</div> : null}
    </div>
  );
}
