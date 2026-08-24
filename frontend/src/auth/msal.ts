import { PublicClientApplication } from '@azure/msal-browser';
import type { Configuration } from '@azure/msal-browser';

const clientId = import.meta.env.VITE_ENTRA_CLIENT_ID as string | undefined;
const tenantId = import.meta.env.VITE_ENTRA_TENANT_ID as string | undefined;

/** True when the app is configured for Entra ID SSO (production mode). */
export const isEntraConfigured = Boolean(clientId && tenantId);

export const msalConfig: Configuration = {
  auth: {
    clientId: clientId ?? '',
    authority: tenantId ? `https://login.microsoftonline.com/${tenantId}` : undefined,
    redirectUri: typeof window !== 'undefined' ? window.location.origin : undefined,
  },
  cache: {
    cacheLocation: 'sessionStorage',
    storeAuthStateInCookie: false,
  },
};

// The API (FastAPI) expects an OIDC access token in the Authorization header;
// roles are resolved server-side from the token's group claims.
export const loginRequest = {
  scopes: ['openid', 'profile', 'email', `${clientId ?? ''}/.default`].filter(Boolean),
};

export const msalInstance = new PublicClientApplication(msalConfig);
