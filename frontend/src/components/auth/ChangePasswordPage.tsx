import { useId, useState } from 'react';
import type { FormEvent } from 'react';

import { api, ApiError } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { PRODUCT_NAME } from '../../branding';
import { AuthShell } from './AuthShell';
import { AlertIcon, EyeIcon, EyeOffIcon } from './icons';

const MIN_LENGTH = 8;

/**
 * Forced password change for administrator-provisioned accounts.
 *
 * Rendered instead of the app shell when ``GET /api/me`` reports
 * ``must_change_password``. The user sets their own password; the account's
 * temporary password is then invalidated.
 */
export function ChangePasswordPage({ onDone }: { onDone: () => void }) {
  const auth = useAuth();
  const uid = useId();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentId = `${uid}-current`;
  const nextId = `${uid}-next`;
  const confirmId = `${uid}-confirm`;
  const errorId = `${uid}-error`;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (next.length < MIN_LENGTH) {
      setError(`New password must be at least ${MIN_LENGTH} characters.`);
      return;
    }
    if (next !== confirm) {
      setError('The new passwords do not match.');
      return;
    }
    if (next === current) {
      setError('Choose a password different from your temporary one.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post('/api/auth/change-password', {
        current_password: current,
        new_password: next,
      });
      onDone();
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
    <AuthShell>
      <section className="auth-card auth-card-signin" aria-labelledby="cp-heading">
        <h1 id="cp-heading" className="auth-card-heading">
          Set your password
        </h1>
        <p className="auth-card-sub">
          Your {PRODUCT_NAME} account was created with a temporary password. Choose
          your own to continue.
        </p>

        <div className="auth-password">
          <form className="auth-password-form" onSubmit={submit} noValidate>
            {error ? (
              <div className="auth-error" id={errorId} role="alert">
                <AlertIcon />
                <span>{error}</span>
              </div>
            ) : null}

            <div className="field">
              <label htmlFor={currentId}>Temporary password</label>
              <input
                id={currentId}
                name="current_password"
                type={show ? 'text' : 'password'}
                autoComplete="current-password"
                required
                aria-required="true"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                autoFocus
              />
            </div>

            <div className="field">
              <label htmlFor={nextId}>New password</label>
              <div className="auth-input-wrap">
                <input
                  id={nextId}
                  name="new_password"
                  type={show ? 'text' : 'password'}
                  autoComplete="new-password"
                  required
                  minLength={MIN_LENGTH}
                  aria-required="true"
                  aria-describedby={error ? errorId : undefined}
                  value={next}
                  onChange={(e) => setNext(e.target.value)}
                />
                <button
                  type="button"
                  className="auth-pw-toggle"
                  onClick={() => setShow((v) => !v)}
                  aria-label={show ? 'Hide passwords' : 'Show passwords'}
                  aria-pressed={show}
                >
                  {show ? <EyeOffIcon /> : <EyeIcon />}
                </button>
              </div>
            </div>

            <div className="field">
              <label htmlFor={confirmId}>Confirm new password</label>
              <input
                id={confirmId}
                name="confirm_password"
                type={show ? 'text' : 'password'}
                autoComplete="new-password"
                required
                minLength={MIN_LENGTH}
                aria-required="true"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </div>

            <button className="btn auth-submit-btn" type="submit" disabled={busy} aria-busy={busy}>
              {busy ? (
                <>
                  <span className="auth-spinner" aria-hidden="true" />
                  Saving…
                </>
              ) : (
                'Set password'
              )}
            </button>
          </form>

          <button type="button" className="btn btn-sm" onClick={auth.logout}>
            Sign out
          </button>
        </div>
      </section>
    </AuthShell>
  );
}
