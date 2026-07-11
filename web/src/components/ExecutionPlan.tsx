import type { ExecutionPlan as ExecutionPlanType } from '../types';

interface ExecutionPlanProps {
  plan: ExecutionPlanType;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

export function ExecutionPlan({ plan }: ExecutionPlanProps) {
  return (
    <div>
      <div className="plan-strategy">
        <span className="plan-strategy__badge">{plan.strategy}</span>
        <span className="plan-strategy__reason">{plan.reason}</span>
      </div>

      <div className="plan-summary">
        <span>{plan.modules.length} module{plan.modules.length !== 1 ? 's' : ''}</span>
        <span>~{formatDuration(plan.estimated_duration_seconds)}</span>
        <span>~{plan.estimated_test_count.toLocaleString()} tests</span>
      </div>

      <div className="plan-modules">
        {plan.modules.map((mod) => (
          <div key={mod.artifact_id} className="module-card">
            <span className={`module-label module-label--${mod.label}`}>{mod.label}</span>
            <div className="module-info">
              <div className="module-info__name">{mod.artifact_id}</div>
              {mod.reason && (
                <div className="module-info__reason">{mod.reason}</div>
              )}
            </div>
            <div className="module-stats">
              <div>~{formatDuration(mod.estimated_duration_seconds)}</div>
              <div>{mod.estimated_test_count} tests</div>
            </div>
          </div>
        ))}
      </div>

      {plan.maven_command && (
        <div>
          <div className="detail-section__title mt-12">Maven Command</div>
          <pre className="plan-command">{plan.maven_command}</pre>
        </div>
      )}
    </div>
  );
}
