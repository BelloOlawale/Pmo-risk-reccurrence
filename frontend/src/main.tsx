import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import App from './App';
import { AuthProvider } from './auth/AuthContext';
import { setAuthState } from './auth/authStore';
import { isEntraConfigured, msalInstance } from './auth/msal';
import './index.css';

function render() {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </React.StrictMode>,
  );
}

/**
 * Bootstrap.
 *
 * We render immediately rather than awaiting `msalInstance.initialize()` first:
 * waiting produced a blank screen on every load. The auth gate awaits the same
 * (idempotent) initialize promise before resolving a session, which keeps the
 * original fix for the child-before-parent effect race that used to break the
 * SSO redirect. Until resolution finishes the API client defers requests.
 */
if (isEntraConfigured) {
  void msalInstance.initialize().catch((err: unknown) => {
    // Non-fatal: the gate retries initialize() and surfaces the failure via the
    // sign-in screen's error banner.
    console.error('MSAL initialize() failed', err);
  });
} else {
  // Dev mode has no session to resolve — unblock API requests right away.
  setAuthState({ entra: false, ready: true });
}

render();
