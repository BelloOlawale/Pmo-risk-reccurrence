import { useId, useState } from 'react';
import type { FormEvent } from 'react';

import { api, ApiError } from '../api/client';
import type { LoginToken } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { AlertIcon, EyeIcon, EyeOffIcon } from './auth/icons';

/**
 * Email + password sign-in with app-managed credentials.
 *
 * Rendered only when the backend reports it is enabled
 * (``RISKAPP_LOCAL_LOGIN_ENABLED``). These passwords are held by this
 * application.
 */
export function PasswordLoginForm() {
  const auth = useAuth();
  const uid = useId();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const emailId = `${uid}-email`;
  const passwordId = `${uid}-password`;
  const errorId = `${uid}-error`;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<LoginToken>('/api/auth/login', { email, password });
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
      <form className="auth-password-form" onSubmit={submit} noValidate>
        {error ? (
          <div className="auth-error" id={errorId} role="alert">
            <AlertIcon />
            <span>{error}</span>
          </div>
        ) : null}

        <div className="field">
          <label htmlFor={emailId}>Email</label>
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
            placeholder="you@company.com"
            autoFocus
          />
        </div>

        <div className="field">
          <label htmlFor={passwordId}>Password</label>
          <div className="auth-input-wrap">
            <input
              id={passwordId}
              name="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
              required
              aria-required="true"
              aria-describedby={error ? errorId : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button
              type="button"
              className="auth-pw-toggle"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              aria-pressed={showPassword}
              title={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? <EyeOffIcon /> : <EyeIcon />}
            </button>
          </div>
        </div>

        <button
          className="btn auth-submit-btn"
          type="submit"
          disabled={busy}
          aria-busy={busy}
        >
          {busy ? (
            <>
              <span className="auth-spinner" aria-hidden="true" />
              Signing in…
            </>
          ) : (
            'Sign in'
          )}
        </button>
      </form>
    </div>
  );
}
