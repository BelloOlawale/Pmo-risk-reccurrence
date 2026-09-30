import { useMemo, useState } from 'react';

import type { Risk } from '../api/types';
import { ratingRank, statusRank } from '../utils/colors';
import { formatDate } from '../utils/format';
import { RatingBadge, StatusBadge } from './Badges';

type SortKey = 'code' | 'rating' | 'status' | 'owner' | 'date' | 'acknowledged';

const COLUMN_COUNT = 9;

interface RiskTableProps {
  risks: Risk[];
  onSelect: (risk: Risk) => void;
  /** Show the search/filter toolbar. Hidden when the table is embedded per-register. */
  showToolbar?: boolean;
  /**
   * When provided, a Delete action is shown next to View and a confirmation
   * dialog is required before the handler runs. The parent performs the API
   * call and reload (so it can refresh whatever list it owns).
   */
  onDelete?: (risk: Risk) => Promise<void> | void;
  /** Optional per-row gate; defaults to allowing delete whenever onDelete is set. */
  canDelete?: (risk: Risk) => boolean;
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
    case 'acknowledged':
      va = a.sla_acknowledged ? 1 : 0;
      vb = b.sla_acknowledged ? 1 : 0;
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

export function RiskTable({
  risks,
  onSelect,
  showToolbar = true,
  onDelete,
  canDelete,
}: RiskTableProps) {
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [ratingFilter, setRatingFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('date');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [pendingDelete, setPendingDelete] = useState<Risk | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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

  async function confirmDelete() {
    if (!pendingDelete || !onDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await onDelete(pendingDelete);
      setPendingDelete(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleting(false);
    }
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
              <th className="sortable" onClick={() => toggleSort('acknowledged')}>
                Acknowledged{sortIndicator('acknowledged')}
              </th>
              <th className="col-hide-md">Risk start</th>
              <th className="col-hide-md">Risk end</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((risk) => (
              <RiskRow
                key={risk.id}
                risk={risk}
                onSelect={onSelect}
                onDelete={
                  onDelete && (canDelete ? canDelete(risk) : true)
                    ? () => setPendingDelete(risk)
                    : undefined
                }
              />
            ))}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={COLUMN_COUNT} className="empty-state">
                  No risks match the current filters.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {pendingDelete ? (
        <div className="modal-overlay" onClick={() => setPendingDelete(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Delete Risk?</h2>
              <button
                className="btn btn-sm"
                onClick={() => setPendingDelete(null)}
                aria-label="Close"
              >
                ✕
              </button>
            </div>
            <p>
              Are you sure you want to delete <strong>{pendingDelete.risk_code}</strong>? This
              action cannot be undone.
            </p>
            {deleteError ? <div className="error-banner">{deleteError}</div> : null}
            <div className="btn-group">
              <button className="btn" onClick={() => setPendingDelete(null)}>
                Cancel
              </button>
              <button
                className="btn btn-danger"
                disabled={deleting}
                onClick={() => void confirmDelete()}
              >
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function AcknowledgedBadge({ acknowledged }: { acknowledged: boolean }) {
  return (
    <span className={`ack-badge ${acknowledged ? 'ack-yes' : 'ack-no'}`}>
      {acknowledged ? 'Acknowledged' : 'Not Acknowledged'}
    </span>
  );
}

function RiskRow({
  risk,
  onSelect,
  onDelete,
}: {
  risk: Risk;
  onSelect: (risk: Risk) => void;
  onDelete?: () => void;
}) {
  return (
    <tr className="risk-row" onClick={() => onSelect(risk)}>
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
      <td className="col-hide-sm">
        <span className="owner-cell">
          {risk.owner_name ?? 'Unassigned'}
          {risk.owner_type === 'External' ? (
            <span className="owner-type-tag">External</span>
          ) : null}
        </span>
      </td>
      <td>
        <AcknowledgedBadge acknowledged={risk.sla_acknowledged} />
      </td>
      <td className="col-hide-md">{formatDate(risk.risk_start_date)}</td>
      <td className="col-hide-md">{formatDate(risk.risk_end_date)}</td>
      <td>
        <div className="row-actions">
          <button
            className="link-btn"
            onClick={(e) => {
              e.stopPropagation();
              onSelect(risk);
            }}
          >
            View
          </button>
          {onDelete ? (
            <button
              className="link-btn link-btn-danger"
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
            >
              Delete
            </button>
          ) : null}
        </div>
      </td>
    </tr>
  );
}
