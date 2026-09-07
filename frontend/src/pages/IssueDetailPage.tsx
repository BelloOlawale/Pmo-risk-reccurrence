import { Link, useParams, useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import type { Issue } from '../api/types';
import { RatingBadge, SectionCard, StatusBadge } from '../components/Badges';
import { useApi } from '../hooks/useApi';
import { statusLabel } from '../utils/colors';
import { formatDate, formatDateTime } from '../utils/format';

function ownerLabel(ownerUserId: number | null): string {
  return ownerUserId !== null ? `User #${ownerUserId}` : 'Unassigned';
}

export function IssueDetailPage() {
  const { issueId } = useParams();
  const [searchParams] = useSearchParams();
  const from = searchParams.get('from') === 'risk-history' ? 'risk-history' : 'active-risk';
  const id = Number(issueId);

  const { data: issue, error } = useApi(() => api.get<Issue>(`/api/issues/${id}`), [id]);

  if (!Number.isFinite(id) || id <= 0) {
    return <div className="error-banner">Invalid issue id.</div>;
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <Link to={`/${from}/${issue?.project_id ?? ''}`} className="muted">
            ← Back to {issue ? issue.project_name : 'project'}
          </Link>
          <h1 style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="mono">{issue?.issue_code ?? 'Issue'}</span>
            {issue ? <StatusBadge status={issue.status} /> : null}
            {issue ? <RatingBadge rating={issue.risk_rating} /> : null}
          </h1>
          <div className="subtitle">
            {issue ? (
              <>
                Raised from risk <span className="mono">{issue.source_risk_code}</span> ·{' '}
                {issue.project_name}
              </>
            ) : (
              'Loading…'
            )}
          </div>
        </div>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}

      {issue ? (
        <>
          <div className="materialized-banner">
            <strong>Materialized risk</strong> — this issue was created automatically when risk{' '}
            <span className="mono">{issue.source_risk_code}</span> passed its Risk End Date (
            {formatDate(issue.risk_end_date)}) without being resolved. The originating risk remains
            in the register as the historical record.
          </div>

          <div className="detail-grid">
            <div className="stack">
              <SectionCard title="Issue description">
                <p className="mt-0">{issue.description}</p>
              </SectionCard>

              <SectionCard title="Issue details">
                <div className="key-value">
                  <div>
                    <div className="kv-label">Source risk</div>
                    <div className="kv-value">
                      <Link
                        to={`/risks/${issue.source_risk_id}?from=${from}`}
                        className="mono"
                      >
                        {issue.source_risk_code}
                      </Link>
                    </div>
                  </div>
                  <div>
                    <div className="kv-label">Source risk status</div>
                    <div className="kv-value">
                      <StatusBadge status={issue.source_risk_status} />
                    </div>
                  </div>
                  <div>
                    <div className="kv-label">Status</div>
                    <div className="kv-value">{statusLabel(issue.status)}</div>
                  </div>
                  <div>
                    <div className="kv-label">Project / Risk Register</div>
                    <div className="kv-value">
                      <Link to={`/${from}/${issue.project_id}`}>{issue.project_name}</Link>
                    </div>
                  </div>
                  <div>
                    <div className="kv-label">Category</div>
                    <div className="kv-value">{issue.category ?? '—'}</div>
                  </div>
                  <div>
                    <div className="kv-label">Risk source</div>
                    <div className="kv-value">{issue.risk_source ?? '—'}</div>
                  </div>
                  <div>
                    <div className="kv-label">Likelihood</div>
                    <div className="kv-value">{issue.likelihood}</div>
                  </div>
                  <div>
                    <div className="kv-label">Impact</div>
                    <div className="kv-value">{issue.impact}</div>
                  </div>
                  <div>
                    <div className="kv-label">Owner</div>
                    <div className="kv-value">{ownerLabel(issue.owner_user_id)}</div>
                  </div>
                  <div>
                    <div className="kv-label">Project life cycle</div>
                    <div className="kv-value">{issue.identified_during ?? '—'}</div>
                  </div>
                  <div>
                    <div className="kv-label">Risk start</div>
                    <div className="kv-value">{formatDate(issue.risk_start_date)}</div>
                  </div>
                  <div>
                    <div className="kv-label">Risk end</div>
                    <div className="kv-value">{formatDate(issue.risk_end_date)}</div>
                  </div>
                  <div>
                    <div className="kv-label">Created</div>
                    <div className="kv-value">{formatDateTime(issue.created_at)}</div>
                  </div>
                </div>

                {issue.response_strategy ? (
                  <div className="mt-20">
                    <div className="kv-label">Response strategy</div>
                    <div className="kv-value">{issue.response_strategy}</div>
                  </div>
                ) : null}
                {issue.response_plan ? (
                  <div className="mt-20">
                    <div className="kv-label">Response plan</div>
                    <div className="kv-value">{issue.response_plan}</div>
                  </div>
                ) : null}
              </SectionCard>
            </div>

            <div className="stack">
              <SectionCard title="Source risk">
                <div className="key-value">
                  <div>
                    <div className="kv-label">Risk</div>
                    <div className="kv-value">
                      <Link
                        to={`/risks/${issue.source_risk_id}?from=${from}`}
                        className="mono"
                      >
                        {issue.source_risk_code}
                      </Link>
                    </div>
                  </div>
                  <div>
                    <div className="kv-label">Status</div>
                    <div className="kv-value">
                      <StatusBadge status={issue.source_risk_status} />
                    </div>
                  </div>
                  <div>
                    <div className="kv-label">Risk rating</div>
                    <div className="kv-value">
                      <RatingBadge rating={issue.risk_rating} />
                    </div>
                  </div>
                </div>
                <div className="mt-20">
                  <Link to={`/risks/${issue.source_risk_id}?from=${from}`} className="btn">
                    Open original risk
                  </Link>
                </div>
              </SectionCard>
            </div>
          </div>
        </>
      ) : (
        !error && <div className="loading">Loading issue…</div>
      )}
    </div>
  );
}
