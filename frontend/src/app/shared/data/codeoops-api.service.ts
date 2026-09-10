import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, forkJoin, map, of, switchMap } from 'rxjs';

import {
  CreateJobRequest,
  DashboardStats,
  DocumentationArtifact,
  DocumentationJob,
} from './models';

/* ==========================================================================
   THE ONLY FILE IN THIS UI THAT TOUCHES THE BACKEND.
   --------------------------------------------------------------------------
   Wired against the real CodeOops FastAPI routes:

     GET  /api/v1/documentation/jobs               (repository_id optional —
                                                      omitted, it lists every
                                                      job the backend knows
                                                      about)
     GET  /api/v1/documentation/jobs/{id}
     POST /api/v1/documentation/jobs                {repository_url}
     GET  /api/v1/documentation/jobs/{id}/overview  (raw overview.md bytes)
     GET  /api/v1/repositories
     GET  /api/v1/repositories/{id}
     GET  /api/v1/stats

   A job on this backend carries only `repository_id`, not the repository's
   URL/owner/name — those live on the repository record. Every method below
   joins a job against its repository before handing a `DocumentationJob` to
   a screen, so `repository_url` / `repository_name` / `branch` are always
   real values read from `GET /repositories`, never guessed from the job
   alone.
   ========================================================================== */

const API_BASE = '/api/v1';

const ENDPOINTS = {
  jobs: `${API_BASE}/documentation/jobs`,
  job: (id: string) => `${API_BASE}/documentation/jobs/${encodeURIComponent(id)}`,
  jobOverview: (id: string) =>
    `${API_BASE}/documentation/jobs/${encodeURIComponent(id)}/overview`,
  repositories: `${API_BASE}/repositories`,
  repository: (id: string) => `${API_BASE}/repositories/${encodeURIComponent(id)}`,
  bin: `${API_BASE}/repositories/bin`,
  repositoryRestore: (id: string) =>
    `${API_BASE}/repositories/${encodeURIComponent(id)}/restore`,
  repositoryPurge: (id: string) =>
    `${API_BASE}/repositories/${encodeURIComponent(id)}/bin`,
  stats: `${API_BASE}/stats`,
} as const;

/** Shape of `app.schemas.job.JobResponse`. */
interface RawJob {
  id: string;
  repository_id: string;
  status: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_code: string | null;
  error_message: string | null;
  overview_available: boolean;
  codewiki: {
    codewiki_job_id: string;
    codewiki_status: string | null;
    started_at: string | null;
    completed_at: string | null;
    main_model: string | null;
  } | null;
}

interface RawJobList {
  items: RawJob[];
  total: number;
}

/** Shape of `app.schemas.repository.RepositoryResponse` (fields we use). */
interface RawRepository {
  id: string;
  owner: string;
  name: string;
  repository_url: string;
  default_branch: string;
}

interface RawRepositoryList {
  items: RawRepository[];
  total: number;
}

/** Shape of `app.schemas.stats.StatsResponse`. */
interface RawStats {
  repository_count: number;
  job_counts: { completed: number; in_progress: number; failed: number };
}

/** Shape of `app.schemas.repository.BinnedRepositoryResponse`. */
interface RawBinnedRepository {
  repository: RawRepository & {
    source: string;
    upload_original_filename: string | null;
  };
  binned_at: string;
  job_count: number;
  has_overview: boolean;
}

/** One row in the Bin view. */
export interface BinItem {
  repository_id: string;
  label: string;
  repository_url: string;
  source: string;
  binned_at: string;
  job_count: number;
  has_overview: boolean;
}

@Injectable({ providedIn: 'root' })
export class CodeOopsApiService {
  private readonly http = inject(HttpClient);

  /** Every job the backend knows about, newest first, joined with its repository. */
  listJobs(): Observable<DocumentationJob[]> {
    return forkJoin({
      jobs: this.http.get<RawJobList>(ENDPOINTS.jobs),
      repositories: this.http.get<RawRepositoryList>(ENDPOINTS.repositories),
    }).pipe(
      map(({ jobs, repositories }) => {
        const byId = new Map(repositories.items.map((r) => [r.id, r]));
        return jobs.items.map((job) => toDocumentationJob(job, byId.get(job.repository_id)));
      }),
    );
  }

  /** One job, joined with its repository. Safe to poll — used every 3s while a job runs. */
  getJob(id: string): Observable<DocumentationJob> {
    return this.http.get<RawJob>(ENDPOINTS.job(id)).pipe(
      switchMap((job) =>
        this.http.get<RawRepository>(ENDPOINTS.repository(job.repository_id)).pipe(
          map((repo) => toDocumentationJob(job, repo)),
          // A repository lookup failing must not hide the job itself — the
          // job still renders, just without the joined repository fields.
          catchError(() => of(toDocumentationJob(job, undefined))),
        ),
      ),
    );
  }

  /** Submit a repository URL for documentation generation. */
  createJob(request: CreateJobRequest): Observable<DocumentationJob> {
    return this.http
      .post<RawJob>(ENDPOINTS.jobs, { repository_url: request.repository_url })
      .pipe(
        switchMap((job) =>
          this.http.get<RawRepository>(ENDPOINTS.repository(job.repository_id)).pipe(
            map((repo) => toDocumentationJob(job, repo)),
            catchError(() => of(toDocumentationJob(job, undefined))),
          ),
        ),
      );
  }

  /**
   * Fetch the overview CodeWiki produced for a job.
   *
   * `name` is accepted for interface compatibility with the documents rail,
   * but this backend has exactly one document per job — `overview.md` — so
   * every call resolves to the same endpoint. A 404 (unknown job) or 409
   * (no verified overview yet) here means the document genuinely does not
   * exist; callers surface that as an empty state, never as placeholder prose.
   */
  getDocument(jobId: string, name: string): Observable<DocumentationArtifact> {
    return this.http
      .get(ENDPOINTS.jobOverview(jobId), { responseType: 'text' })
      .pipe(map((content) => ({ name, content }) satisfies DocumentationArtifact));
  }

