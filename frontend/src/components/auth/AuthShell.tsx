import type { ReactNode } from 'react';

/**
 * Dedicated authentication layout.
 *
 * This is intentionally NOT the application shell: an unauthenticated user
 * never sees the sidebar, topbar, navigation or any application data. It is
 * only ever rendered before a session exists.
 *
 * The brand lockup and the card are grouped in a single centred column so they
 * read as one cohesive component; the footer is pinned to the bottom.
 */
export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="auth-page">
      <div className="auth-accent-bar" aria-hidden="true" />

      <div className="auth-center">
        <header className="auth-brand">
          <img className="auth-logo" src="/wragby-logo.png" alt="Wragby" />
          <p className="auth-product-name">
            <span className="brand-wragby">WRAGBY</span>{' '}
            <span className="brand-intell">RiskIntel</span>
          </p>
          <div className="auth-brand-rule" aria-hidden="true" />
          <p className="auth-product-subtitle">PMO Risk Management</p>
        </header>

        <main className="auth-main">{children}</main>
      </div>

      <footer className="auth-footer">
        <span>© {new Date().getFullYear()} Wragby</span>
        <span className="auth-footer-dot" aria-hidden="true">
          •
        </span>
        <span>PMO Risk Management</span>
      </footer>
    </div>
  );
}
