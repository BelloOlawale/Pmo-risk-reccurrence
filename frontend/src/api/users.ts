import { api } from './client';
import type { User } from './types';
import { useApi } from '../hooks/useApi';

// Users are created on first sign-in, so the directory is small and stable for
// the life of a session. Cache it at module scope so every picker/table shares
// one request instead of refetching per component.
let cache: User[] | null = null;
let inflight: Promise<User[]> | null = null;

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

/** The user directory. Returns [] until loaded (and on failure). */
export function useUsers(): User[] {
  const { data } = useApi(fetchUsers, []);
  return data ?? cache ?? [];
}

/** Display name for a risk/issue owner, falling back to `User #id`. */
export function ownerName(users: User[], ownerUserId: number | null): string {
  if (ownerUserId === null) return 'Unassigned';
  const user = users.find((u) => u.id === ownerUserId);
  return user ? user.display_name || user.upn : `User #${ownerUserId}`;
}