  /**
   * Move a repository (and its documentation jobs) to the bin. Nothing is
   * destroyed — the overview, the extracted archive and CodeWiki's state
   * stay put, so `restoreRepository` is a true undo. Resolves on 204.
   */
  deleteRepository(repositoryId: string): Observable<void> {
    return this.http
      .delete(ENDPOINTS.repository(repositoryId), { observe: 'response' })
      .pipe(map(() => undefined));
  }

  /** Everything currently in the bin, newest first. */
  listBin(): Observable<BinItem[]> {
    return this.http.get<{ items: RawBinnedRepository[] }>(ENDPOINTS.bin).pipe(
      map((res) =>
        (res.items ?? []).map((row) => ({
          repository_id: row.repository.id,
          label:
            row.repository.source === 'UPLOAD'
              ? row.repository.upload_original_filename || row.repository.name
              : `${row.repository.owner}/${row.repository.name}`,
          repository_url: row.repository.repository_url,
          source: row.repository.source,
          binned_at: row.binned_at,
          job_count: row.job_count,
          has_overview: row.has_overview,
        })),
      ),
    );
  }

  /** Bring a binned repository — and its binned jobs — back to the live set. */
  restoreRepository(repositoryId: string): Observable<void> {
    return this.http
      .post(ENDPOINTS.repositoryRestore(repositoryId), null, { observe: 'response' })
      .pipe(map(() => undefined));
  }

  /**
   * Erase a binned repository for good: record, jobs, stored overview,
   * CodeWiki output + registry, and the extracted archive. No undo.
   */
  purgeRepository(repositoryId: string): Observable<void> {
    return this.http
      .delete(ENDPOINTS.repositoryPurge(repositoryId), { observe: 'response' })
      .pipe(map(() => undefined));
  }

  /** Dashboard counters, computed by the backend from real stored rows. */
  getStats(): Observable<DashboardStats> {
    return this.http.get<RawStats>(ENDPOINTS.stats).pipe(
      map((stats) => ({
        repositories: stats.repository_count,
        jobs_total:
          stats.job_counts.completed + stats.job_counts.in_progress + stats.job_counts.failed,
        jobs_running: stats.job_counts.in_progress,
        jobs_completed: stats.job_counts.completed,
        jobs_failed: stats.job_counts.failed,
        documents: stats.job_counts.completed,
      })),
    );
  }
}

/** Real math on two real timestamps — not a fabricated figure. */
function computeDurationSeconds(
  started: string | null,
  finished: string | null,
): number | null {
  if (!started || !finished) return null;
  const start = new Date(started).getTime();
  const end = new Date(finished).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  return Math.max(0, Math.round((end - start) / 1000));
}

function toDocumentationJob(job: RawJob, repo: RawRepository | undefined): DocumentationJob {
  return {
    id: job.id,
    repository_id: job.repository_id,
    repository_url: repo?.repository_url ?? null,
    repository_name: repo ? `${repo.owner}/${repo.name}` : null,
    branch: repo?.default_branch ?? null,
    status: job.status,
    created_at: job.created_at,
    started_at: job.started_at,
    completed_at: job.completed_at,
    error_code: job.error_code,
    error_message: job.error_message,
    overview_available: job.overview_available,
    modules_total: null,
    modules_completed: null,
    codewiki: job.codewiki
      ? {
          job_id: job.codewiki.codewiki_job_id,
          status: job.codewiki.codewiki_status,
          model: job.codewiki.main_model,
          started_at: job.codewiki.started_at,
          finished_at: job.codewiki.completed_at,
          duration_seconds: computeDurationSeconds(
            job.codewiki.started_at,
            job.codewiki.completed_at,
          ),
        }
      : null,
  };
}

/**
 * Counters computed from the job list alone.
 *
 * Not used by the dashboard by default (it calls `getStats()` above, which
 * reads the real `/stats` endpoint), but kept as a same-shape fallback for
 * any screen that only has a job list to work with. Everything here is
 * counted from real records — there is no estimate and no default.
 */
export function deriveStats(jobs: readonly DocumentationJob[]): DashboardStats {
  const status = (job: DocumentationJob): string => (job.status ?? '').toUpperCase();

  const repositories = new Set(
    jobs.map((j) => j.repository_id ?? j.repository_url).filter((v): v is string => !!v),
  );

  return {
    repositories: repositories.size,
    jobs_total: jobs.length,
    jobs_running: jobs.filter((j) =>
      ['QUEUED', 'SUBMITTING', 'GENERATING', 'RETRIEVING'].includes(status(j)),
    ).length,
    jobs_completed: jobs.filter((j) => status(j) === 'COMPLETED').length,
    jobs_failed: jobs.filter((j) => status(j) === 'FAILED').length,
    documents: jobs.filter((j) => status(j) === 'COMPLETED').length,
  };
}

/** Best-effort display name for a repository, without inventing one. */
export function repositoryLabel(job: DocumentationJob | null | undefined): string {
  if (!job) return 'Unknown repository';
  if (job.repository_name) return job.repository_name;

  const url = job.repository_url;
  if (!url) return 'Unknown repository';

  const trimmed = url.replace(/\.git$/i, '').replace(/\/+$/, '');
  const parts = trimmed.split('/').filter(Boolean);
  if (parts.length >= 2) return `${parts[parts.length - 2]}/${parts[parts.length - 1]}`;
  return parts[parts.length - 1] ?? url;
}
