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
   * Risk-Owner mode: the first choice is the owner *type* (Internal/External),
   * Internal opens the Wragby user search, External opens a name + email form.
   * Off by default so the project-manager picker only ever lists colleagues.
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
}

const EMPTY_EXTERNAL: ExternalForm = { full_name: '', email: '' };
// Client-side sanity check mirroring the backend validator.
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/**
 * Searchable single-select over the user directory. Used for risk owners and
 * project managers. Every row shows the person's full name and email, and
 * matching runs against the name, first/last name and email.
 *
 * In risk-owner mode (``includeExternal``) the first step is choosing whether
 * the owner is Internal or External. Internal users come from the Wragby
 * directory; an external owner is captured with only a name and an email.
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
  const [step, setStep] = useState<'choose' | 'internal' | 'external'>('choose');
  const [created, setCreated] = useState<User[]>([]);
  const [form, setForm] = useState<ExternalForm>(EMPTY_EXTERNAL);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allUsers = useMemo(() => {
    if (!includeExternal) return users.filter((u) => u.owner_type !== 'External');
    // Merge in any owner created in this picker before the directory refreshed.
    const known = new Set(users.map((u) => u.id));
    return [...users, ...created.filter((u) => !known.has(u.id))];
  }, [users, includeExternal, created]);

  const internalUsers = useMemo(
    () => allUsers.filter((u) => u.owner_type !== 'External'),
    [allUsers],
  );

  const selected = allUsers.find((u) => u.id === selectedUserId) ?? null;

  const matches = useMemo(() => {
    const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const base = tokens.length
      ? internalUsers.filter((u) => {
          const hay = searchText(u);
          return tokens.every((token) => hay.includes(token));
        })
      : internalUsers;
    return base.slice(0, MAX_RESULTS);
  }, [internalUsers, query]);

  function close() {
    setOpen(false);
    setStep('choose');
    setQuery('');
    setError(null);
  }

  function pick(user: User | null) {
    onSelect(user);
    close();
  }

  async function handleCreateExternal(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const owner = await createExternalOwner({
        full_name: form.full_name.trim(),
        email: form.email.trim().toLowerCase(),
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

  // ---------------------------------------------------------------------
  // Risk-owner mode: type-first selector.
  // ---------------------------------------------------------------------
  if (includeExternal) {
    const canSubmitExternal =
      form.full_name.trim().length > 0 && EMAIL_RE.test(form.email.trim().toLowerCase());

    return (
      <div className="user-picker">
        <button
          type="button"
          className="user-picker-trigger"
          disabled={disabled}
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => (open ? close() : setOpen(true))}
        >
          {selected ? (
            <span className="user-picker-selected">
              <span className="user-picker-name">{userDisplayName(selected)}</span>
              <span className="user-picker-upn">{userEmail(selected)}</span>
              {selected.owner_type === 'External' ? (
                <span className="owner-type-tag">External</span>
              ) : null}
            </span>
          ) : (
            <span className="user-picker-placeholder">{placeholder}</span>
          )}
          <span className="user-picker-caret" aria-hidden="true">
            ▾
          </span>
        </button>

        {open ? (
          <>
            <div className="user-picker-backdrop" onClick={close} aria-hidden="true" />
            <div className="user-picker-menu" role="dialog" aria-label="Select risk owner">
              {step === 'choose' ? (
                <>
                  <div className="user-picker-menu-title">Is this owner Internal or External?</div>
                  <div className="owner-type-options">
                    <button
                      type="button"
                      className="owner-type-option"
                      onMouseDown={(e) => {
                        e.preventDefault();
                        setQuery('');
                        setStep('internal');
                      }}
                    >
                      <span className="owner-type-option-title">Internal</span>
                      <span className="owner-type-option-sub">Wragby user directory</span>
                    </button>
                    <button
                      type="button"
                      className="owner-type-option"
                      onMouseDown={(e) => {
                        e.preventDefault();
                        setError(null);
                        setStep('external');
                      }}
                    >
                      <span className="owner-type-option-title">External</span>
                      <span className="owner-type-option-sub">Partner, vendor or consultant</span>
                    </button>
                  </div>
                  <button
                    type="button"
                    className="user-picker-clear"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      pick(null);
                    }}
                  >
                    {noneLabel}
                  </button>
                </>
              ) : null}

              {step === 'internal' ? (
                <>
                  <div className="user-picker-menu-header">
                    <button
                      type="button"
                      className="link-btn"
                      onMouseDown={(e) => {
                        e.preventDefault();
                        setStep('choose');
                      }}
                    >
                      ← Back
                    </button>
                    <span>Internal owner</span>
                  </div>
                  <input
                    type="text"
                    role="combobox"
                    aria-expanded="true"
                    aria-autocomplete="list"
                    autoFocus
                    className="search-input"
                    placeholder="Search by name or email…"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                  />
                  <ul className="user-picker-list user-picker-list-inline" role="listbox">
                    {matches.map((user) => (
                      <li
                        key={user.id}
                        role="option"
                        aria-selected={user.id === selectedUserId}
                        onMouseDown={() => pick(user)}
                      >
                        <span className="user-picker-name">{userDisplayName(user)}</span>
                        <span className="user-picker-upn">{userEmail(user)}</span>
                      </li>
                    ))}
                    {matches.length === 0 ? (
                      <li className="user-picker-empty">No matches</li>
                    ) : null}
                  </ul>
                </>
              ) : null}

              {step === 'external' ? (
                <div className="external-owner-form">
                  <div className="user-picker-menu-header">
                    <button
                      type="button"
                      className="link-btn"
                      onMouseDown={(e) => {
                        e.preventDefault();
                        setStep('choose');
                      }}
                    >
                      ← Back
                    </button>
                    <span>New external owner</span>
                  </div>
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
                  <div className="btn-group">
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      disabled={saving || !canSubmitExternal}
                      onClick={(e) => void handleCreateExternal(e)}
                    >
                      {saving ? 'Adding…' : 'Add external owner'}
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          </>
        ) : null}
      </div>
    );
  }

  // ---------------------------------------------------------------------
  // Plain directory mode (project-manager picker): unchanged search combobox.
  // ---------------------------------------------------------------------
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
          window.setTimeout(() => setOpen(false), 150);
        }}
      />
      {open ? (
        <ul className="user-picker-list" role="listbox">
          <li role="option" aria-selected={selectedUserId === null} onMouseDown={() => pick(null)}>
            {noneLabel}
          </li>
          {matches.map((user) => (
            <li
              key={user.id}
              role="option"
              aria-selected={user.id === selectedUserId}
              onMouseDown={() => pick(user)}
            >
              <span className="user-picker-name">{userDisplayName(user)}</span>
              <span className="user-picker-upn">{userEmail(user)}</span>
            </li>
          ))}
          {matches.length === 0 ? <li className="user-picker-empty">No matches</li> : null}
        </ul>
      ) : null}
    </div>
  );
}
