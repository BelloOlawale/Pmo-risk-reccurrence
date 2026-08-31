import { NavLink, Outlet } from 'react-router-dom';

import { DEV_ROLES, useAuth } from '../auth/AuthContext';
import { NotificationBell } from './NotificationBell';

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
            Risk Registers
          </NavLink>
          <NavLink to="/active-register" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            Active Register
          </NavLink>
          <NavLink to="/projects" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            Projects
          </NavLink>
          <NavLink to="/onboard" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            Onboard Project
          </NavLink>
          <NavLink to="/portfolio" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
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
