/**
 * Explicit UI states.
 *
 * Every repository or documentation operation is in exactly one of these at any
 * time. Nothing in the UI renders from an implicit or unknown state, and no
 * state silently hides an error.
 */
export type WorkflowState =
  | 'IDLE'
  | 'SUBMITTING'
  | 'READY'
  | 'GENERATING'
  | 'COMPLETED'
  | 'FAILED'
  | 'NOT_GENERATED';

export const WORKFLOW_STATE_LABELS: Record<WorkflowState, string> = {
  IDLE: 'Idle',
  SUBMITTING: 'Submitting',
  READY: 'Ready',
  GENERATING: 'Generating',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
  NOT_GENERATED: 'Not generated',
};

/** Tone used by status pills and indicators. */
export type StateTone = 'neutral' | 'progress' | 'success' | 'danger';

export const WORKFLOW_STATE_TONES: Record<WorkflowState, StateTone> = {
  IDLE: 'neutral',
  SUBMITTING: 'progress',
  READY: 'success',
  GENERATING: 'progress',
  COMPLETED: 'success',
  FAILED: 'danger',
  NOT_GENERATED: 'neutral',
};
