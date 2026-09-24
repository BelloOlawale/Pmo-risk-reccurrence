// Module-level auth session store. The API client reads this on every request
// so it never needs React context plumbing. AuthProvider keeps it in sync.

export interface AuthState {
  /** Entra ID access token (production). When set, sent as a Bearer token. */
  accessToken: string | null;
  /** Dev-mode user id, sent as the X-User-Id header. */
  devUserId: number | null;
  /** Dev-mode role, sent as the X-User-Role header. */
  devRole: string;
  /**
   * True when running against Entra ID. In that mode ONLY a bearer token is
   * sent — never the dev headers, which the backend ignores anyway and which
   * would mask "not signed in yet" as a confusing 401.
   */
  entra: boolean;
}

let state: AuthState = {
  accessToken: null,
  devUserId: null,
  devRole: 'System Admin',
  entra: false,
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

  if (s.entra) {
    return s.accessToken ? { Authorization: `Bearer ${s.accessToken}` } : {};
  }

  const headers: Record<string, string> = { 'X-User-Role': s.devRole };
  if (s.devUserId !== null) {
    headers['X-User-Id'] = String(s.devUserId);
  }
  return headers;
}
