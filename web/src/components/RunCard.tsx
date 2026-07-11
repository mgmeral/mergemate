import type { ValidationRun } from '../types';
import { StatusBadge } from './StatusBadge';

interface RunCardProps {
  run: ValidationRun;
  onClick: (runId: string) => void;
}

function timeAgo(isoString: string): string {
  const date = new Date(isoString);
  const diffMs = Date.now() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);

  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

function truncateRepo(url: string): string {
  // Strip protocol
  const noProto = url.replace(/^https?:\/\//, '').replace(/^git@[^:]+:/, '');
  // Remove trailing .git
  return noProto.replace(/\.git$/, '');
}

export function RunCard({ run, onClick }: RunCardProps) {
  const repoDisplay = run.repo_url ? truncateRepo(run.repo_url) : run.run_id;
  const featureBranch = run.feature_branch ?? '?';
  const targetBranch = run.target_branch ?? '?';

  return (
    <div
      className="run-card"
      onClick={() => onClick(run.run_id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onClick(run.run_id);
      }}
    >
      <div className="run-card__left">
        <div className="run-card__repo" title={run.repo_url ?? run.run_id}>
          {repoDisplay}
        </div>
        <div className="run-card__branches">
          {featureBranch} → {targetBranch}
        </div>
      </div>
      <div className="run-card__right">
        <StatusBadge status={run.status} />
        <span className="run-card__time">{timeAgo(run.started_at)}</span>
        <span className="run-card__id">{run.run_id.slice(0, 8)}</span>
      </div>
    </div>
  );
}
