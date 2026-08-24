import { useCallback, useEffect, useRef, useState } from 'react';
import type { DependencyList } from 'react';

import { ApiError } from '../api/client';

export interface ApiResult<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
  setData: (data: T | null) => void;
}

/**
 * Minimal data-fetching hook: runs `fetcher` on mount and whenever `deps`
 * change, exposing data/error/loading plus a manual reload.
 */
export function useApi<T>(fetcher: () => Promise<T>, deps: DependencyList = []): ApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const load = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetcherRef
      .current()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.message
              : err instanceof Error
                ? err.message
                : String(err),
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => load(), deps); // the returned cancel function is the cleanup
  // eslint-disable-next-line react-hooks/exhaustive-deps

  const reload = useCallback(() => {
    load();
  }, [load]);

  return { data, error, loading, reload, setData };
}
