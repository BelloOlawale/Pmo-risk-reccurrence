import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useMsal, MsalProvider } from '@azure/msal-react';

import { isEntraConfigured, loginRequest, msalInstance } from './msal';
import { setAuthState } from './authStore';

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
    setAuthState({ accessToken: null, devUserId: identity.userId, devRole: identity.role });
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
    }),
    [identity],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

function EntraAuthGate({ children }: { children: ReactNode }) {
  const { instance, accounts } = useMsal();
  const [accessToken, setAccessToken] = useState<string | null>(null);

  // Resolve the redirect response on load, then acquire a silent token.
  useEffect(() => {
    instance
      .handleRedirectPromise()
      .then((result) => {
        if (result?.account) {
          instance.setActiveAccount(result.account);
        }
        const account = instance.getActiveAccount() ?? instance.getAllAccounts()[0];
        if (account) {
          return instance
            .acquireTokenSilent({ ...loginRequest, account })
            .then((r) => setAccessToken(r.accessToken))
            .catch(() => undefined);
        }
        return undefined;
      })
      .catch(() => undefined);
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
    setAuthState({ accessToken, devUserId: null });
  }, [accessToken]);

  const account = accounts[0];
  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated: accounts.length > 0,
      isDevMode: false,
      user: account
        ? { upn: account.username, displayName: account.name ?? account.username }
        : null,
      userId: null,
      role: '',
      login: () => instance.loginRedirect(loginRequest),
      logout: () => instance.logoutRedirect(),
      setDevIdentity: () => undefined,
    }),
    [instance, accounts, account],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
