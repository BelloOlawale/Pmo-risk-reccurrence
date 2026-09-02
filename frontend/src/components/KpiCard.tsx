export interface KpiCardProps {
  label: string;
  value: string | number;
  hint?: string;
  tone?: 'default' | 'danger' | 'warning' | 'success' | 'info';
}

const TONE_COLORS: Record<NonNullable<KpiCardProps['tone']>, string> = {
  default: 'var(--text)',
  danger: 'var(--danger)',
  warning: 'var(--warning)',
  success: 'var(--success)',
  info: 'var(--info)',
};

export function KpiCard({ label, value, hint, tone = 'default' }: KpiCardProps) {
  return (
    <div className={`kpi${tone !== 'default' ? ` kpi-${tone}` : ''}`}>
      <div className="kpi-label">
        {tone !== 'default' ? (
          <span className="kpi-dot" style={{ background: TONE_COLORS[tone] }} />
        ) : null}
        {label}
      </div>
      <div className="kpi-value" style={{ color: TONE_COLORS[tone] }}>
        {value}
      </div>
      {hint ? <div className="kpi-hint">{hint}</div> : null}
    </div>
  );
}
