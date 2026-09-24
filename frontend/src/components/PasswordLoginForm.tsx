import { useId, useState } from 'react';
import type { FormEvent } from 'react';

import { api, ApiError } from '../api/client';
import type { TestLoginToken } from '../api/types';
import { useAuth } from '../auth/AuthContext';

/**
 * Email + password sign-in with app-managed credentials.
 *
 * Rendered only when the backend reports it is enabled
 * (``RISKAPP_LOCAL_LOGIN_ENABLED``). These passwords are held by this
 * application and are independent of the Microsoft/Entra account.
 */
export function PasswordLoginForm() {
  const auth = useAuth();
  const uid = useId();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const emailId = `${uid}-email`;
  const passwordId = `${uid}-password`;
  const errorId = `${uid}-error`;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<TestLoginToken>('/api/auth/login', { email, password });
      auth.loginWithToken(res.access_token, {
        upn: res.upn,
        displayName: res.display_name,
      });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : String(err),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-password">
      <div className="auth-password-divider">
        <span>or</span>
      </div>

      <form className="auth-password-form" onSubmit={submit} noValidate>
        {error ? (
          <div className="auth-error" id={errorId} role="alert">
            {error}
          </div>
        ) : null}

        <div className="field">
          <label htmlFor={emailId}>Wragby email</label>
          <input
            id={emailId}
            name="email"
            type="email"
            autoComplete="username"
            required
            aria-required="true"
            aria-describedby={error ? errorId : undefined}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@wragbysolutions.com"
          />
        </div>

        <div className="field">
          <label htmlFor={passwordId}>Password</label>
          <input
            id={passwordId}
            name="password"
            type="password"
            autoComplete="current-password"
            required
            aria-required="true"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        <button className="btn auth-password-submit" type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in with email'}
        </button>
      </form>
    </div>
  );
}
