import type { ValidationRun } from '../types';

interface StatusBadgeProps {
  status: ValidationRun['status'];
  large?: boolean;
}

const STATUS_LABELS: Record<ValidationRun['status'], string> = {
  pending: 'Pending',
  running: 'Running',
  success: 'Success',
  failure: 'Failure',
  error: 'Error',
};

export function StatusBadge({ status, large = false }: StatusBadgeProps) {
  const isRunning = status === 'running';

  return (
    <span
      className={[
        'status-badge',
        `status-badge--${status}`,
        large ? 'status-badge--large' : '',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <span
        className={[
          'status-badge__dot',
          isRunning ? 'status-badge__dot--pulse' : '',
        ]
          .filter(Boolean)
          .join(' ')}
      />
      {STATUS_LABELS[status]}
    </span>
  );
}
