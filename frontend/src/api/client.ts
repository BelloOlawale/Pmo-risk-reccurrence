import { authHeaders, whenAuthReady } from '../auth/authStore';

// Relative URLs go through the Vite dev proxy in development. Set
// VITE_API_BASE_URL to an absolute URL when the API lives elsewhere.
const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? '';

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  // Never fire before the session is resolved: in Entra mode an early request
  // would go out token-less and 401 (and could race the sign-in flow).
  await whenAuthReady();

  const headers = new Headers(init.headers);
  const hasBody = init.body !== undefined && init.body !== null;

  if (hasBody) {
    headers.set('Content-Type', 'application/json');
  }
  for (const [key, value] of Object.entries(authHeaders())) {
    headers.set(key, value);
  }

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body.detail !== undefined) {
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // non-JSON error body; keep the status text
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

/**
 * Fetch a binary file with the session's auth headers and return it as a Blob.
 *
 * A plain ``window.open``/anchor would omit the bearer token in Entra mode, so
 * downloads go through the same authenticated request path as the JSON API.
 */
async function download(path: string): Promise<{ blob: Blob; filename: string | null }> {
  await whenAuthReady();

  const headers = new Headers();
  for (const [key, value] of Object.entries(authHeaders())) {
    headers.set(key, value);
  }

  const res = await fetch(`${API_BASE}${path}`, { headers });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body.detail !== undefined) {
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // non-JSON error body; keep the status text
    }
    throw new ApiError(res.status, detail);
  }

  const disposition = res.headers.get('content-disposition') ?? '';
  const match = /filename="?([^";]+)"?/.exec(disposition);
  return { blob: await res.blob(), filename: match ? match[1] : null };
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PATCH',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  download,
};
