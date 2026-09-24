import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useMsal, MsalProvider } from '@azure/msal-react';

import { api } from '../api/client';
import type { LoginOptions } from '../api/types';
import { isEntraConfigured, loginRequest, msalInstance } from './msal';
import { setAuthState } from './authStore';
import { useApi } from '../hooks/useApi';
import { AuthShell } from '../components/auth/AuthShell';

export interface AuthUser {
  upn: string;
  displayName: string;
}

export interface AuthContextValue {
  isAuthenticated: boolean;
  isDevMode: boolean;
  user: AuthUser | null;
  userId: number | null;
  role: string;
  login: () => void;
  logout: () => void;
  setDevIdentity: (userId: number | null, role: string) => void;
  /** Local non-Microsoft sign-in (testing / app-managed accounts). */
  passwordLoginEnabled: boolean;
  testLoginEnabled: boolean;
  testLoginCodeRequired: boolean;
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
  if (isEntraConfigured) {
    return (
      <MsalProvider instance={msalInstance}>
        <EntraAuthGate>{children}</EntraAuthGate>
      </MsalProvider>
    );
  }
  return <DevAuthProvider>{children}</DevAuthProvider>;
}

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
    setAuthState({ accessToken: null, devUserId: identity.userId, devRole: identity.role, entra: false });
    localStorage.setItem(DEV_STORAGE_KEY, JSON.stringify(identity));
  }, [identity]);

  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated: true,
      isDevMode: true,
      user: {
        upn: identity.userId !== null ? `user-${identity.userId}@local` : 'dev-admin@local',
        displayName: identity.userId !== null ? `Dev User ${identity.userId}` : 'Dev Admin',
      },
      userId: identity.userId,
      role: identity.role,
      login: () => undefined,
      logout: () => undefined,
      setDevIdentity: (userId, role) => setIdentity({ userId, role }),
      testLoginEnabled: false,
      testLoginCodeRequired: false,
      passwordLoginEnabled: false,
      loginWithToken: () => undefined,
      entraError: null,
    }),
    [identity],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

function EntraAuthGate({ children }: { children: ReactNode }) {
  const { instance, accounts } = useMsal();
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [testIdentity, setTestIdentity] = useState<AuthUser | null>(null);
  // Public endpoint: which non-Microsoft sign-in methods are offered.
  const { data: loginOptions } = useApi(
    () => api.get<LoginOptions>('/api/auth/login-options'),
    [],
  );

  // Resolve the redirect response on load, then acquire a token. Crucially we
  // do NOT render the app until a token exists, otherwise child pages fire
  // /api requests with no bearer token ("Missing bearer token").
  useEffect(() => {
    setAuthState({ entra: true, devUserId: null });
    let cancelled = false;

    async function initialise() {
      try {
        const result = await instance.handleRedirectPromise();
        if (result?.account) {
          instance.setActiveAccount(result.account);
        }
      } catch (err) {
        if (!cancelled) setTokenError(err instanceof Error ? err.message : String(err));
      }

      const account = instance.getActiveAccount() ?? instance.getAllAccounts()[0];
      if (!account) {
        return; // no session — the layout shows the Sign in prompt
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
    setAuthState({ entra: true, accessToken, devUserId: null });
  }, [accessToken]);

  const account = accounts[0];
  const msaUser: AuthUser | null = account
    ? { upn: account.username, displayName: account.name ?? account.username }
    : null;
  const user = testIdentity ?? msaUser;
  // A session only counts once we actually hold a token: an MSAL account with
  // no token (e.g. consent blocked) must fall back to the sign-in page rather
  // than rendering the app shell, which would 401 on every request.
  const isAuthenticated = Boolean(accessToken);

  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated,
      isDevMode: false,
      user,
      userId: null,
      role: '',
      // Always show the account picker so a stale cached account can be switched.
      login: () => instance.loginRedirect({ ...loginRequest, prompt: 'select_account' }),
      logout: () => {
        setTestIdentity(null);
        setAccessToken(null);
        instance.logoutRedirect();
      },
      setDevIdentity: () => undefined,
      passwordLoginEnabled: loginOptions?.password_enabled ?? false,
      testLoginEnabled: loginOptions?.test_login_enabled ?? false,
      testLoginCodeRequired: loginOptions?.test_code_required ?? false,
      loginWithToken: (token, nextUser) => {
        setTestIdentity(nextUser);
        setAccessToken(token);
      },
      entraError: tokenError,
    }),
    [
      instance,
      accounts.length,
      account,
      msaUser,
      user,
      isAuthenticated,
      testIdentity,
      loginOptions,
      tokenError,
    ],
  );

  // Hold the app back until we have a token (or there is no session to resolve).
  // Rendered in the dedicated auth layout so a half-established session never
  // flashes the application shell.
  if (accounts.length > 0 && !accessToken && !tokenError) {
    return (
      <AuthContext.Provider value={value}>
        <AuthShell>
          <section className="auth-card auth-card-status" aria-live="polite">
            <div className={tokenError ? 'auth-status-icon auth-status-error' : 'auth-status-icon'} aria-hidden="true">
              {tokenError ? '!' : <span className="auth-spinner" />}
            </div>
            <h1 className="auth-card-heading">
              {tokenError ? 'Sign-in failed' : 'Signing you in…'}
            </h1>
            <p className="auth-card-sub">
              {tokenError ?? 'Acquiring your Microsoft access token…'}
            </p>
            {tokenError ? (
              <button
                type="button"
                className="auth-primary-btn"
                onClick={() => instance.acquireTokenRedirect(loginRequest)}
              >
                Retry sign-in
              </button>
            ) : null}
          </section>
        </AuthShell>
      </AuthContext.Provider>
    );
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
