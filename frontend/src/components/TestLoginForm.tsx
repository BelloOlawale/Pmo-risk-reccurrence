import { useId, useState } from 'react';
import type { FormEvent } from 'react';

import { api, ApiError } from '../api/client';
import type { TestLoginToken } from '../api/types';
import { useAuth, DEV_ROLES } from '../auth/AuthContext';

/**
 * Local, non-Microsoft sign-in for testing while Entra admin consent is
 * pending. Only rendered when the backend reports it is enabled
 * (RISKAPP_TEST_LOGIN_ENABLED); an access code is required when configured.
 *
 * Deliberately presented as a clearly-labelled, visually subordinate
 * "Development / Test access" section so it never competes with, or is
 * mistaken for, the production Microsoft sign-in.
 */
export function TestLoginForm() {
  const auth = useAuth();
  const uid = useId();
  const [role, setRole] = useState<string>(DEV_ROLES[0]);
  const [upn, setUpn] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const roleId = `${uid}-role`;
  const emailId = `${uid}-email`;
  const codeId = `${uid}-code`;
  const errorId = `${uid}-error`;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<TestLoginToken>('/api/auth/test-login', {
        role,
        upn: upn.trim() || null,
        code: code || null,
      });
      auth.loginWithToken(res.access_token, {
        upn: res.upn,
        displayName: res.display_name,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-dev">
      <div className="auth-dev-divider">
        <span>Development / Test access</span>
      </div>
      <p className="auth-dev-note">For local testing only — not part of production sign-in.</p>

      <form className="auth-dev-form" onSubmit={submit} noValidate>
        {error ? (
          <div className="auth-error" id={errorId} role="alert">
            {error}
          </div>
        ) : null}

        <div className="field">
          <label htmlFor={roleId}>Role</label>
          <select
            id={roleId}
            name="role"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            aria-describedby={error ? errorId : undefined}
          >
            {DEV_ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor={emailId}>
            Email
            <span className="auth-optional">optional</span>
          </label>
          <input
            id={emailId}
            name="email"
            type="email"
            autoComplete="off"
            value={upn}
            onChange={(e) => setUpn(e.target.value)}
            placeholder="tester@wragbysolutions.com"
          />
          <span className="field-hint">Leave blank to use the default test account for the role.</span>
        </div>

        {auth.testLoginCodeRequired ? (
          <div className="field">
            <label htmlFor={codeId}>Access code</label>
            <input
              id={codeId}
              name="code"
              type="password"
              autoComplete="off"
              required
              aria-required="true"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="Test access code"
            />
          </div>
        ) : null}

        <button className="btn auth-dev-submit" type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Test login'}
        </button>
      </form>
    </div>
  );
}
