import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import App from './App';
import { AuthProvider } from './auth/AuthContext';
import { authMode } from './auth/authMode';
import { setAuthState } from './auth/authStore';
import { loadSession } from './auth/session';
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
 * The session store is seeded synchronously before the first render so the API
 * client never fires a request with the wrong identity: in password mode a
 * persisted session is attached as a bearer token, otherwise the request goes
 * out token-less and the sign-in page is shown.
 */
if (authMode === 'password') {
  const session = loadSession();
  setAuthState({
    bearer: true,
    accessToken: session?.token ?? null,
    devUserId: null,
    ready: true,
  });
} else {
  setAuthState({ bearer: false, ready: true });
}

render();
