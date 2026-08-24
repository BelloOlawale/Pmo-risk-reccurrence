// Module-level auth session store. The API client reads this on every request
// so it never needs React context plumbing. AuthProvider keeps it in sync.

export interface AuthState {
  /** Entra ID access token (production). When set, sent as a Bearer token. */
  accessToken: string | null;
  /** Dev-mode user id, sent as the X-User-Id header. */
  devUserId: number | null;
  /** Dev-mode role, sent as the X-User-Role header. */
  devRole: string;
}

let state: AuthState = {
  accessToken: null,
  devUserId: null,
  devRole: 'System Admin',
};

export function setAuthState(next: Partial<AuthState>): void {
  state = { ...state, ...next };
}

export function getAuthState(): AuthState {
  return state;
}

/** Headers to attach to every API request based on the current session. */
export function authHeaders(): Record<string, string> {
  const s = getAuthState();
  const headers: Record<string, string> = {};
  if (s.accessToken) {
    headers.Authorization = `Bearer ${s.accessToken}`;
  } else {
    if (s.devUserId !== null) {
      headers['X-User-Id'] = String(s.devUserId);
    }
    headers['X-User-Role'] = s.devRole;
  }
  return headers;
}
