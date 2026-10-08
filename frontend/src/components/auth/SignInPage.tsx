import { useAuth } from '../../auth/AuthContext';
import { PasswordLoginForm } from '../PasswordLoginForm';
import { AuthShell } from './AuthShell';
import { AlertIcon } from './icons';

/**
 * Sign-in page.
 *
 * Authentication is app-managed: users sign in with their Wragby email and a
 * password issued by the PMO team. There is no Microsoft/SSO option and no
 * developer test login.
 *
 * The product name lives in the branding lockup (AuthShell), so the card uses a
 * short, task-focused heading to avoid repeating "WRAGBY RiskIntel".
 */
export function SignInPage() {
  const auth = useAuth();

  return (
    <AuthShell>
      <section className="auth-card auth-card-signin" aria-labelledby="auth-heading">
        <h1 id="auth-heading" className="auth-card-heading">
          Welcome back
        </h1>
        <p className="auth-card-sub">Sign in to WRAGBY RiskIntel to continue.</p>

        {auth.passwordLoginEnabled ? (
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
