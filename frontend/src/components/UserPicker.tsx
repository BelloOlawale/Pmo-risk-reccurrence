import { useMemo, useState } from 'react';

import type { User } from '../api/types';

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

/**
 * Searchable single-select over the (large) Entra ID user directory. Used for
 * risk owners and project managers. A native `<select>` with 1000+ options is
 * unusable, so this filters as you type.
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
    const q = query.trim().toLowerCase();
    const base = q
      ? users.filter((u) => `${u.display_name} ${u.upn}`.toLowerCase().includes(q))
      : users;
    return base.slice(0, MAX_RESULTS);
  }, [users, query]);

  function pick(user: User | null) {
    onSelect(user);
    setQuery('');
    setOpen(false);
  }

  return (
    <div className="user-picker">
      <input
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        placeholder={placeholder}
        disabled={disabled}
        value={open ? query : selected ? selected.display_name || selected.upn : ''}
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
              <span className="user-picker-name">{user.display_name || user.upn}</span>
              <span className="user-picker-upn">{user.upn}</span>
            </li>
          ))}
          {matches.length === 0 ? <li className="user-picker-empty">No matches</li> : null}
        </ul>
      ) : null}
    </div>
  );
}
