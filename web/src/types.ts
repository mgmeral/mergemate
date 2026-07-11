export interface StartValidationRequest {
  repo_url: string;
  feature_branch: string;
  target_branch: string;
  validation_profile?: string;
  active_maven_profiles?: string[];
}

export interface PlannedModule {
  artifact_id: string;
  label: 'changed' | 'dependent' | 'dependency';
  reason: string;
  estimated_duration_seconds: number;
  estimated_test_count: number;
}

export interface ExecutionPlan {
  strategy: 'full' | 'incremental';
  reason: string;
  modules: PlannedModule[];
  maven_command: string;
  estimated_duration_seconds: number;
  estimated_test_count: number;
}

export interface AffectedModule {
  artifact_id: string;
  label: 'changed' | 'dependent' | 'dependency';
  reason: string;
}

export interface ValidationRun {
  run_id: string;
  status: 'pending' | 'running' | 'success' | 'failure' | 'error';
  started_at: string;
  finished_at: string | null;
  has_conflicts: boolean | null;
  changed_files: string[];
  conflict_files: string[];
  maven_command: string | null;
  lifecycle_log: string[];
  error_message: string | null;
  execution_plan: ExecutionPlan | null;
  repo_url?: string;
  feature_branch?: string;
  target_branch?: string;
  // Impact analysis fields (Phase 5)
  affected_modules?: AffectedModule[];
  selected_tests?: string[];
  risk_level?: string;
}
