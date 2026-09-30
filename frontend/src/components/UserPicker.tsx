import { useMemo, useState } from 'react';

import type { User } from '../api/types';
import { userDisplayName, userEmail } from '../api/users';

interface UserPickerProps {
  users: User[];
  /** Currently selected user id, or null for none. */
  selectedUserId: number | null;
  onSelect: (user: User | null) => void;
  placeholder?: string;
  /** Label for the "clear selection" row. */
  noneLabel?: string;
  disabled?: boolean;
}

const MAX_RESULTS = 50;

/** Everything a user can be searched by: full name, first/last name and email. */
function searchText(user: User): string {
  return `${userDisplayName(user)} ${user.display_name ?? ''} ${userEmail(user)}`.toLowerCase();
}

/**
 * Searchable single-select over the (large) Entra ID user directory. Used for
 * risk owners and project managers. Every row shows the person's full name and
 * email, and matching runs against the name, first/last name and email.
 */
export function UserPicker({
  users,
  selectedUserId,
  onSelect,
  placeholder = 'Search by name or email…',
  noneLabel = 'Unassigned',
  disabled = false,
}: UserPickerProps) {
  const selected = users.find((u) => u.id === selectedUserId) ?? null;
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);

  const matches = useMemo(() => {
    const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const base = tokens.length
      ? users.filter((u) => {
          const hay = searchText(u);
          return tokens.every((token) => hay.includes(token));
        })
      : users;
    return base.slice(0, MAX_RESULTS);
  }, [users, query]);

  function pick(user: User | null) {
    onSelect(user);
    setQuery('');
    setOpen(false);
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
          window.setTimeout(() => setOpen(false), 150);
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
