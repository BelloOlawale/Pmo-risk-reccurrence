import type { ReactNode } from 'react';
import { NavLink, Outlet } from 'react-router-dom';

import { DEV_ROLES, useAuth } from '../auth/AuthContext';
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
          {auth.isDevMode ? (
            <div className="dev-switcher">
              <label>Dev mode role</label>
              <select
                value={auth.role}
                onChange={(e) => auth.setDevIdentity(auth.userId, e.target.value)}
              >
                {DEV_ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
              <label>User ID (blank = admin)</label>
              <input
                type="number"
                value={auth.userId ?? ''}
                placeholder="admin"
                onChange={(e) =>
                  auth.setDevIdentity(
                    e.target.value === '' ? null : Number(e.target.value),
                    auth.role,
                  )
                }
              />
            </div>
          ) : (
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
          )}
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="topbar-title">
            <span className="topbar-mark" aria-hidden="true">W</span>
            <span>PMO Risk Management</span>
          </div>
          <div className="topbar-actions">
            <NotificationBell />
          </div>
        </header>
        <main className="content">
          {!auth.isDevMode && !auth.isAuthenticated ? (
            <div className="empty-state">
              <h2>Sign in required</h2>
              <p className="muted">Authenticate with your Microsoft account to continue.</p>
              <button className="btn btn-primary" onClick={auth.login}>
                Sign in with Microsoft
              </button>
            </div>
          ) : (
            <Outlet />
          )}
        </main>
      </div>
    </div>
  );
}
