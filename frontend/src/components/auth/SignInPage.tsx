import { useAuth } from '../../auth/AuthContext';
import { PasswordLoginForm } from '../PasswordLoginForm';
import { AuthShell } from './AuthShell';

/**
 * Sign-in page.
 *
 * Authentication is app-managed: users sign in with their Wragby email and a
 * password issued by the PMO team. There is no Microsoft/SSO option and no
 * developer test login.
 */
export function SignInPage() {
  const auth = useAuth();

  return (
    <AuthShell>
      <section className="auth-card" aria-labelledby="auth-heading">
        <h1 id="auth-heading" className="auth-card-heading">
          Welcome to WRAGBY RiskIntel
        </h1>
        <p className="auth-card-sub">
          Sign in with your email and password to continue.
        </p>

        {auth.passwordLoginEnabled ? (
          <PasswordLoginForm />
        ) : (
          <div className="auth-error" role="alert">
            Email and password sign-in is not enabled for this deployment.
          </div>
        )}
      </section>
    </AuthShell>
  );
}
