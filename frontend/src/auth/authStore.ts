// Module-level auth session store. The API client reads this on every request
// so it never needs React context plumbing. AuthProvider keeps it in sync.

export interface AuthState {
  /** Locally-issued (email + password) access token, sent as a Bearer token. */
  accessToken: string | null;
  /** Dev-mode user id, sent as the X-User-Id header. */
  devUserId: number | null;
  /** Dev-mode role, sent as the X-User-Role header. */
  devRole: string;
  /**
   * True when the session authenticates with a bearer token. In that mode ONLY
   * a bearer token is sent — never the dev headers, which would mask "not
   * signed in yet" as a confusing 401.
   */
  bearer: boolean;
  /**
   * True once session resolution has finished. Until then the API client defers
   * requests so a page never fires an unauthenticated call during sign-in.
   */
  ready: boolean;
}

let state: AuthState = {
  accessToken: null,
  devUserId: null,
  devRole: 'System Admin',
  bearer: false,
  ready: false,
};

let readyResolvers: Array<() => void> = [];

export function setAuthState(next: Partial<AuthState>): void {
  state = { ...state, ...next };
  if (state.ready && readyResolvers.length > 0) {
    const resolvers = readyResolvers;
    readyResolvers = [];
    for (const resolve of resolvers) resolve();
  }
}

/** Resolves once auth resolution has finished (immediately when already ready). */
export function whenAuthReady(): Promise<void> {
  if (state.ready) return Promise.resolve();
  return new Promise((resolve) => {
    readyResolvers.push(resolve);
  });
}

export function getAuthState(): AuthState {
  return state;
}

/** Headers to attach to every API request based on the current session. */
export function authHeaders(): Record<string, string> {
  const s = getAuthState();

  if (s.bearer) {
    return s.accessToken ? { Authorization: `Bearer ${s.accessToken}` } : {};
  }

  const headers: Record<string, string> = { 'X-User-Role': s.devRole };
  if (s.devUserId !== null) {
    headers['X-User-Id'] = String(s.devUserId);
  }
  return headers;
}
