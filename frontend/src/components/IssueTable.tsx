import { useMemo, useState } from 'react';

import type { Issue, User } from '../api/types';
import { ownerName, useUsers } from '../api/users';
import { ratingRank, statusLabel } from '../utils/colors';
import { formatDate, formatDateTime } from '../utils/format';
import { RatingBadge, StatusBadge } from './Badges';

type SortKey = 'code' | 'rating' | 'status' | 'owner' | 'date';

interface IssueTableProps {
  issues: Issue[];
  onSelect: (issue: Issue) => void;
}

function compare(a: Issue, b: Issue, key: SortKey, dir: 'asc' | 'desc'): number {
  let va: string | number;
  let vb: string | number;
  switch (key) {
    case 'rating':
      va = ratingRank(a.risk_rating);
      vb = ratingRank(b.risk_rating);
      break;
    case 'status':
      va = a.status;
      vb = b.status;
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
      va = a.issue_code;
      vb = b.issue_code;
  }
  const cmp = va < vb ? -1 : va > vb ? 1 : 0;
  return dir === 'asc' ? cmp : -cmp;
}

export function IssueTable({ issues, onSelect }: IssueTableProps) {
  const users = useUsers();
  const [sortKey, setSortKey] = useState<SortKey>('date');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const rows = useMemo(
    () => [...issues].sort((a, b) => compare(a, b, sortKey, sortDir)),
    [issues, sortKey, sortDir],
  );

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
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th className="expand-cell" aria-label="Expand" />
            <th className="sortable" onClick={() => toggleSort('code')}>
              Issue{sortIndicator('code')}
            </th>
            <th>Description</th>
            <th className="col-hide-md">Source risk</th>
            <th className="sortable col-hide-sm" onClick={() => toggleSort('rating')}>
              Rating{sortIndicator('rating')}
            </th>
            <th className="sortable" onClick={() => toggleSort('status')}>
              Status{sortIndicator('status')}
            </th>
            <th className="sortable col-hide-sm" onClick={() => toggleSort('owner')}>
              Owner{sortIndicator('owner')}
            </th>
            <th className="sortable col-hide-md" onClick={() => toggleSort('date')}>
              Created{sortIndicator('date')}
            </th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((issue) => {
            const isOpen = expanded.has(issue.id);
            return (
              <IssueRow
                key={issue.id}
                issue={issue}
                users={users}
                isOpen={isOpen}
                onSelect={onSelect}
                onToggle={() => toggleExpand(issue.id)}
              />
            );
          })}
          {rows.length === 0 ? (
            <tr>
              <td colSpan={9} className="empty-state">
                No issues yet. Risks that pass their Risk End Date without being resolved
                materialize into Issues automatically.
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

function IssueRow({
  issue,
  users,
  isOpen,
  onSelect,
  onToggle,
}: {
  issue: Issue;
  users: User[];
  isOpen: boolean;
  onSelect: (issue: Issue) => void;
  onToggle: () => void;
}) {
  const secondary: { label: string; value: string }[] = [
    { label: 'Category', value: issue.category ?? '—' },
    { label: 'Risk source', value: issue.risk_source ?? '—' },
    { label: 'Likelihood', value: issue.likelihood },
    { label: 'Impact', value: issue.impact },
    { label: 'Project life cycle', value: issue.identified_during ?? '—' },
    { label: 'Response strategy', value: issue.response_strategy ?? '—' },
    { label: 'Response plan', value: issue.response_plan ?? '—' },
    { label: 'Risk start', value: formatDate(issue.risk_start_date) },
    { label: 'Risk end', value: formatDate(issue.risk_end_date) },
    { label: 'Source risk status', value: statusLabel(issue.source_risk_status) },
  ];

  return (
    <>
      <tr className="risk-row" onClick={() => onSelect(issue)}>
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
        <td className="mono">{issue.issue_code}</td>
        <td className="cell-ellipsis risk-desc-cell" title={issue.description}>
          {issue.description}
        </td>
        <td className="col-hide-md mono">{issue.source_risk_code}</td>
        <td className="col-hide-sm">
          <RatingBadge rating={issue.risk_rating} />
        </td>
        <td>
          <StatusBadge status={issue.status} />
        </td>
        <td className="col-hide-sm">{ownerName(users, issue.owner_user_id)}</td>
        <td className="col-hide-md">{formatDateTime(issue.created_at)}</td>
        <td>
          <button
            className="link-btn"
            onClick={(e) => {
              e.stopPropagation();
              onSelect(issue);
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
