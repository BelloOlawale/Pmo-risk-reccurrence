import { useCallback, useEffect, useState } from 'react';

import { api } from './client';
import type { ExternalOwnerCreatePayload, User } from './types';

// External owners are captured by PMs mid-workflow, so the directory can change
// during a session (we refresh it after creating one). Cache it at module scope
// so every picker/table shares one request, and notify subscribers on refresh.
let cache: User[] | null = null;
let inflight: Promise<User[]> | null = null;
const listeners = new Set<() => void>();

export function fetchUsers(): Promise<User[]> {
  if (cache) return Promise.resolve(cache);
  if (!inflight) {
    inflight = api
      .get<User[]>('/api/users')
      .then((users) => {
        cache = users;
        return users;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/** Force a reload of the directory (after creating an external owner). */
export async function refreshUsers(): Promise<User[]> {
  cache = null;
  inflight = null;
  const users = await fetchUsers();
  for (const listener of listeners) listener();
  return users;
}

/** The user directory (internal + external). Returns [] until loaded. */
export function useUsers(): User[] {
  const [users, setUsers] = useState<User[]>(() => cache ?? []);

  const sync = useCallback(() => {
    if (cache) setUsers(cache);
  }, []);

  useEffect(() => {
    let active = true;
    fetchUsers()
      .then((loaded) => {
        if (active) setUsers(loaded);
      })
      .catch(() => {
        // Directory is best-effort for display; pickers just stay empty.
      });
    listeners.add(sync);
    return () => {
      active = false;
      listeners.delete(sync);
    };
  }, [sync]);

  return users;
}

/** Capture a new external Risk Owner and refresh the shared directory. */
export async function createExternalOwner(
  payload: ExternalOwnerCreatePayload,
): Promise<User> {
  const owner = await api.post<User>('/api/external-owners', payload);
  // Refresh is best-effort: the owner exists even if the directory refetch
  // fails, and the picker falls back to the row it already holds.
  try {
    await refreshUsers();
  } catch {
    // Ignore: selection still works via the returned owner.
  }
  return owner;
}

/** Build a human-readable name from an email/UPN local part. */
function nameFromUpn(upn: string): string {
  const local = (upn.split('@')[0] ?? upn).trim();
  const words = local.split(/[._+-]+/).filter(Boolean);
  if (words.length === 0) return upn;
  return words
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/**
 * The person's full name, falling back to a name derived from their email
 * local part when the directory row has no usable display name. This keeps
 * owners/PMs from ever showing as an email address only.
 */
export function userDisplayName(user: User): string {
  const name = (user.display_name ?? '').trim();
  const isUsableName =
    name.length > 0 && !name.includes('@') && name.toLowerCase() !== user.upn.toLowerCase();
  return isUsableName ? name : nameFromUpn(user.upn);
}

/** The person's email address (their UPN). */
export function userEmail(user: User): string {
  return user.upn;
}

/** True when the directory row is an external (non-Wragby) owner. */
export function isExternalUser(user: User | null | undefined): boolean {
  return user?.owner_type === 'External';
}

/** Display name for a risk/issue owner, falling back to `User #id`. */
export function ownerName(users: User[], ownerUserId: number | null): string {
  if (ownerUserId === null) return 'Unassigned';
  const user = users.find((u) => u.id === ownerUserId);
  return user ? userDisplayName(user) : `User #${ownerUserId}`;
}
