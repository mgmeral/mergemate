import type { StartValidationRequest, ValidationRun } from './types';

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8080';

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function startValidation(req: StartValidationRequest): Promise<ValidationRun> {
  return fetchJson<ValidationRun>('/api/v1/validations', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export async function getRun(runId: string): Promise<ValidationRun> {
  return fetchJson<ValidationRun>(`/api/v1/validations/${encodeURIComponent(runId)}`);
}

export async function listRuns(limit = 20): Promise<{ runs: ValidationRun[]; total: number }> {
  return fetchJson<{ runs: ValidationRun[]; total: number }>(
    `/api/v1/validations?limit=${limit}`
  );
}
