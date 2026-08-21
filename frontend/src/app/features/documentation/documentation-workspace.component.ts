import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { forkJoin, switchMap } from 'rxjs';

import { ApiError, isApiError } from '../../core/models/api-error.model';
import { DocumentationState } from '../../core/models/documentation.model';
import {
  DocumentationJob,
  isTerminalJobStatus,
  pipelineSteps as computePipelineSteps,
} from '../../core/models/job.model';
import { Repository } from '../../core/models/repository.model';
import { DocumentationJobService } from '../../core/services/documentation-job.service';
import { DocumentationTocItem } from '../../core/services/markdown.service';
import { RepositoryService } from '../../core/services/repository.service';
import { ToastService } from '../../core/services/toast.service';
import { AppShellComponent } from '../../shared/layout/app-shell.component';
import { DocumentationPrismComponent } from '../../shared/ui/documentation-prism.component';
import { StatusPillComponent } from '../../shared/ui/status-pill.component';
import { RepositorySubmitFormComponent } from '../repositories/repository-submit-form.component';
import { DocumentationViewerComponent } from './documentation-viewer.component';

type LoadState = 'IDLE' | 'SUBMITTING' | 'READY' | 'FAILED';

interface GenerationStep {
  readonly label: string;
  readonly detail: string | null;
  readonly tone: 'success' | 'progress' | 'danger' | 'neutral';
  readonly done: boolean;
}

const UNEXPECTED: ApiError = {
  status: 0,
  code: 'UNEXPECTED_ERROR',
  message: 'Unexpected error while loading this repository.',
  details: {},
  offline: false,
};

@Component({
  selector: 'co-documentation-workspace',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DatePipe,
    RouterLink,
    AppShellComponent,
    StatusPillComponent,
    DocumentationPrismComponent,
    DocumentationViewerComponent,
    RepositorySubmitFormComponent,
  ],
  templateUrl: './documentation-workspace.component.html',
  styleUrl: './documentation-workspace.component.scss',
})
export class DocumentationWorkspaceComponent {
  /** Bound from the `documentation/:repositoryId` route. */
  readonly repositoryId = input<string | undefined>(undefined);

  private readonly service = inject(RepositoryService);
  private readonly jobService = inject(DocumentationJobService);
  private readonly toasts = inject(ToastService);
  private readonly injector = inject(Injector);
  private readonly destroyRef = inject(DestroyRef);

  private readonly docContent = viewChild<ElementRef<HTMLElement>>('docContent');

  protected readonly repository = signal<Repository | null>(null);
  protected readonly documentation = signal<DocumentationState | null>(null);
  protected readonly loadState = signal<LoadState>('IDLE');
  protected readonly error = signal<ApiError | null>(null);

  protected readonly toc = signal<readonly DocumentationTocItem[]>([]);
  protected readonly activeHeadingId = signal<string | null>(null);

  /** The job this session is actively tracking — live progress, not history. */
  protected readonly activeJob = signal<DocumentationJob | null>(null);

  /**
   * The most recent job CodeOops has for this repository, fetched on load —
   * distinct from `activeJob`, which is only set once this session starts or
   * resumes a run. Needed so a completed doc's export links have a job id to
   * point at even when the page was opened fresh, not right after generating.
   */
  protected readonly latestJob = signal<DocumentationJob | null>(null);

  /** The job id backing the overview/PDF/CSV export links, if any is known. */
  protected readonly exportJobId = computed(
    () => this.activeJob()?.id ?? this.latestJob()?.id ?? null,
  );

  protected readonly overviewPdfUrl = computed(() => {
    const jobId = this.exportJobId();
    return jobId ? this.jobService.overviewPdfUrl(jobId) : null;
  });

  protected readonly overviewCsvUrl = computed(() => {
    const jobId = this.exportJobId();
    return jobId ? this.jobService.overviewCsvUrl(jobId) : null;
  });

  /** Repositories already known to the service, for the picker. */
  protected readonly knownRepositories = this.service.repositories;

  private headingObserver: IntersectionObserver | null = null;

  protected readonly isGenerating = computed(() => {
    const job = this.activeJob();
    if (job) {
      return !isTerminalJobStatus(job.status);
    }
    const status = this.documentation()?.status;
    return status === 'QUEUED' || status === 'GENERATING';
  });

  protected readonly hasEverGenerated = computed(
    () => this.documentation()?.status === 'COMPLETED',
  );

  protected readonly livePipelineSteps = computed(() => {
    const job = this.activeJob();
    return job && job.status !== 'FAILED' ? computePipelineSteps(job) : [];
  });

