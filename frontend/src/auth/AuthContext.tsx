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

export interface AuthContextValue {
  isAuthenticated: boolean;
  isDevMode: boolean;
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
  setDevIdentity: (userId: number | null, role: string) => void;
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

export const DEV_ROLES = ['System Admin', 'PMO Lead', 'Project Manager'];
const DEV_STORAGE_KEY = 'riskapp.devIdentity';

interface DevIdentity {
  userId: number | null;
  role: string;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  if (authMode === 'entra') {
    return (
      <MsalProvider instance={msalInstance}>
        <EntraAuthGate>{children}</EntraAuthGate>
      </MsalProvider>
    );
  }
  if (authMode === 'dev') {
    return <DevAuthProvider>{children}</DevAuthProvider>;
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
      devUserId: null,
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
    navigate(location.pathname + location.search, { state: {} });
  }, [session, location.pathname, location.search, navigate]);

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
      isDevMode: false,
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
      setDevIdentity: () => undefined,
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
 * Developer-only provider: header-based identity with the sidebar switcher.
 * Used when ``VITE_AUTH_MODE=dev``; the backend must also run in dev mode
 * (no ``RISKAPP_ENTRA_TENANT_ID`` and no local login).
 */
function DevAuthProvider({ children }: { children: ReactNode }) {
  const [identity, setIdentity] = useState<DevIdentity>(() => {
    try {
      const raw = localStorage.getItem(DEV_STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as DevIdentity;
        return { userId: parsed.userId ?? null, role: parsed.role ?? 'System Admin' };
      }
    } catch {
      // fall through to defaults
    }
    return { userId: null, role: 'System Admin' };
  });

  useEffect(() => {
    setAuthState({ bearer: false, accessToken: null, devUserId: identity.userId, devRole: identity.role });
    localStorage.setItem(DEV_STORAGE_KEY, JSON.stringify(identity));
  }, [identity]);

  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated: true,
      isDevMode: true,
      authReady: true,
      user: {
        upn: identity.userId !== null ? `user-${identity.userId}@local` : 'dev-admin@local',
        displayName: identity.userId !== null ? `Dev User ${identity.userId}` : 'Dev Admin',
      },
      userId: identity.userId,
      role: identity.role,
      isEntraMode: false,
      login: () => undefined,
      logout: () => undefined,
      setDevIdentity: (userId, role) => setIdentity({ userId, role }),
      passwordLoginEnabled: false,
      loginWithToken: () => undefined,
      entraError: null,
    }),
    [identity],
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
    setAuthState({ bearer: true, accessToken, devUserId: null });
  }, [accessToken]);

  const account = accounts[0];
  const user: AuthUser | null = account
    ? { upn: account.username, displayName: account.name ?? account.username }
    : null;
  // A session only counts once we actually hold a token: an MSAL account with
  // no token (e.g. consent blocked) must fall back to the sign-in page rather
  // than rendering the app shell, which would 401 on every request.
  const isAuthenticated = Boolean(accessToken);

  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated,
      isDevMode: false,
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
      setDevIdentity: () => undefined,
      passwordLoginEnabled: false,
      loginWithToken: () => undefined,
      entraError: tokenError,
    }),
    [instance, accounts.length, account, user, isAuthenticated, tokenError, authReady],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
