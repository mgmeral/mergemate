import { useState } from 'react';
import { startValidation, startLocalAnalysis } from '../api';
import type { StartValidationRequest, StartLocalAnalysisRequest } from '../types';

interface ValidationFormProps {
  onRunStarted: (runId: string) => void;
}

type FormMode = 'docker' | 'local';

const EMPTY_DOCKER: StartValidationRequest = {
  repo_url: '',
  feature_branch: '',
  target_branch: 'main',
};

const EMPTY_LOCAL: StartLocalAnalysisRequest = {
  repo_dir: '',
  source: 'HEAD',
  target: 'origin/main',
  goal: 'test',
};

const GOALS = ['analyze', 'test', 'compile', 'verify'] as const;

export function ValidationForm({ onRunStarted }: ValidationFormProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [mode, setMode] = useState<FormMode>('local');
  const [dockerForm, setDockerForm] = useState<StartValidationRequest>(EMPTY_DOCKER);
  const [localForm, setLocalForm] = useState<StartLocalAnalysisRequest>(EMPTY_LOCAL);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleDockerChange(field: keyof StartValidationRequest, value: string) {
    setDockerForm((prev) => ({ ...prev, [field]: value }));
  }

  function handleLocalChange(field: keyof StartLocalAnalysisRequest, value: string) {
    setLocalForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === 'local') {
        if (!localForm.repo_dir.trim() || !localForm.target.trim()) {
          setError('Repo dir and target branch are required.');
          return;
        }
        const run = await startLocalAnalysis({
          repo_dir: localForm.repo_dir.trim(),
          source: localForm.source?.trim() || 'HEAD',
          target: localForm.target.trim(),
          goal: localForm.goal || 'test',
        });
        setLocalForm(EMPTY_LOCAL);
        setIsOpen(false);
        onRunStarted(run.run_id);
      } else {
        if (!dockerForm.repo_url.trim() || !dockerForm.feature_branch.trim() || !dockerForm.target_branch.trim()) {
          setError('All fields are required.');
          return;
        }
        const run = await startValidation({
          repo_url: dockerForm.repo_url.trim(),
          feature_branch: dockerForm.feature_branch.trim(),
          target_branch: dockerForm.target_branch.trim(),
        });
        setDockerForm(EMPTY_DOCKER);
        setIsOpen(false);
        onRunStarted(run.run_id);
      }
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
        <span>+ Start New Analysis</span>
        <span className={`form-section__toggle-icon ${isOpen ? 'form-section__toggle-icon--open' : ''}`}>
          ▼
        </span>
      </button>

      {isOpen && (
        <div className="form-section__body">
          {/* Mode tabs */}
          <div className="form-tabs">
            <button
              type="button"
              className={`form-tab ${mode === 'local' ? 'form-tab--active' : ''}`}
              onClick={() => { setMode('local'); setError(null); }}
            >
              Local Repo
            </button>
            <button
              type="button"
              className={`form-tab ${mode === 'docker' ? 'form-tab--active' : ''}`}
              onClick={() => { setMode('docker'); setError(null); }}
            >
              Remote (Docker)
            </button>
          </div>

          <form onSubmit={(e) => { void handleSubmit(e); }} noValidate>
            {mode === 'local' ? (
              <>
                <div className="form-group">
                  <label className="form-label" htmlFor="repo_dir">
                    Repository Directory
                  </label>
                  <input
                    id="repo_dir"
                    type="text"
                    className="form-input form-input--mono"
                    placeholder="/path/to/your/project"
                    value={localForm.repo_dir}
                    onChange={(e) => handleLocalChange('repo_dir', e.target.value)}
                    disabled={submitting}
                    required
                  />
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label" htmlFor="source">
                      Source (HEAD)
                    </label>
                    <input
                      id="source"
                      type="text"
                      className="form-input form-input--mono"
                      placeholder="HEAD"
                      value={localForm.source ?? 'HEAD'}
                      onChange={(e) => handleLocalChange('source', e.target.value)}
                      disabled={submitting}
                    />
                  </div>

                  <div className="form-group">
                    <label className="form-label" htmlFor="target">
                      Target Branch
                    </label>
                    <input
                      id="target"
                      type="text"
                      className="form-input form-input--mono"
                      placeholder="origin/main"
                      value={localForm.target}
                      onChange={(e) => handleLocalChange('target', e.target.value)}
                      disabled={submitting}
                      required
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label">Goal</label>
                  <div className="form-radio-group">
                    {GOALS.map((g) => (
                      <label key={g} className="form-radio">
                        <input
                          type="radio"
                          name="goal"
                          value={g}
                          checked={localForm.goal === g}
                          onChange={() => handleLocalChange('goal', g)}
                          disabled={submitting}
                        />
                        {g}
                      </label>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <>
                <div className="form-group">
                  <label className="form-label" htmlFor="repo_url">
                    Repository URL
                  </label>
                  <input
                    id="repo_url"
                    type="url"
                    className="form-input"
                    placeholder="https://github.com/org/repo"
                    value={dockerForm.repo_url}
                    onChange={(e) => handleDockerChange('repo_url', e.target.value)}
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
                      value={dockerForm.feature_branch}
                      onChange={(e) => handleDockerChange('feature_branch', e.target.value)}
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
                      value={dockerForm.target_branch}
                      onChange={(e) => handleDockerChange('target_branch', e.target.value)}
                      disabled={submitting}
                      required
                    />
                  </div>
                </div>
              </>
            )}

            <div className="form-actions">
              <button type="submit" className="btn btn--primary" disabled={submitting}>
                {submitting ? (
                  <>
                    <span className="spinner" />
                    Starting…
                  </>
                ) : mode === 'local' ? (
                  'Analyze'
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
