import { useMemo, useState } from 'react';
import type { FormEvent } from 'react';

import type { User } from '../api/types';
import { createExternalOwner, userDisplayName, userEmail } from '../api/users';

interface UserPickerProps {
  users: User[];
  /** Currently selected user id, or null for none. */
  selectedUserId: number | null;
  onSelect: (user: User | null) => void;
  placeholder?: string;
  /** Label for the "clear selection" row. */
  noneLabel?: string;
  disabled?: boolean;
  /**
   * Include external (non-Wragby) owners in the list and offer the
   * "+ Add External Risk Owner" action. Off by default so the project-manager
   * picker only ever lists internal colleagues.
   */
  includeExternal?: boolean;
}

const MAX_RESULTS = 50;

/** Everything a user can be searched by: full name, first/last name and email. */
function searchText(user: User): string {
  return `${userDisplayName(user)} ${user.display_name ?? ''} ${userEmail(user)}`.toLowerCase();
}

interface ExternalForm {
  full_name: string;
  email: string;
  organization: string;
}

const EMPTY_EXTERNAL: ExternalForm = { full_name: '', email: '', organization: '' };

/**
 * Searchable single-select over the user directory. Used for risk owners and
 * project managers. Every row shows the person's full name and email, and
 * matching runs against the name, first/last name and email.
 *
 * When ``includeExternal`` is set, previously created external owners are
 * searchable too and a PM can add a brand-new external owner inline, without
 * leaving the risk register.
 */
export function UserPicker({
  users,
  selectedUserId,
  onSelect,
  placeholder = 'Search by name or email…',
  noneLabel = 'Unassigned',
  disabled = false,
  includeExternal = false,
}: UserPickerProps) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState<User[]>([]);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState<ExternalForm>(EMPTY_EXTERNAL);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allUsers = useMemo(() => {
    if (!includeExternal) return users.filter((u) => u.owner_type !== 'External');
    // Merge in any owner created in this picker before the directory refreshed.
    const known = new Set(users.map((u) => u.id));
    return [...users, ...created.filter((u) => !known.has(u.id))];
  }, [users, includeExternal, created]);

  const selected = allUsers.find((u) => u.id === selectedUserId) ?? null;

  const matches = useMemo(() => {
    const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const base = tokens.length
      ? allUsers.filter((u) => {
          const hay = searchText(u);
          return tokens.every((token) => hay.includes(token));
        })
      : allUsers;
    return base.slice(0, MAX_RESULTS);
  }, [allUsers, query]);

  function pick(user: User | null) {
    onSelect(user);
    setQuery('');
    setOpen(false);
    setAdding(false);
    setError(null);
  }

  async function handleCreateExternal(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const owner = await createExternalOwner({
        full_name: form.full_name.trim(),
        email: form.email.trim(),
        organization: form.organization.trim() || null,
      });
      setCreated((prev) => [...prev, owner]);
      setForm(EMPTY_EXTERNAL);
      pick(owner);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  const selectedLabel = selected
    ? `${userDisplayName(selected)} (${userEmail(selected)})`
    : '';

  return (
    <div className="user-picker">
      <input
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        placeholder={placeholder}
        disabled={disabled}
        value={open ? query : selectedLabel}
        onFocus={() => {
          setQuery('');
          setOpen(true);
        }}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onBlur={() => {
          // Delay so a click on a list item lands before the list is hidden.
          if (!adding) {
            window.setTimeout(() => setOpen(false), 150);
          }
        }}
      />
      {open ? (
        <ul className="user-picker-list" role="listbox">
          <li
            role="option"
            aria-selected={selectedUserId === null}
            onMouseDown={() => pick(null)}
          >
            {noneLabel}
          </li>
          {matches.map((user) => (
            <li
              key={user.id}
              role="option"
              aria-selected={user.id === selectedUserId}
              onMouseDown={() => pick(user)}
            >
              <span className="user-picker-name">
                {userDisplayName(user)}
                {user.owner_type === 'External' ? (
                  <span className="owner-type-tag">External</span>
                ) : null}
              </span>
              <span className="user-picker-upn">
                {userEmail(user)}
                {user.organization ? ` · ${user.organization}` : ''}
              </span>
            </li>
          ))}
          {matches.length === 0 ? <li className="user-picker-empty">No matches</li> : null}

          {includeExternal && !adding ? (
            <li
              className="user-picker-add"
              role="button"
              onMouseDown={(e) => {
                e.preventDefault();
                setAdding(true);
                setError(null);
              }}
            >
              + Add External Risk Owner
            </li>
          ) : null}
        </ul>
      ) : null}

      {includeExternal && adding ? (
        <div className="external-owner-form">
          <div className="external-owner-form-title">New external Risk Owner</div>
          {error ? <div className="error-banner">{error}</div> : null}
          <div className="field">
            <label>Full name *</label>
            <input
              type="text"
              value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              placeholder="John Smith"
            />
          </div>
          <div className="field">
            <label>Email address *</label>
            <input
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              placeholder="john.smith@externalcompany.com"
            />
          </div>
          <div className="field">
            <label>Organization (optional)</label>
            <input
              type="text"
              value={form.organization}
              onChange={(e) => setForm({ ...form, organization: e.target.value })}
              placeholder="ABC Consulting"
            />
          </div>
          <div className="btn-group">
            <button
              type="button"
              className="btn btn-sm btn-primary"
              disabled={saving || !form.full_name.trim() || !form.email.trim()}
              onClick={(e) => void handleCreateExternal(e)}
            >
              {saving ? 'Adding…' : 'Add external owner'}
            </button>
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => {
                setAdding(false);
                setError(null);
                setForm(EMPTY_EXTERNAL);
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
