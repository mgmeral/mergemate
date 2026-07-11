import { useValidations } from '../hooks/useValidations';
import { ValidationForm } from './ValidationForm';
import { RunCard } from './RunCard';

interface DashboardProps {
  onSelectRun: (runId: string) => void;
}

export function Dashboard({ onSelectRun }: DashboardProps) {
  const { runs, total, loading, error, refresh } = useValidations(5000);

  function handleRunStarted(runId: string) {
    refresh();
    onSelectRun(runId);
  }

  return (
    <div className="page-container">
      <ValidationForm onRunStarted={handleRunStarted} />

      <div className="runs-section__header">
        <h2 className="runs-section__title">Recent Validations</h2>
        <span className="runs-section__meta">
          {loading && runs.length === 0
            ? 'Loading…'
            : `${total} total · auto-refreshes every 5s`}
        </span>
      </div>

      {error && !loading && (
        <div className="error-box" style={{ marginBottom: 16 }}>
          <div className="error-box__title">Could not fetch runs</div>
          <div>{error}</div>
        </div>
      )}

      {loading && runs.length === 0 ? (
        <div className="empty-state">
          <div style={{ fontSize: 24 }}>⏳</div>
          <p className="empty-state__text mt-8">Loading runs…</p>
        </div>
      ) : runs.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state__icon">🔍</div>
          <p className="empty-state__text">
            No validations yet. Start one above.
          </p>
        </div>
      ) : (
        <div>
          {runs.map((run) => (
            <RunCard key={run.run_id} run={run} onClick={onSelectRun} />
          ))}
        </div>
      )}
    </div>
  );
}
