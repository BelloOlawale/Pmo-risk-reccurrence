/**
 * Persisted sign-in session for the app-managed email + password login.
 *
 * The token is a short-lived (8h) HS256 bearer token issued by the backend.
 * It lives in localStorage so a page refresh keeps the user signed in; once it
 * expires the next sign-in replaces it.
 */

export interface StoredSession {
  token: string;
  upn: string;
  displayName: string;
  /** Epoch milliseconds at which the token stops being valid. */
  expiresAt: number;
}

const STORAGE_KEY = 'riskapp.session';

export function loadSession(): StoredSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredSession>;
    if (
      typeof parsed.token !== 'string' ||
      typeof parsed.upn !== 'string' ||
      typeof parsed.expiresAt !== 'number'
    ) {
      return null;
    }
    if (parsed.expiresAt <= Date.now()) {
      clearSession();
      return null;
    }
    return {
      token: parsed.token,
      upn: parsed.upn,
      displayName: parsed.displayName ?? parsed.upn,
      expiresAt: parsed.expiresAt,
    };
  } catch {
    return null;
  }
}

export function saveSession(session: StoredSession): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  localStorage.removeItem(STORAGE_KEY);
}
