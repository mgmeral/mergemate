import { useState } from 'react';
import { startValidation } from '../api';
import type { StartValidationRequest } from '../types';

interface ValidationFormProps {
  onRunStarted: (runId: string) => void;
}

const EMPTY_FORM: StartValidationRequest = {
  repo_url: '',
  feature_branch: '',
  target_branch: 'main',
};

export function ValidationForm({ onRunStarted }: ValidationFormProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [form, setForm] = useState<StartValidationRequest>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleChange(field: keyof StartValidationRequest, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.repo_url.trim() || !form.feature_branch.trim() || !form.target_branch.trim()) {
      setError('All fields are required.');
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const run = await startValidation({
        repo_url: form.repo_url.trim(),
        feature_branch: form.feature_branch.trim(),
        target_branch: form.target_branch.trim(),
      });
      setForm(EMPTY_FORM);
      setIsOpen(false);
      onRunStarted(run.run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start validation');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="form-section">
      <button
        type="button"
        className="form-section__toggle"
        onClick={() => setIsOpen((o) => !o)}
        aria-expanded={isOpen}
      >
        <span>+ Start New Validation</span>
        <span className={`form-section__toggle-icon ${isOpen ? 'form-section__toggle-icon--open' : ''}`}>
          ▼
        </span>
      </button>

      {isOpen && (
        <div className="form-section__body">
          <form onSubmit={(e) => { void handleSubmit(e); }} noValidate>
            <div className="form-group">
              <label className="form-label" htmlFor="repo_url">
                Repository URL
              </label>
              <input
                id="repo_url"
                type="url"
                className="form-input"
                placeholder="https://github.com/org/repo"
                value={form.repo_url}
                onChange={(e) => handleChange('repo_url', e.target.value)}
                disabled={submitting}
                required
              />
            </div>

            <div className="form-row">
              <div className="form-group">
                <label className="form-label" htmlFor="feature_branch">
                  Feature Branch
                </label>
                <input
                  id="feature_branch"
                  type="text"
                  className="form-input"
                  placeholder="feature/my-feature"
                  value={form.feature_branch}
                  onChange={(e) => handleChange('feature_branch', e.target.value)}
                  disabled={submitting}
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="target_branch">
                  Target Branch
                </label>
                <input
                  id="target_branch"
                  type="text"
                  className="form-input"
                  placeholder="main"
                  value={form.target_branch}
                  onChange={(e) => handleChange('target_branch', e.target.value)}
                  disabled={submitting}
                  required
                />
              </div>
            </div>

            <div className="form-actions">
              <button type="submit" className="btn btn--primary" disabled={submitting}>
                {submitting ? (
                  <>
                    <span className="spinner" />
                    Starting…
                  </>
                ) : (
                  'Run Validation'
                )}
              </button>
              {error && <span className="form-error">{error}</span>}
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
