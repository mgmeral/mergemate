import { useState, useEffect, useCallback, useRef } from 'react';
import { getRun } from '../api';
import type { ValidationRun } from '../types';

interface UseRunResult {
  run: ValidationRun | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

const TERMINAL_STATUSES = new Set<ValidationRun['status']>(['success', 'failure', 'error']);

export function useRun(runId: string, pollIntervalMs = 3000): UseRunResult {
  const [run, setRun] = useState<ValidationRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Keep a ref to the latest run so the interval callback can read it without
  // being re-created every time run changes.
  const runRef = useRef<ValidationRun | null>(null);
  runRef.current = run;

  const fetchRun = useCallback(async (isInitial: boolean) => {
    if (isInitial) setLoading(true);
    try {
      const data = await getRun(runId);
      setRun(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (isInitial) setLoading(false);
    }
  }, [runId]);

  const refresh = useCallback(() => {
    void fetchRun(false);
  }, [fetchRun]);

  useEffect(() => {
    void fetchRun(true);

    const interval = setInterval(() => {
      const current = runRef.current;
      if (current !== null && TERMINAL_STATUSES.has(current.status)) {
        clearInterval(interval);
        return;
      }
      void fetchRun(false);
    }, pollIntervalMs);

    return () => clearInterval(interval);
  }, [fetchRun, pollIntervalMs]);

  return { run, loading, error, refresh };
}
