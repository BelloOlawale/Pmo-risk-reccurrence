/**
 * Frontend authentication mode.
 *
 * The application signs users in with an app-managed email + password (see
 * ``PasswordLoginForm``). Set ``VITE_AUTH_MODE=dev`` to run with header-based
 * developer auth and the sidebar identity switcher instead — local development
 * only, never in a deployed build.
 */
const configured = (import.meta.env.VITE_AUTH_MODE as string | undefined)
  ?.trim()
  .toLowerCase();

export type AuthMode = 'password' | 'dev';

export const authMode: AuthMode = configured === 'dev' ? 'dev' : 'password';
