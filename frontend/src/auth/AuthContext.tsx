import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { MsalProvider, useMsal } from '@azure/msal-react';

import { api } from '../api/client';
import type { LoginOptions } from '../api/types';
import { authMode } from './authMode';
import { loginRequest, msalInstance } from './msal';
import { clearSession, loadSession, saveSession } from './session';
import type { StoredSession } from './session';
import { setAuthState } from './authStore';
import { useApi } from '../hooks/useApi';

export interface AuthUser {
  upn: string;
  displayName: string;
}

/**
 * Where a fresh page load and a fresh sign-in always start.
 *
 * The app must never resume the route the browser restored (a reload/reopen of
 * ``/report`` or ``/risks/5`` lands here instead). The public owner
 * acknowledgement route (``/acknowledge/:token``) is exempt so emailed links
 * keep working.
 */
const START_ROUTE = '/active-risk';

function startRouteFor(pathname: string): string {
  return pathname.startsWith('/acknowledge') ? pathname : START_ROUTE;
}

export interface AuthContextValue {
  isAuthenticated: boolean;
  /**
   * False only while a session is being resolved. The app shell renders during
   * this window and data fetching is deferred by the API client.
   */
  authReady: boolean;
  user: AuthUser | null;
  userId: number | null;
  role: string;
  /** True when Microsoft Entra ID SSO (MSAL) is the active mode. */
  isEntraMode: boolean;
  /** Begin the interactive Microsoft sign-in redirect (Entra mode only). */
  login: () => void;
  logout: () => void;
  /** Whether the backend offers app-managed email + password sign-in. */
  passwordLoginEnabled: boolean;
  /** Store a locally-issued bearer token and signed-in identity. */
  loginWithToken: (token: string, user: AuthUser) => void;
  /** Set when Microsoft sign-in failed (e.g. admin consent required). */
  entraError: string | null;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  if (authMode === 'entra') {
    return (
      <MsalProvider instance={msalInstance}>
        <EntraAuthGate>{children}</EntraAuthGate>
      </MsalProvider>
    );
  }
  return <PasswordAuthProvider>{children}</PasswordAuthProvider>;
}

/**
 * App-managed email + password sign-in.
 *
 * A session is a locally-issued bearer token (see ``session.ts``); the backend
 * validates it and resolves roles. There is no third-party identity provider.
 */
function PasswordAuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<StoredSession | null>(() => loadSession());
  // Public endpoint: whether the deployment offers password sign-in.
  const { data: loginOptions } = useApi(
    () => api.get<LoginOptions>('/api/auth/login-options'),
    [],
  );

  useEffect(() => {
    setAuthState({
      bearer: true,
      accessToken: session?.token ?? null,
      ready: true,
    });
  }, [session]);

  // Browser Back navigates within the app as normal. Sign-out only happens
  // when the user Backs past the app's first page: on sign-in we push one
  // duplicate entry (the "boundary") so Back at the first page lands on a
  // same-document entry instead of leaving the app or closing the tab.
  const navigate = useNavigate();
  const location = useLocation();
  const boundaryIdxRef = useRef<number | null>(null);
  const armedRef = useRef(false);

  useEffect(() => {
    if (!session) {
      armedRef.current = false;
      boundaryIdxRef.current = null;
      return;
    }
    if (armedRef.current) return;
    armedRef.current = true;
    // Record the index below which Back means "leaving the app".
    boundaryIdxRef.current = window.history.state?.idx ?? 0;
    // A fresh load / fresh sign-in always opens Active Risk, not the restored
    // route, while the public acknowledge link is left untouched.
    navigate(startRouteFor(location.pathname), { state: {} });
  }, [session, location.pathname, navigate]);

  useEffect(() => {
    if (!session) return;
    const onPopState = () => {
      // react-router stores its entry index in history.state.idx; at/below the
      // boundary there is no app page left, so sign out instead of exiting.
      const idx = window.history.state?.idx;
      const boundary = boundaryIdxRef.current;
      if (boundary === null) return;
      if (idx === undefined || idx === null || idx <= boundary) {
        clearSession();
        setSession(null);
      }
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [session]);

  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated: Boolean(session),
      authReady: true,
      user: session ? { upn: session.upn, displayName: session.displayName } : null,
      userId: null,
      role: '',
      isEntraMode: false,
      login: () => undefined,
      logout: () => {
        clearSession();
        setSession(null);
      },
      passwordLoginEnabled: loginOptions?.password_enabled ?? true,
      loginWithToken: (token, user) => {
        const next: StoredSession = {
          token,
          upn: user.upn,
          displayName: user.displayName,
          // Tokens are issued with an 8h lifetime by the backend.
          expiresAt: Date.now() + 8 * 60 * 60 * 1000,
        };
        saveSession(next);
        setSession(next);
      },
      entraError: null,
    }),
    [session, loginOptions],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * Microsoft Entra ID SSO via MSAL (redirect flow).
 *
 * Resolves the redirect response, then acquires an access token silently and
 * attaches it as a Bearer token (see ``authStore.authHeaders``). Roles are
 * resolved server-side from the token's ``groups`` claim — the SPA never
 * authorizes.
 */