  /** Fallback timeline for when nothing has been triggered this session yet. */
  protected readonly generationSteps = computed<readonly GenerationStep[]>(() => {
    const repo = this.repository();
    const doc = this.documentation();
    if (!repo) {
      return [];
    }

    const submitted: GenerationStep = {
      label: 'Repository submitted',
      detail: `${repo.owner}/${repo.name} is registered with CodeOops.`,
      tone: 'success',
      done: true,
    };

    if (!doc) {
      return [submitted];
    }

    const documentationStep = ((): GenerationStep => {
      switch (doc.status) {
        case 'QUEUED':
          return {
            label: 'Queued for generation',
            detail: doc.detail,
            tone: 'progress',
            done: false,
          };
        case 'GENERATING':
          return {
            label: 'CodeWiki is generating documentation',
            detail: doc.detail,
            tone: 'progress',
            done: false,
          };
        case 'COMPLETED':
          return {
            label: 'Documentation generated',
            detail: doc.artifact ? `Produced by ${doc.artifact.provider}.` : doc.detail,
            tone: 'success',
            done: true,
          };
        case 'FAILED':
          return {
            label: 'Generation failed',
            detail: doc.detail ?? 'CodeWiki reported a failure for this repository.',
            tone: 'danger',
            done: true,
          };
        default:
          return {
            label: 'Documentation not started',
            detail: doc.detail ?? 'No documentation provider is connected yet.',
            tone: 'neutral',
            done: false,
          };
      }
    })();

    return [submitted, documentationStep];
  });

  constructor() {
    // Load whenever the route id changes; also refresh the picker list.
    effect(() => {
      const id = this.repositoryId();
      this.activeJob.set(null);
      if (id) {
        this.load(id);
      } else {
        this.repository.set(null);
        this.documentation.set(null);
        this.loadState.set('IDLE');
        this.service.listRepositories().subscribe({ error: () => undefined });
      }
    });

    // Scroll-spy: highlight the TOC entry for the heading currently in view.
    effect(() => {
      const items = this.toc();
      const container = this.docContent()?.nativeElement;

      this.headingObserver?.disconnect();
      this.headingObserver = null;

      if (!container || items.length === 0) {
        this.activeHeadingId.set(null);
        return;
      }

      afterNextRender(
        () => {
          const headings = container.querySelectorAll<HTMLElement>(
            '.doc-prose :is(h2, h3, h4)[id]',
          );
          if (headings.length === 0) {
            return;
          }
          this.headingObserver = new IntersectionObserver(
            (entries) => {
              const visible = entries
                .filter((entry) => entry.isIntersecting)
                .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
              if (visible[0]) {
                this.activeHeadingId.set(visible[0].target.id);
              }
            },
            { rootMargin: '-15% 0px -70% 0px', threshold: 0 },
          );
          headings.forEach((heading) => this.headingObserver?.observe(heading));
        },
        { injector: this.injector },
      );
    });

    this.destroyRef.onDestroy(() => this.headingObserver?.disconnect());
  }

  protected onTocChange(items: readonly DocumentationTocItem[]): void {
    this.toc.set(items);
  }

  protected retry(): void {
    const id = this.repositoryId();
    if (id) {
      this.load(id);
    }
  }

  protected generateDocumentation(): void {
    const repo = this.repository();
    if (!repo || this.isGenerating()) {
      return;
    }

    this.jobService
      .startGeneration(repo)
      .pipe(
        switchMap((job) => {
          this.activeJob.set(job);
          return this.jobService.pollJob(job.id);
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (job) => {
          this.activeJob.set(job);
          if (job.status === 'COMPLETED') {
            this.toasts.success('Documentation generated', `${repo.owner}/${repo.name} is ready.`);
            this.refreshDocumentation(repo.id);
          } else if (job.status === 'FAILED') {
            this.toasts.error(
              'Generation failed',
              job.error_message ?? 'CodeWiki reported a failure for this repository.',
            );
          }
        },
        error: (error: unknown) => {
          const apiError = isApiError(error) ? error : UNEXPECTED;
          this.toasts.error('Could not start generation', apiError.message);
        },
      });
  }

  private load(repositoryId: string): void {
    this.loadState.set('SUBMITTING');
    this.error.set(null);
    this.toc.set([]);
    this.latestJob.set(null);

    forkJoin({
      repository: this.service.getRepository(repositoryId),
      documentation: this.service.getDocumentationState(repositoryId),
    }).subscribe({
      next: ({ repository, documentation }) => {
        this.repository.set(repository);
        this.documentation.set(documentation);
        this.loadState.set('READY');
        this.loadLatestJob(repositoryId);
      },
      error: (error: unknown) => {
        this.repository.set(null);
        this.documentation.set(null);
        this.error.set(isApiError(error) ? error : UNEXPECTED);
        this.loadState.set('FAILED');
      },
    });
  }

  /**
   * Fetches the most recent job for this repository — populates `latestJob`
   * (so a completed doc's export links have a job id even on a fresh page
   * load) and, if that job is still in flight, resumes live polling for it.
   */
  private loadLatestJob(repositoryId: string): void {
    this.jobService.listJobsForRepository(repositoryId).subscribe({
      next: (page) => {
        const latest = page.items[0];
        if (!latest) {
          return;
        }
        this.latestJob.set(latest);
        if (isTerminalJobStatus(latest.status)) {
          return;
        }
        this.activeJob.set(latest);
        this.jobService
          .pollJob(latest.id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: (job) => {
              this.activeJob.set(job);
              this.latestJob.set(job);
              if (job.status === 'COMPLETED') {
                this.refreshDocumentation(repositoryId);
              }
            },
            error: () => undefined,
          });
      },
      error: () => undefined,
    });
  }

  private refreshDocumentation(repositoryId: string): void {
    this.service.getDocumentationState(repositoryId).subscribe({
      next: (documentation) => this.documentation.set(documentation),
      error: () => undefined,
    });
  }
}
