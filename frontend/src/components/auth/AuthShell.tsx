import type { ReactNode } from 'react';

/**
 * Official Microsoft four-square logo mark.
 *
 * Rendered inline (no external asset) so the sign-in button carries the
 * Microsoft icon without shipping a third-party icon package. Decorative
 * only — the accessible name comes from the button's visible label.
 */
export function MicrosoftLogo({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 23 23"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="1" y="1" width="10" height="10" fill="#F25022" />
      <rect x="12" y="1" width="10" height="10" fill="#7FBA00" />
      <rect x="1" y="12" width="10" height="10" fill="#00A4EF" />
      <rect x="12" y="12" width="10" height="10" fill="#FFB900" />
    </svg>
  );
}

/**
 * Dedicated authentication layout.
 *
 * This is intentionally NOT the application shell: an unauthenticated user
 * never sees the sidebar, topbar, navigation or any application data. It is
 * only ever rendered before a session exists (or while one is being resolved).
 */
export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="auth-page">
      <div className="auth-accent-bar" aria-hidden="true" />

      <header className="auth-brand">
        <img className="auth-logo" src="/wragby-logo.png" alt="Wragby" />
        <div className="auth-brand-rule" aria-hidden="true" />
        <p className="auth-product-name">PMO Risk Management</p>
      </header>

      <main className="auth-main">{children}</main>

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
