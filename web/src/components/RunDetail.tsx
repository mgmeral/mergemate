import { useRun } from '../hooks/useRun';
import { StatusBadge } from './StatusBadge';
import { ExecutionPlan } from './ExecutionPlan';

interface RunDetailProps {
  runId: string;
  onBack: () => void;
}

function formatDateTime(isoString: string | null): string {
  if (!isoString) return '—';
  try {
    return new Date(isoString).toLocaleString();
  } catch {
    return isoString;
  }
}

function truncateRepo(url: string): string {
  return url.replace(/^https?:\/\//, '').replace(/^git@[^:]+:/, '').replace(/\.git$/, '');
}

export function RunDetail({ runId, onBack }: RunDetailProps) {
  const { run, loading, error } = useRun(runId);

  if (loading) {
    return (
      <div className="page-container">
        <div className="detail-back">
          <button className="btn btn--secondary" onClick={onBack}>
            ← Back
          </button>
        </div>
        <div className="empty-state">
          <div className="spinner" style={{ width: 24, height: 24 }} />
          <p className="mt-12 text-secondary">Loading run…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page-container">
        <div className="detail-back">
          <button className="btn btn--secondary" onClick={onBack}>
            ← Back
          </button>
        </div>
        <div className="error-box">
          <div className="error-box__title">Failed to load run</div>
          <div>{error}</div>
        </div>
      </div>
    );
  }

  if (!run) return null;

  const repoDisplay = run.repo_url ? truncateRepo(run.repo_url) : '—';
  const hasConflicts = run.has_conflicts === true;

  return (
    <div className="page-container">
      <div className="detail-back">
        <button className="btn btn--secondary" onClick={onBack}>
          ← Back
        </button>
      </div>

      {/* Header */}
      <div className="detail-header">
        <h1 className="detail-header__title" title={run.repo_url ?? run.run_id}>
          {repoDisplay}
        </h1>
        <StatusBadge status={run.status} large />
      </div>

      {/* Meta */}
      <div className="detail-meta">
        <div className="detail-meta__item">
          <div className="detail-meta__label">Run ID</div>
          <div className="detail-meta__value detail-meta__value--mono">{run.run_id}</div>
        </div>
        {run.repo_url && (
          <div className="detail-meta__item">
            <div className="detail-meta__label">Repository</div>
            <div className="detail-meta__value">
              <a href={run.repo_url} target="_blank" rel="noopener noreferrer">
                {repoDisplay}
              </a>
            </div>
          </div>
        )}
        {(run.feature_branch ?? run.target_branch) && (
          <div className="detail-meta__item">
            <div className="detail-meta__label">Branches</div>
            <div className="detail-meta__value detail-meta__value--mono">
              {run.feature_branch ?? '?'} → {run.target_branch ?? '?'}
            </div>
          </div>
        )}
        <div className="detail-meta__item">
          <div className="detail-meta__label">Started</div>
          <div className="detail-meta__value">{formatDateTime(run.started_at)}</div>
        </div>
        {run.finished_at && (
          <div className="detail-meta__item">
            <div className="detail-meta__label">Finished</div>
            <div className="detail-meta__value">{formatDateTime(run.finished_at)}</div>
          </div>
        )}
      </div>

      {/* Error message */}
      {run.error_message && (
        <div className="detail-section">
          <div className="error-box">
            <div className="error-box__title">Error</div>
            <div>{run.error_message}</div>
          </div>
        </div>
      )}

      {/* Conflict files */}
      {hasConflicts && run.conflict_files.length > 0 && (
        <div className="detail-section">
          <div className="conflict-box">
            <div className="conflict-box__title">
              Merge Conflicts ({run.conflict_files.length})
            </div>
            <ul className="conflict-box__files">
              {run.conflict_files.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Changed files */}
      {run.changed_files.length > 0 && (
        <div className="detail-section">
          <div className="detail-section__title">
            Changed Files ({run.changed_files.length})
          </div>
          <ul className="file-list">
            {run.changed_files.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Execution plan */}
      {run.execution_plan && (
        <div className="detail-section">
          <div className="detail-section__title">Execution Plan</div>
          <ExecutionPlan plan={run.execution_plan} />
        </div>
      )}

      {/* Maven command (if no execution plan but command is present) */}
      {!run.execution_plan && run.maven_command && (
        <div className="detail-section">
          <div className="detail-section__title">Maven Command</div>
          <pre className="plan-command">{run.maven_command}</pre>
        </div>
      )}

      {/* Lifecycle log */}
      {run.lifecycle_log.length > 0 && (
        <div className="detail-section">
          <div className="detail-section__title">
            Lifecycle Log ({run.lifecycle_log.length} entries)
          </div>
          <div className="lifecycle-log">
            {run.lifecycle_log.map((entry, idx) => (
              <div key={idx} className="lifecycle-log__entry">
                {entry}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
