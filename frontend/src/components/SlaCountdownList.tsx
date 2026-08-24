import type { Risk } from '../api/types';
import { countdownState } from '../utils/format';
import { RatingBadge } from './Badges';

interface SlaCountdownListProps {
  risks: Risk[];
  onSelect: (risk: Risk) => void;
}

/** Risks with an active SLA deadline, ordered soonest-first with urgency. */
export function SlaCountdownList({ risks, onSelect }: SlaCountdownListProps) {
  const rows = risks
    .filter(
      (r) =>
        r.sla_deadline !== null &&
        !r.sla_acknowledged &&
        ['Open', 'In Progress', 'Escalated'].includes(r.status),
    )
    .map((risk) => ({ risk, deadlineMs: new Date(risk.sla_deadline!).getTime() }))
    .sort((a, b) => a.deadlineMs - b.deadlineMs);

  if (rows.length === 0) {
    return <div className="empty-state">No active SLA deadlines.</div>;
  }

  return (
    <div className="sla-list">
      {rows.map(({ risk }) => {
        const cd = countdownState(risk);
        return (
          <div key={risk.id} className="sla-row" onClick={() => onSelect(risk)}>
            <span className="mono">{risk.risk_code}</span>
            <RatingBadge rating={risk.risk_rating} />
            <span className="cell-ellipsis" title={risk.description}>
              {risk.description}
            </span>
            <span className={`sla-countdown tone-${cd.tone}`}>{cd.label}</span>
          </div>
        );
      })}
    </div>
  );
}