function EntraAuthGate({ children }: { children: ReactNode }) {
  const { instance, accounts } = useMsal();
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [authReady, setAuthReady] = useState(false);

  // Resolve the redirect response, then acquire a token. The app shell renders
  // immediately; the API client defers requests until authReady so pages never
  // fire token-less calls during sign-in.
  useEffect(() => {
    let cancelled = false;

    async function initialise() {
      try {
        // Idempotent (MsalProvider also calls it). Awaiting it here fixes the
        // ordering race where a child effect ran handleRedirectPromise before
        // the provider's effect had initialized MSAL.
        await instance.initialize();
        const result = await instance.handleRedirectPromise();
        if (result?.account) {
          instance.setActiveAccount(result.account);
        }
      } catch (err) {
        if (!cancelled) setTokenError(err instanceof Error ? err.message : String(err));
      }

      try {
        const account = instance.getActiveAccount() ?? instance.getAllAccounts()[0];
        if (!account) {
          return; // no session — the layout shows the sign-in prompt
        }
        try {
          const silent = await instance.acquireTokenSilent({ ...loginRequest, account });
          if (!cancelled) {
            setAccessToken(silent.accessToken);
            setTokenError(null);
          }
        } catch {
          // Consent/MFA/expired session: fall back to an interactive redirect,
          // which navigates away rather than leaving the app token-less.
          try {
            await instance.acquireTokenRedirect({ ...loginRequest, account });
          } catch (err) {
            if (!cancelled) setTokenError(err instanceof Error ? err.message : String(err));
          }
        }
      } catch (err) {
        if (!cancelled) setTokenError(err instanceof Error ? err.message : String(err));
      } finally {
        // Resolution is done either way; unblock deferred API calls (they 401
        // only if the user genuinely has no session).
        if (!cancelled) {
          setAuthReady(true);
          setAuthState({ ready: true });
        }
      }
    }

    void initialise();
    return () => {
      cancelled = true;
    };
  }, [instance]);

  // When the active account changes (login/logout), refresh the token.
  useEffect(() => {
    const account = instance.getActiveAccount() ?? accounts[0];
    if (account) {
      instance
        .acquireTokenSilent({ ...loginRequest, account })
        .then((r) => setAccessToken(r.accessToken))
        .catch(() => undefined);
    } else {
      setAccessToken(null);
    }
  }, [instance, accounts]);

  useEffect(() => {
    setAuthState({ bearer: true, accessToken });
  }, [accessToken]);

  const account = accounts[0];
  const user: AuthUser | null = account
    ? { upn: account.username, displayName: account.name ?? account.username }
    : null;
  // A session only counts once we actually hold a token: an MSAL account with
  // no token (e.g. consent blocked) must fall back to the sign-in page rather
  // than rendering the app shell, which would 401 on every request.
  const isAuthenticated = Boolean(accessToken);

  // A fresh load / fresh sign-in always opens Active Risk (see START_ROUTE),
  // never the route the browser restored. Runs once per authenticated session.
  const navigate = useNavigate();
  const location = useLocation();
  const startRedirectedRef = useRef(false);
  useEffect(() => {
    if (!isAuthenticated) {
      startRedirectedRef.current = false;
      return;
    }
    if (startRedirectedRef.current) return;
    startRedirectedRef.current = true;
    const target = startRouteFor(location.pathname);
    // Skip when already on the target (and for the exempt public route).
    if (target !== location.pathname) {
      navigate(target, { replace: true });
    }
  }, [isAuthenticated, location.pathname, navigate]);

  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated,
      isEntraMode: true,
      authReady,
      user,
      userId: null,
      role: '',
      // Always show the account picker so a stale cached account can be switched.
      login: () => instance.loginRedirect({ ...loginRequest, prompt: 'select_account' }),
      logout: () => {
        setAccessToken(null);
        instance.logoutRedirect();
      },
      passwordLoginEnabled: false,
      loginWithToken: () => undefined,
      entraError: tokenError,
    }),
    [instance, accounts.length, account, user, isAuthenticated, tokenError, authReady],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
