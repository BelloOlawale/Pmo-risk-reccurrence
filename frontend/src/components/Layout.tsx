import type { ReactNode } from 'react';
import { NavLink, Outlet } from 'react-router-dom';

import { DEV_ROLES, useAuth } from '../auth/AuthContext';
import { NotificationBell } from './NotificationBell';

function NavIcon({ children }: { children: ReactNode }) {
  return <span className="nav-icon">{children}</span>;
}

const ICONS: Record<string, ReactNode> = {
  registers: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 10h18M9 10v10" />
    </svg>
  ),
  active: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
    </svg>
  ),
  projects: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="7" width="20" height="14" rx="2" />
      <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
    </svg>
  ),
  onboard: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <path d="M12 8v8M8 12h8" />
    </svg>
  ),
  portfolio: (
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
          <span className="brand-mark">R</span>
          <span className="brand-text">Risk Recurrence</span>
        </div>
        <nav className="nav">
          <NavLink to="/" end className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            <NavIcon>{ICONS.registers}</NavIcon>
            Risk Registers
          </NavLink>
          <NavLink to="/active-register" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            <NavIcon>{ICONS.active}</NavIcon>
            Active Register
          </NavLink>
          <NavLink to="/projects" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            <NavIcon>{ICONS.projects}</NavIcon>
            Projects
          </NavLink>
          <NavLink to="/onboard" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            <NavIcon>{ICONS.onboard}</NavIcon>
            Onboard Project
          </NavLink>
          <NavLink to="/portfolio" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            <NavIcon>{ICONS.portfolio}</NavIcon>
            Portfolio
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
          <div className="topbar-title">PMO Risk Management</div>
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
