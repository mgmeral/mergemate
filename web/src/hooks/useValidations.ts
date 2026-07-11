import { useState, useEffect, useCallback } from 'react';
import { listRuns } from '../api';
import type { ValidationRun } from '../types';

interface UseValidationsResult {
  runs: ValidationRun[];
  total: number;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useValidations(pollIntervalMs = 5000, limit = 20): UseValidationsResult {
  const [runs, setRuns] = useState<ValidationRun[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRuns = useCallback(async (isInitial: boolean) => {
    if (isInitial) setLoading(true);
    try {
      const data = await listRuns(limit);
      setRuns(data.runs);
      setTotal(data.total);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (isInitial) setLoading(false);
    }
  }, [limit]);

  const refresh = useCallback(() => {
    void fetchRuns(false);
  }, [fetchRuns]);

  useEffect(() => {
    void fetchRuns(true);

    const interval = setInterval(() => {
      void fetchRuns(false);
    }, pollIntervalMs);

    return () => clearInterval(interval);
  }, [fetchRuns, pollIntervalMs]);

  return { runs, total, loading, error, refresh };
}
