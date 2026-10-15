// Module-level auth session store. The API client reads this on every request
// so it never needs React context plumbing. AuthProvider keeps it in sync.

export interface AuthState {
  /** Bearer access token (Entra OIDC or a locally-issued password token). */
  accessToken: string | null;
  /**
   * True when the session authenticates with a bearer token. Only a bearer
   * token is ever sent — the client never falls back to identity headers.
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
  return s.accessToken ? { Authorization: `Bearer ${s.accessToken}` } : {};
}
