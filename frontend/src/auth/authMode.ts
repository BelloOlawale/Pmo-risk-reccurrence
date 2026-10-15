/**
 * Frontend authentication mode.
 *
 * Two modes, selected by ``VITE_AUTH_MODE`` (a build-time value):
 *
 *   ``entra``    — Microsoft Entra ID SSO via MSAL (production).
 *   ``password`` — app-managed email + password sign-in (fallback).
 *
 * ``entra`` is also auto-selected when ``VITE_ENTRA_CLIENT_ID`` and
 * ``VITE_ENTRA_TENANT_ID`` are both present and no explicit mode is set.
 */
const configured = (import.meta.env.VITE_AUTH_MODE as string | undefined)
  ?.trim()
  .toLowerCase();
const entraClientId = import.meta.env.VITE_ENTRA_CLIENT_ID as string | undefined;
const entraTenantId = import.meta.env.VITE_ENTRA_TENANT_ID as string | undefined;

export type AuthMode = 'entra' | 'password';

function resolveMode(): AuthMode {
  if (configured === 'password') return 'password';
  if (configured === 'entra') return 'entra';
  // Unset/unrecognised: prefer Entra when it is fully configured, else password.
  return entraClientId && entraTenantId ? 'entra' : 'password';
}

export const authMode: AuthMode = resolveMode();

/** True when MSAL-based Entra sign-in is the active mode. */
export const isEntraMode = authMode === 'entra';
