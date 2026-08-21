/**
 * Wire contract for documentation generation jobs.
 *
 * A job is CodeOops's own record of one CodeWiki run — distinct from
 * `RepositoryStatus`/`DocumentationStatus`, which describe the coarser,
 * per-repository state. `status` here is the real backend state machine
 * (SUBMITTING -> GENERATING -> RETRIEVING -> COMPLETED/FAILED); nothing in
 * this file invents intermediate progress that the backend doesn't report.
 */

export type JobStatus = 'SUBMITTING' | 'GENERATING' | 'RETRIEVING' | 'COMPLETED' | 'FAILED';

export interface CodeWikiJobInfo {
  readonly codewiki_job_id: string;
  readonly codewiki_status: string | null;
  readonly codewiki_progress: string | null;
  readonly created_at: string | null;
  readonly started_at: string | null;
  readonly completed_at: string | null;
  readonly main_model: string | null;
  readonly commit_id: string | null;
}

export interface DocumentationJob {
  readonly id: string;
  readonly repository_id: string;
  readonly status: JobStatus;
  readonly created_at: string;
  readonly started_at: string | null;
  readonly completed_at: string | null;
  readonly error_code: string | null;
  readonly error_message: string | null;
  readonly progress_message: string | null;
  readonly overview_available: boolean;
  readonly served_from_codewiki_cache: boolean;
  readonly provider: string;
  readonly codewiki: CodeWikiJobInfo | null;
}

export interface JobListResponse {
  readonly items: readonly DocumentationJob[];
  readonly total: number;
}

/** Exactly one of `repository_url` or `repository_id` must be set — the
 * former for a GitHub submission, the latter for an already-registered
 * repository (e.g. from a ZIP upload). */
export interface CreateJobRequest {
  readonly repository_url?: string;
  readonly repository_id?: string;
}

export interface EngineStatus {
  readonly engine: string;
  readonly reachable: boolean;
  readonly base_url: string;
}

export function isTerminalJobStatus(status: JobStatus): boolean {
  return status === 'COMPLETED' || status === 'FAILED';
}

type PipelinePhase = 'SUBMITTING' | 'GENERATING' | 'RETRIEVING' | 'COMPLETED';

/** The happy-path sequence a job moves through, in order. */
const PIPELINE_ORDER: readonly PipelinePhase[] = [
  'SUBMITTING',
  'GENERATING',
  'RETRIEVING',
  'COMPLETED',
];

const PIPELINE_LABELS: Record<PipelinePhase, string> = {
  SUBMITTING: 'Submitting to CodeWiki',
  GENERATING: 'CodeWiki is generating documentation',
  RETRIEVING: 'Verifying and storing the result',
  COMPLETED: 'Documentation ready',
};

export type PipelineStepState = 'done' | 'active' | 'pending';

export interface PipelineStep {
  readonly key: JobStatus;
  readonly label: string;
  readonly state: PipelineStepState;
}

/**
 * The 4-step happy-path checklist, derived only from `job.status`.
 *
 * Not meaningful for a FAILED job — the backend does not record which phase
 * a failure occurred in, so callers should render the failure state
 * separately rather than guessing which step to mark failed.
 */
export function pipelineSteps(job: DocumentationJob): readonly PipelineStep[] {
  const currentIndex = PIPELINE_ORDER.indexOf(job.status as PipelinePhase);
  // COMPLETED is the pipeline's own final step, not a phase still in
  // progress — once reached, every step (including this one) is done.
  const isComplete = job.status === 'COMPLETED';
  return PIPELINE_ORDER.map((key, index) => {
    let state: PipelineStepState = 'pending';
    if (isComplete || index < currentIndex) {
      state = 'done';
    } else if (index === currentIndex) {
      state = 'active';
    }
    return { key, label: PIPELINE_LABELS[key], state };
  });
}
