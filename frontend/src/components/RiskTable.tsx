import { useMemo, useState } from 'react';

import type { Risk } from '../api/types';
import { ratingRank, statusRank } from '../utils/colors';
import { countdownState, formatDate, formatDateTime } from '../utils/format';
import { RatingBadge, StatusBadge } from './Badges';

type SortKey = 'code' | 'rating' | 'status' | 'owner' | 'sla';

interface RiskTableProps {
  risks: Risk[];
  onSelect: (risk: Risk) => void;
}

function compare(a: Risk, b: Risk, key: SortKey, dir: 'asc' | 'desc'): number {
  let va: string | number;
  let vb: string | number;
  switch (key) {
    case 'rating':
      va = ratingRank(a.risk_rating);
      vb = ratingRank(b.risk_rating);
      break;
    case 'status':
      va = statusRank(a.status);
      vb = statusRank(b.status);
      break;
    case 'owner':
      va = a.owner_user_id ?? 999_999;
      vb = b.owner_user_id ?? 999_999;
      break;
    case 'sla':
      va = a.sla_deadline ?? '9999-12-31';
      vb = b.sla_deadline ?? '9999-12-31';
      break;
    default:
      va = a.risk_code;
      vb = b.risk_code;
  }
  const cmp = va < vb ? -1 : va > vb ? 1 : 0;
  return dir === 'asc' ? cmp : -cmp;
}

export function RiskTable({ risks, onSelect }: RiskTableProps) {
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [ratingFilter, setRatingFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('code');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');

  const categories = useMemo(
    () =>
      [...new Set(risks.map((r) => r.category).filter((c): c is string => c !== null))].sort(),
    [risks],
  );

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = risks.filter((r) => {
      if (q) {
        const hay = [r.risk_code, r.description, r.category, r.subcategory, r.source]
          .filter(Boolean)
          .join(' ')
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (statusFilter && r.status !== statusFilter) return false;
      if (ratingFilter && r.risk_rating !== ratingFilter) return false;
      if (categoryFilter && r.category !== categoryFilter) return false;
      return true;
    });
    return filtered.sort((a, b) => compare(a, b, sortKey, sortDir));
  }, [risks, query, statusFilter, ratingFilter, categoryFilter, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  }

  const sortIndicator = (key: SortKey) => (sortKey === key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : '');

  return (
    <div>
      <div className="toolbar">
        <input
          className="search-input"
          type="search"
          placeholder="Search code, description, category…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          {[...new Set(risks.map((r) => r.status))].map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select value={ratingFilter} onChange={(e) => setRatingFilter(e.target.value)}>
          <option value="">All ratings</option>
          <option value="High">High</option>
          <option value="Medium">Medium</option>
          <option value="Low">Low</option>
        </select>
        <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="sortable" onClick={() => toggleSort('code')}>
                Code{sortIndicator('code')}
              </th>
              <th>Description</th>
              <th>Category</th>
              <th>Likelihood</th>
              <th>Impact</th>
              <th className="sortable" onClick={() => toggleSort('rating')}>
                Rating{sortIndicator('rating')}
              </th>
              <th className="sortable" onClick={() => toggleSort('status')}>
                Status{sortIndicator('status')}
              </th>
              <th className="sortable" onClick={() => toggleSort('owner')}>
                Owner{sortIndicator('owner')}
              </th>
              <th className="sortable" onClick={() => toggleSort('sla')}>
                SLA deadline{sortIndicator('sla')}
              </th>
              <th>Risk start</th>
              <th>Risk end</th>
              <th>Project life cycle</th>
              <th>Response strategy</th>
              <th>Response plan</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((risk) => {
              const cd = countdownState(risk);
              return (
                <tr key={risk.id} onClick={() => onSelect(risk)}>
                  <td className="mono">{risk.risk_code}</td>
                  <td className="cell-ellipsis" title={risk.description}>
                    {risk.description}
                  </td>
                  <td>{risk.category ?? '—'}</td>
                  <td>{risk.likelihood}</td>
                  <td>{risk.impact}</td>
                  <td>
                    <RatingBadge rating={risk.risk_rating} />
                  </td>
                  <td>
                    <StatusBadge status={risk.status} />
                  </td>
                  <td>{risk.owner_user_id !== null ? `User #${risk.owner_user_id}` : '—'}</td>
                  <td>
                    <span className={`tone-${cd.tone}`} title={cd.label}>
                      {formatDateTime(risk.sla_deadline)}
                    </span>
                  </td>
                  <td>{formatDate(risk.risk_start_date)}</td>
                  <td>{formatDate(risk.risk_end_date)}</td>
                  <td>{risk.identified_during ?? '—'}</td>
                  <td>{risk.response_strategy ?? '—'}</td>
                  <td className="cell-ellipsis" title={risk.response_plan ?? ''}>
                    {risk.response_plan ?? '—'}
                  </td>
                  <td>{risk.source ?? '—'}</td>
                </tr>
              );
            })}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={15} className="empty-state">
                  No risks match the current filters.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
