import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import App from './App';
import { AuthProvider } from './auth/AuthContext';
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
 * msal-browser v3 refuses every API call until `initialize()` has resolved
 * (`blockAPICallsBeforeInitialize`). `MsalProvider` does call it, but from an
 * effect — and React runs child effects before parent effects, so
 * `EntraAuthGate.handleRedirectPromise()` always won that race and threw
 * `uninitialized_public_client_application`, breaking the SSO redirect flow.
 *
 * Awaiting initialize() here, before the tree mounts, makes every later call
 * (including MsalProvider's own) a safe no-op.
 */
if (isEntraConfigured) {
  msalInstance
    .initialize()
    .catch((err: unknown) => {
      // Render anyway: MsalProvider retries initialize() and surfaces the
      // failure through the sign-in screen's error banner.
      console.error('MSAL initialize() failed', err);
    })
    .finally(render);
} else {
  render();
}
