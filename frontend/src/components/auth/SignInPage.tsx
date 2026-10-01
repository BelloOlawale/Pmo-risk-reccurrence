import { useAuth } from '../../auth/AuthContext';
import { PasswordLoginForm } from '../PasswordLoginForm';
import { TestLoginForm } from '../TestLoginForm';
import { AuthShell, MicrosoftLogo } from './AuthShell';

/**
 * Enterprise sign-in page.
 *
 * Visual hierarchy:
 *   1. Wragby branding (shell)
 *   2. Welcome / authentication message
 *   3. Microsoft sign-in (the real authentication mechanism)
 *   4. Email + password sign-in (app-managed accounts), when enabled
 *   5. Development / test login (subordinate, only when enabled by the backend)
 */export function SignInPage() {
  const auth = useAuth();

  return (
    <AuthShell>
      <section className="auth-card" aria-labelledby="auth-heading">
        <h1 id="auth-heading" className="auth-card-heading">
          Welcome to WRAGBY RiskIntel
        </h1>
        <p className="auth-card-sub">
          {auth.passwordLoginEnabled
            ? 'Sign in with your Microsoft account, or with your Wragby email and password.'
            : 'Sign in with your Microsoft account to continue.'}
        </p>

        {auth.entraError ? (
          <div className="auth-error" role="alert">
            Microsoft sign-in failed: {auth.entraError}
          </div>
        ) : null}

        <button type="button" className="auth-primary-btn" onClick={auth.login}>
          <span className="auth-ms-logo">
            <MicrosoftLogo size={16} />
          </span>
          Continue with Microsoft
        </button>

        {auth.passwordLoginEnabled ? <PasswordLoginForm /> : null}
        {auth.testLoginEnabled ? <TestLoginForm /> : null}
      </section>
    </AuthShell>
  );
}
