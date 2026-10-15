import { Suspense, type ReactNode } from 'react';
import { NavLink, Outlet } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';
import { api } from '../api/client';
import type { Me } from '../api/types';
import { useApi } from '../hooks/useApi';
import { BrandLockup } from './BrandLockup';
import { SignInPage } from './auth/SignInPage';
import { ChangePasswordPage } from './auth/ChangePasswordPage';
import { NotificationBell } from './NotificationBell';

function NavIcon({ children }: { children: ReactNode }) {
  return <span className="nav-icon">{children}</span>;
}

const ICONS: Record<string, ReactNode> = {
  create: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <path d="M12 8v8M8 12h8" />
    </svg>
  ),
  active: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
    </svg>
  ),
  history: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5" />
      <path d="M12 7v5l4 2" />
    </svg>
  ),
  report: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3v18h18" />
      <path d="M7 16v-5M12 16V8M17 16v-3" />
    </svg>
  ),
};

export function Layout() {
  const auth = useAuth();

  // While an Entra session resolves we render the app shell with a placeholder
  // so it paints immediately, instead of a blank screen then a sign-in flash.
  const resolvingSession = !auth.authReady;

  // Fetch the caller once a session exists. Besides role-aware controls, this
  // is what tells us an administrator-provisioned account must set its own
  // password before any application screen is shown.
  const { data: me, reload: reloadMe } = useApi<Me | null>(
    () => (auth.isAuthenticated ? api.get<Me>('/api/me') : Promise.resolve(null)),
    [auth.isAuthenticated],
  );

  // Unauthenticated users get the dedicated sign-in layout. The application
  // shell (sidebar, topbar, navigation, page data) must never be rendered
  // before a session exists.
  if (!auth.isAuthenticated && !resolvingSession) {
    return <SignInPage />;
  }

  // A temporary (admin-set) password must be replaced before the app is usable.
  if (me?.must_change_password) {
    return <ChangePasswordPage onDone={reloadMe} />;
  }

  // Remount the active page on identity change (sign-in/out) so every page
  // refetches under the new session instead of showing stale data.
  const outletKey = 'session';

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <img className="brand-logo" src="/wragby-logo.png" alt="Wragby" />
        </div>
        <nav className="nav">
          <NavLink to="/create-risk" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            <NavIcon>{ICONS.create}</NavIcon>
            Create Risk
          </NavLink>
          <NavLink to="/active-risk" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            <NavIcon>{ICONS.active}</NavIcon>
            Active Risk
          </NavLink>
          <NavLink to="/risk-history" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            <NavIcon>{ICONS.history}</NavIcon>
            Risk History
          </NavLink>
          <NavLink to="/report" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            <NavIcon>{ICONS.report}</NavIcon>
            Report
          </NavLink>
        </nav>
        <div className="sidebar-footer">
          <div className="user-card">
            <div className="user-avatar">{auth.user?.displayName?.[0] ?? '?'}</div>
            <div className="user-meta">
              <div className="user-name">{auth.user?.displayName ?? 'Signed out'}</div>
              <div className="user-upn">{auth.user?.upn ?? ''}</div>
            </div>
            <button className="btn btn-sm" onClick={auth.logout}>
              Sign out
            </button>
          </div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="topbar-title">
            <div className="topbar-brand">
              <BrandLockup className="brand-lockup-topbar" />
            </div>
          </div>
          <div className="topbar-actions">
            <NotificationBell />
          </div>
        </header>
        <main className="content">
          {resolvingSession ? (
            <div className="loading">Loading your session…</div>
          ) : (
            <Suspense fallback={<div className="loading">Loading…</div>}>
              <Outlet key={outletKey} />
            </Suspense>
          )}
        </main>
      </div>
    </div>
  );
}
