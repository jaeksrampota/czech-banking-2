import { useCallback, useEffect, useRef, useState } from 'react';

export interface UseFetchResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  lastUpdated: Date | null;
  refresh: () => void;
}

interface Options {
  /** Auto-refresh interval in ms. 0 / undefined disables. */
  refreshInterval?: number;
  /** Dependencies that force a refetch when they change. */
  deps?: unknown[];
}

/**
 * Tiny data-loader with loading / error / lastUpdated / manual refresh.
 * Dedupes in-flight requests so a fast-clicked refresh button doesn't stack.
 */
export function useFetch<T>(fetcher: () => Promise<T>, opts: Options = {}): UseFetchResult<T> {
  const { refreshInterval = 0, deps = [] } = opts;
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const inflight = useRef(false);
  const mounted = useRef(true);

  const run = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    setLoading(true);
    setError(null);
    try {
      const result = await fetcher();
      if (!mounted.current) return;
      setData(result);
      setLastUpdated(new Date());
    } catch (e) {
      if (!mounted.current) return;
      setError(e instanceof Error ? e.message : 'Request failed');
    } finally {
      inflight.current = false;
      if (mounted.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetcher]);

  useEffect(() => {
    mounted.current = true;
    run();
    return () => {
      mounted.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (!refreshInterval) return;
    const id = setInterval(run, refreshInterval);
    return () => clearInterval(id);
  }, [refreshInterval, run]);

  return { data, loading, error, lastUpdated, refresh: run };
}
