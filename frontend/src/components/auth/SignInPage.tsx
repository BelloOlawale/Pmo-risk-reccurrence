import { useAuth } from '../../auth/AuthContext';
import { PRODUCT_NAME } from '../../branding';
import { PasswordLoginForm } from '../PasswordLoginForm';
import { AuthShell } from './AuthShell';
import { AlertIcon, MicrosoftIcon } from './icons';

/**
 * Sign-in page.
 *
 * The deployment's auth mode decides what is offered:
 *
 *   * Entra ID SSO  — a "Sign in with Microsoft" button (MSAL redirect).
 *   * password      — the app-managed email + password form.
 *
 * The product name lives in the branding lockup (AuthShell), so the card uses a
 * short, task-focused heading.
 */
export function SignInPage() {
  const auth = useAuth();

  return (
    <AuthShell>
      <section className="auth-card auth-card-signin" aria-labelledby="auth-heading">
        <h1 id="auth-heading" className="auth-card-heading">
          Welcome back
        </h1>
        <p className="auth-card-sub">Sign in to {PRODUCT_NAME} to continue.</p>

        {auth.isEntraMode ? (
          <div className="auth-sso">
            {auth.entraError ? (
              <div className="auth-error" role="alert">
                <AlertIcon />
                <span>{auth.entraError}</span>
              </div>
            ) : null}
            <button type="button" className="btn auth-sso-btn" onClick={auth.login}>
              <MicrosoftIcon />
              Sign in with Microsoft
            </button>
          </div>
        ) : auth.passwordLoginEnabled ? (
          <PasswordLoginForm />
        ) : (
          <div className="auth-error auth-error-standalone" role="alert">
            <AlertIcon />
            <span>Email and password sign-in is not enabled for this deployment.</span>
          </div>
        )}
      </section>
    </AuthShell>
  );
}
