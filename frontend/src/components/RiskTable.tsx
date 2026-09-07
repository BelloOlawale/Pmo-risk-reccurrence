import { useMemo, useState } from 'react';

import type { Risk } from '../api/types';
import { ratingRank, statusRank } from '../utils/colors';
import { formatDate } from '../utils/format';
import { RatingBadge, StatusBadge } from './Badges';

type SortKey = 'code' | 'rating' | 'status' | 'owner' | 'date';

interface RiskTableProps {
  risks: Risk[];
  onSelect: (risk: Risk) => void;
  /** Show the search/filter toolbar. Hidden when the table is embedded per-register. */
  showToolbar?: boolean;
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
    case 'date':
      va = new Date(a.created_at).getTime();
      vb = new Date(b.created_at).getTime();
      if (va === vb) {
        va = a.id;
        vb = b.id;
      }
      break;
    default:
      va = a.risk_code;
      vb = b.risk_code;
  }
  const cmp = va < vb ? -1 : va > vb ? 1 : 0;
  return dir === 'asc' ? cmp : -cmp;
}

function ownerLabel(ownerUserId: number | null): string {
  return ownerUserId !== null ? `User #${ownerUserId}` : 'Unassigned';
}

export function RiskTable({ risks, onSelect, showToolbar = true }: RiskTableProps) {
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [ratingFilter, setRatingFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('date');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const categories = useMemo(
    () =>
      [...new Set(risks.map((r) => r.category).filter((c): c is string => c !== null))].sort(),
    [risks],
  );

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = risks.filter((r) => {
      if (q) {
        const hay = [r.risk_code, r.description, r.category, r.source]
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

  function toggleExpand(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const sortIndicator = (key: SortKey) => (sortKey === key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : '');

  return (
    <div>
      {showToolbar ? (
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
      ) : null}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="expand-cell" aria-label="Expand" />
              <th className="sortable" onClick={() => toggleSort('code')}>
                Code{sortIndicator('code')}
              </th>
              <th>Description</th>
              <th className="sortable" onClick={() => toggleSort('rating')}>
                Rating{sortIndicator('rating')}
              </th>
              <th className="sortable" onClick={() => toggleSort('status')}>
                Status{sortIndicator('status')}
              </th>
              <th className="sortable col-hide-sm" onClick={() => toggleSort('owner')}>
                Owner{sortIndicator('owner')}
              </th>
              <th className="col-hide-md">Risk start</th>
              <th className="col-hide-md">Risk end</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((risk) => {
              const isOpen = expanded.has(risk.id);
              return (
                <RiskRow
                  key={risk.id}
                  risk={risk}
                  isOpen={isOpen}
                  onSelect={onSelect}
                  onToggle={() => toggleExpand(risk.id)}
                />
              );
            })}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={9} className="empty-state">
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

function RiskRow({
  risk,
  isOpen,
  onSelect,
  onToggle,
}: {
  risk: Risk;
  isOpen: boolean;
  onSelect: (risk: Risk) => void;
  onToggle: () => void;
}) {
  const secondary: { label: string; value: string }[] = [
    { label: 'Category', value: risk.category ?? '—' },
    { label: 'Likelihood', value: risk.likelihood },
    { label: 'Impact', value: risk.impact },
    { label: 'Project life cycle', value: risk.identified_during ?? '—' },
    { label: 'Response strategy', value: risk.response_strategy ?? '—' },
    { label: 'Response plan', value: risk.response_plan ?? '—' },
    { label: 'Source', value: risk.source ?? '—' },
  ];

  return (
    <>
      <tr className="risk-row" onClick={() => onSelect(risk)}>
        <td className="expand-cell">
          <button
            className="expand-btn"
            onClick={(e) => {
              e.stopPropagation();
              onToggle();
            }}
            aria-label={isOpen ? 'Hide details' : 'Show details'}
            aria-expanded={isOpen}
            title={isOpen ? 'Hide details' : 'Show details'}
          >
            {isOpen ? '▾' : '▸'}
          </button>
        </td>
        <td className="mono">{risk.risk_code}</td>
        <td className="cell-ellipsis risk-desc-cell" title={risk.description}>
          {risk.description}
        </td>
        <td>
          <RatingBadge rating={risk.risk_rating} />
        </td>
        <td>
          <StatusBadge status={risk.status} />
        </td>
        <td className="col-hide-sm">{ownerLabel(risk.owner_user_id)}</td>
        <td className="col-hide-md">{formatDate(risk.risk_start_date)}</td>
        <td className="col-hide-md">{formatDate(risk.risk_end_date)}</td>
        <td>
          <button
            className="link-btn"
            onClick={(e) => {
              e.stopPropagation();
              onSelect(risk);
            }}
          >
            View
          </button>
        </td>
      </tr>
      {isOpen ? (
        <tr className="expanded-row">
          <td colSpan={9}>
            <div className="risk-detail-panel">
              {secondary.map((item) => (
                <div key={item.label}>
                  <div className="kv-label">{item.label}</div>
                  <div className="kv-value">{item.value}</div>
                </div>
              ))}
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}
