import { Injectable, inject } from '@angular/core';
import { EMPTY, Observable, expand, switchMap, timer } from 'rxjs';

import { ApiClient } from '../api/api-client.service';
import {
  CreateJobRequest,
  DocumentationJob,
  EngineStatus,
  JobListResponse,
  isTerminalJobStatus,
} from '../models/job.model';
import { Repository } from '../models/repository.model';

/** Widening backoff so a multi-minute generation doesn't hammer the API. */
const POLL_SCHEDULE_MS: readonly number[] = [1000, 1000, 2000, 2000, 3000, 5000, 8000, 10000];

/**
 * Job-oriented documentation generation.
 *
 * Distinct from `RepositoryService.getDocumentationState`, which reads the
 * coarser, always-current per-repository state. This owns starting a
 * generation run and following its real progress.
 */
@Injectable({ providedIn: 'root' })
export class DocumentationJobService {
  private readonly api = inject(ApiClient);

  /**
   * Start generation for `repository`, regardless of how its source arrived.
   *
   * A GITHUB repository is resubmitted by URL (the backend re-registers it
   * idempotently). An UPLOAD repository has no URL CodeWiki could clone — it
   * was already registered and extracted by `POST /repositories/upload`, so
   * it's referenced by id instead. Both converge on the same job pipeline.
   */
  startGeneration(repository: Repository): Observable<DocumentationJob> {
    const body: CreateJobRequest =
      repository.source === 'UPLOAD'
        ? { repository_id: repository.id }
        : { repository_url: repository.repository_url };
    return this.api.post<DocumentationJob, CreateJobRequest>('/documentation/jobs', body);
  }

  getJob(jobId: string): Observable<DocumentationJob> {
    return this.api.get<DocumentationJob>(`/documentation/jobs/${encodeURIComponent(jobId)}`);
  }

  getOverview(jobId: string): Observable<string> {
    return this.api.getText(`/documentation/jobs/${encodeURIComponent(jobId)}/overview`);
  }

  overviewUrl(jobId: string): string {
    return this.api.buildUrl(`/documentation/jobs/${encodeURIComponent(jobId)}/overview`);
  }

  overviewPdfUrl(jobId: string): string {
    return this.api.buildUrl(`/documentation/jobs/${encodeURIComponent(jobId)}/overview.pdf`);
  }

  overviewCsvUrl(jobId: string): string {
    return this.api.buildUrl(`/documentation/jobs/${encodeURIComponent(jobId)}/overview.csv`);
  }

  listJobsForRepository(repositoryId: string): Observable<JobListResponse> {
    return this.api.get<JobListResponse>(
      `/repositories/${encodeURIComponent(repositoryId)}/jobs`,
    );
  }

  probeEngine(): Observable<EngineStatus> {
    return this.api.get<EngineStatus>('/documentation/engine');
  }

  /**
   * Emits the job's live state on a widening interval and completes on its
   * own once the job reaches a terminal state — never polls forever, never
   * fakes a percentage in between.
   */
  pollJob(jobId: string): Observable<DocumentationJob> {
    let attempt = 0;
    return this.getJob(jobId).pipe(
      expand((job) => {
        if (isTerminalJobStatus(job.status)) {
          return EMPTY;
        }
        const delayMs = POLL_SCHEDULE_MS[Math.min(attempt, POLL_SCHEDULE_MS.length - 1)];
        attempt += 1;
        return timer(delayMs).pipe(switchMap(() => this.getJob(jobId)));
      }),
    );
  }
}
