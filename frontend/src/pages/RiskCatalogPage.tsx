import { useState } from 'react';
import type { FormEvent } from 'react';

import { api, ApiError } from '../api/client';
import type { RiskCatalog, RiskCatalogCreatePayload } from '../api/types';
import { useApi } from '../hooks/useApi';

interface CreateFormState {
  name: string;
  description: string;
  category: string;
  subcategory: string;
  risk_source: string;
}

const EMPTY_CREATE: CreateFormState = {
  name: '',
  description: '',
  category: '',
  subcategory: '',
  risk_source: '',
};

export function RiskCatalogPage() {
  const { data, error, loading, reload } = useApi(() => api.get<RiskCatalog[]>('/api/catalog'));

  const risks = data ?? [];

  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState<CreateFormState>(EMPTY_CREATE);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [mergeSurvivorId, setMergeSurvivorId] = useState('');
  const [mergeAbsorbedId, setMergeAbsorbedId] = useState('');
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  function setCreate<K extends keyof CreateFormState>(key: K, value: string) {
    setCreateForm((f) => ({ ...f, [key]: value }));
  }

  function fail(err: unknown) {
    setActionError(
      err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err),
    );
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setActionError(null);
    if (!createForm.description.trim()) {
      setActionError('Description is required.');
      return;
    }
    const payload: RiskCatalogCreatePayload = {
      name: createForm.name.trim() || null,
      description: createForm.description.trim(),
      category: createForm.category.trim() || null,
      subcategory: createForm.subcategory.trim() || null,
      risk_source: createForm.risk_source || null,
    };
    setBusy(true);
    try {
      await api.post<RiskCatalog>('/api/catalog', payload);
      setCreateForm(EMPTY_CREATE);
      setShowCreate(false);
      reload();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  function startRename(risk: RiskCatalog) {
    setRenamingId(risk.id);
    setRenameValue(risk.name ?? '');
    setActionError(null);
  }

  async function saveRename(riskId: number) {
    setActionError(null);
    setBusy(true);
    try {
      await api.patch<RiskCatalog>(`/api/catalog/${riskId}`, {
        name: renameValue.trim() || null,
      });
      setRenamingId(null);
      reload();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleMerge(e: FormEvent) {
    e.preventDefault();
    setActionError(null);
    const survivorId = Number(mergeSurvivorId);
    const absorbedId = Number(mergeAbsorbedId);
    if (!Number.isFinite(survivorId) || !Number.isFinite(absorbedId)) {
      setActionError('Pick both the entry to keep and the entry to merge into it.');
      return;
    }
    if (survivorId === absorbedId) {
      setActionError('Pick two different entries to merge.');
      return;
    }
    setBusy(true);
    try {
      await api.post<RiskCatalog>('/api/catalog/merge', {
        survivor_id: survivorId,
        absorbed_id: absorbedId,
      });
      setMergeSurvivorId('');
      setMergeAbsorbedId('');
      reload();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Risk Catalog</h1>
          <div className="subtitle">The shared library of risk concepts — reused across projects</div>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? 'Cancel' : '+ Add risk'}
        </button>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}
      {actionError ? <div className="error-banner">{actionError}</div> : null}

      {showCreate ? (
        <div className="card" style={{ maxWidth: 720, marginBottom: 20 }}>
          <div className="card-body">
            <form onSubmit={handleCreate}>
              <div className="form-grid">
                <div className="field">
                  <label>Short name</label>
                  <input
                    value={createForm.name}
                    onChange={(e) => setCreate('name', e.target.value)}
                    placeholder="e.g. Vendor onboarding"
                  />
                </div>
                <div className="field">
                  <label>Category</label>
                  <input
                    value={createForm.category}
                    onChange={(e) => setCreate('category', e.target.value)}
                  />
                </div>
                <div className="field" style={{ gridColumn: '1 / -1' }}>
                  <label>Description *</label>
                  <textarea
                    value={createForm.description}
                    onChange={(e) => setCreate('description', e.target.value)}
                    placeholder="Describe the risk concept…"
                  />
                </div>
                <div className="field">
                  <label>Subcategory</label>
                  <input
                    value={createForm.subcategory}
                    onChange={(e) => setCreate('subcategory', e.target.value)}
                  />
                </div>
                <div className="field">
                  <label>Risk source</label>
                  <select
                    value={createForm.risk_source}
                    onChange={(e) => setCreate('risk_source', e.target.value)}
                  >
                    <option value="">—</option>
                    <option value="Human">Human</option>
                    <option value="Environmental">Environmental</option>
                    <option value="Technical">Technical</option>
                  </select>
                </div>
              </div>
              <div className="btn-group">
                <button className="btn btn-primary" type="submit" disabled={busy}>
                  {busy ? 'Adding…' : 'Add risk'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {risks.length >= 2 ? (
        <div className="card" style={{ maxWidth: 720, marginBottom: 20 }}>
          <div className="card-body">
            <form onSubmit={handleMerge}>
              <div className="form-grid">
                <div className="field">
                  <label>Keep (surviving entry)</label>
                  <select
                    value={mergeSurvivorId}
                    onChange={(e) => setMergeSurvivorId(e.target.value)}
                  >
                    <option value="">Select…</option>
                    {risks.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name ?? `#${r.id}`} — {r.description}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label>Merge into it (remove)</label>
                  <select
                    value={mergeAbsorbedId}
                    onChange={(e) => setMergeAbsorbedId(e.target.value)}
                  >
                    <option value="">Select…</option>
                    {risks.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name ?? `#${r.id}`} — {r.description}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="btn-group">
                <button className="btn btn-danger" type="submit" disabled={busy}>
                  {busy ? 'Merging…' : 'Merge duplicates'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      <div className="mb-20 muted">
        {risks.length} risk{risks.length === 1 ? '' : 's'} in the catalog
      </div>

      {loading ? (
        <div className="loading">Loading catalog…</div>
      ) : risks.length === 0 ? (
        <div className="card">
          <div className="empty-state">No risks in the catalog yet.</div>
        </div>
      ) : (
        <div className="card table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Description</th>
                <th>Category</th>
                <th>Subcategory</th>
                <th>Risk source</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {risks.map((r) => (
                <tr key={r.id}>
                  <td>
                    {renamingId === r.id ? (
                      <input
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            void saveRename(r.id);
                          }
                          if (e.key === 'Escape') {
                            setRenamingId(null);
                          }
                        }}
                        autoFocus
                      />
                    ) : (
                      r.name ?? '—'
                    )}
                  </td>
                  <td className="cell-ellipsis" title={r.description}>
                    {r.description}
                  </td>
                  <td>{r.category ?? '—'}</td>
                  <td>{r.subcategory ?? '—'}</td>
                  <td>{r.risk_source ?? '—'}</td>
                  <td>
                    {renamingId === r.id ? (
                      <span className="btn-group">
                        <button
                          className="btn btn-sm btn-primary"
                          onClick={() => void saveRename(r.id)}
                          disabled={busy}
                        >
                          Save
                        </button>
                        <button
                          className="btn btn-sm"
                          onClick={() => setRenamingId(null)}
                          disabled={busy}
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button className="btn btn-sm" onClick={() => startRename(r)}>
                        Rename
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
