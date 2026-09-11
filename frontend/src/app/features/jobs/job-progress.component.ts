import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Subscription, timer } from 'rxjs';
import { switchMap } from 'rxjs/operators';

import { CodeOopsApiService, repositoryLabel } from '../../shared/data/codeoops-api.service';
import {
  formatDateTime,
  formatDuration,
  formatElapsed,
  httpErrorMessage,
  isTerminal,
} from '../../shared/data/format';
import { DocumentationJob } from '../../shared/data/models';
import { PageHeaderComponent } from '../../shared/layout/page-header.component';
import { CardComponent } from '../../shared/ui/card.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { IconTileComponent } from '../../shared/ui/icon-tile.component';
import { ProgressBarComponent } from '../../shared/ui/progress-bar.component';
import { SkeletonComponent } from '../../shared/ui/skeleton.component';
import {
  StatusPillComponent,
  humanStatus,
  toneForStatus,
} from '../../shared/ui/status-pill.component';

const POLL_INTERVAL_MS = 3000;

/** The pipeline stages, in the order the backend moves through them. */
const STAGES: ReadonlyArray<{ status: string; label: string; description: string }> = [
  { status: 'QUEUED', label: 'Queued', description: 'Waiting for a worker to pick the job up.' },
  { status: 'SUBMITTING', label: 'Submitting for analysis', description: 'Handing the repository to the documentation engine.' },
  { status: 'GENERATING', label: 'Generating documentation', description: 'Parsing files, clustering modules and writing summaries.' },
  { status: 'RETRIEVING', label: 'Retrieving artifacts', description: 'Fetching the generated files and verifying they belong to this repository.' },
  { status: 'COMPLETED', label: 'Completed', description: 'The overview is available.' },
];

type StageState = 'done' | 'current' | 'pending' | 'failed';

@Component({
  selector: 'co-job-progress',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    PageHeaderComponent,
    CardComponent,
    StatusPillComponent,
    ProgressBarComponent,
    IconComponent,
    IconTileComponent,
    SkeletonComponent,
  ],
  template: `
    <div class="page stack-lg">
      <co-page-header
        [title]="heading()"
        [subtitle]="job()?.repository_url ?? null"
        [crumbs]="[
          { label: 'Home', link: '/dashboard' },
          { label: 'Documents', link: '/jobs' },
          { label: 'Progress' }
        ]"
      >
        <div page-actions class="row">
          @if (job(); as j) {
            <co-status-pill [label]="statusText()" [tone]="statusTone()" />
            @if (completed()) {
              <a class="btn btn--primary btn--sm" [routerLink]="['/documentation', j.id]">
                <co-icon name="documentation" />
                <span>View documentation</span>
              </a>
            }
          }
        </div>
      </co-page-header>

      @if (error(); as message) {
        <co-card>
          <div class="alert" role="alert">
            <co-icon name="alert" class="alert__icon" />
            <div>
              <p class="alert__title">Could not load this job</p>
              <p class="alert__text">{{ message }}</p>
            </div>
            <a class="btn btn--ghost btn--sm" routerLink="/jobs">Back to documentation</a>
          </div>
        </co-card>
      } @else if (!job()) {
        <co-card>
          <div class="stack">
            <co-skeleton width="40%" height="1.25rem" />
            <co-skeleton width="100%" height="0.5rem" radius="var(--r-pill)" />
            <co-skeleton width="100%" height="9rem" radius="var(--r-md)" />
          </div>
        </co-card>
      } @else {
        <!-- ---------------- progress ---------------- -->
        <co-card>
          <div class="stack-lg">
            <co-progress-bar
              [completed]="job()?.modules_completed ?? null"
              [total]="job()?.modules_total ?? null"
              [label]="progressLabel()"
              [indeterminateLabel]="failed() ? 'Failed' : completed() ? 'Complete' : 'In progress'"
            />

            <div class="facts">
              <div class="facts__cell">
                <span class="t-label">Status</span>
                <span class="facts__value">{{ statusText() }}</span>
              </div>
              <div class="facts__cell">
                <span class="t-label">Default branch</span>
                <span class="facts__value">{{ job()?.branch || '—' }}</span>
              </div>
              <div class="facts__cell">
                <span class="t-label">Elapsed</span>
                <span class="facts__value">{{ elapsed() }}</span>
              </div>
              <div class="facts__cell">
                <span class="t-label">Modules</span>
                <span class="facts__value">{{ moduleText() }}</span>
              </div>
            </div>
          </div>
        </co-card>

        <div class="split">
          <!-- ---------------- stages ---------------- -->
          <co-card title="Pipeline" subtitle="Stages reported by the backend">
            <ol class="stages">
              @for (stage of stages(); track stage.label) {
                <li class="stages__item" [attr.data-state]="stage.state">
                  <span class="stages__marker" aria-hidden="true">
                    @if (stage.state === 'done') {
                      <co-icon name="check" />
                    } @else if (stage.state === 'failed') {
                      <co-icon name="x" />
                    } @else {
                      <span class="stages__dot"></span>
                    }
                  </span>
                  <div class="stages__body">
                    <p class="stages__label">{{ stage.label }}</p>
                    <p class="stages__desc">{{ stage.description }}</p>
                  </div>
                </li>
              }
            </ol>
          </co-card>

          <!-- ---------------- run details ---------------- -->
          <div class="stack-lg">
            @if (failed()) {
              <co-card title="Failure">
                <div class="failure">
                  <co-icon-tile name="alert" tone="amber" size="md" />
                  <div class="stack-sm">
                    <p class="failure__code">
                      {{ job()?.error_code || 'Reported without a failure code' }}
                    </p>
                    <p class="failure__text">
                      {{ job()?.error_message || 'The backend did not include a message.' }}
                    </p>
                  </div>
                </div>
                <div class="row" style="margin-top: var(--s-4)">
                  <a class="btn btn--ghost btn--sm" routerLink="/analyze">
                    <co-icon name="refresh" />
                    <span>Submit again</span>
                  </a>
                </div>
              </co-card>
            }

            <co-card title="Run details">
              <dl class="meta">
                <div class="meta__row">
                  <dt>Job ID</dt>
                  <dd class="t-mono">{{ job()?.id }}</dd>
                </div>
                <div class="meta__row">
                  <dt>Created</dt>
                  <dd>{{ dateOf(job()?.created_at) }}</dd>
                </div>
                <div class="meta__row">
                  <dt>Started</dt>
                  <dd>{{ dateOf(job()?.started_at) }}</dd>
                </div>
                <div class="meta__row">
                  <dt>Completed</dt>
                  <dd>{{ dateOf(job()?.completed_at) }}</dd>
                </div>
                @if (job()?.codewiki; as run) {
                  <div class="meta__row">
                    <dt>Engine job</dt>
                    <dd class="t-mono">{{ run.job_id || '—' }}</dd>
                  </div>
                  <div class="meta__row">
                    <dt>Model</dt>
                    <dd>{{ run.model || '—' }}</dd>
                  </div>
                  <div class="meta__row">
                    <dt>Engine duration</dt>
                    <dd>{{ engineDuration() }}</dd>
                  </div>
                }
              </dl>

              @if (polling()) {
                <p class="polling">
                  <span class="polling__dot" aria-hidden="true"></span>
                  <span>Refreshing every {{ pollSeconds }} seconds while the job is running.</span>
                </p>
              }
            </co-card>
          </div>
        </div>
      }
    </div>
  `,
  styles: `
    :host { display: block; }

    .split {
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
      gap: var(--s-6);
      align-items: start;
    }

    @media (max-width: 1080px) {
      .split { grid-template-columns: minmax(0, 1fr); }
    }

    .facts {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: var(--s-4);
      padding-top: var(--s-4);
      border-top: 1px solid var(--border);
    }

    @media (max-width: 720px) {
      .facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }

    .facts__cell { display: grid; gap: 0.15rem; min-width: 0; }
    .facts__value { font-size: var(--t-md); font-weight: 650; }

    .stages { display: grid; }

    .stages__item {
      display: flex;
      gap: var(--s-4);
      padding-bottom: var(--s-5);
      position: relative;
    }

    .stages__item:last-child { padding-bottom: 0; }

    .stages__item::before {
      content: '';
      position: absolute;
      left: 0.6875rem;
      top: 1.6rem;
      bottom: 0.2rem;
      width: 2px;
      background: var(--grey-200);
    }

    .stages__item:last-child::before { display: none; }
    .stages__item[data-state='done']::before { background: var(--ok-500); }

    .stages__marker {
      position: relative;
      z-index: 1;
      flex: none;
      width: 1.5rem; height: 1.5rem;
      border-radius: 50%;
      display: grid; place-items: center;
      background: var(--grey-100);
      color: var(--grey-400);
      border: 2px solid var(--white);
      box-shadow: 0 0 0 1px var(--grey-200);
      co-icon { width: 0.85rem; height: 0.85rem; }
    }

    .stages__dot { width: 0.4rem; height: 0.4rem; border-radius: 50%; background: currentColor; }

    .stages__item[data-state='done'] .stages__marker {
      background: var(--ok-500); color: #fff; box-shadow: 0 0 0 1px var(--ok-500);
    }

    .stages__item[data-state='current'] .stages__marker {
      background: var(--info-500); color: #fff; box-shadow: 0 0 0 4px var(--info-50);
    }

    .stages__item[data-state='failed'] .stages__marker {
      background: var(--err-500); color: #fff; box-shadow: 0 0 0 1px var(--err-500);
    }

    @media (prefers-reduced-motion: no-preference) {
      .stages__item[data-state='current'] .stages__marker { animation: pulse 1.8s var(--ease) infinite; }
    }

    @keyframes pulse {
      50% { box-shadow: 0 0 0 7px rgba(46, 144, 250, 0.14); }
    }

    .stages__label { font-weight: 650; font-size: var(--t-sm); }
    .stages__item[data-state='pending'] .stages__label { color: var(--text-muted); }
    .stages__desc { font-size: var(--t-sm); color: var(--text-secondary); }

    .meta { display: grid; gap: var(--s-3); }
    .meta__row { display: flex; justify-content: space-between; gap: var(--s-4); font-size: var(--t-sm); }
    .meta__row dt { color: var(--text-secondary); flex: none; }
    .meta__row dd { margin: 0; text-align: right; font-weight: 600; word-break: break-all; }

    .alert { display: flex; align-items: flex-start; gap: var(--s-3); }
    .alert__icon { width: 1.25rem; height: 1.25rem; color: var(--err-600); flex: none; margin-top: 0.1rem; }
    .alert__title { font-weight: 650; color: var(--err-600); }
    .alert__text { font-size: var(--t-sm); color: var(--grey-700); }
    .alert > :last-child { margin-left: auto; flex: none; }

    .failure { display: flex; gap: var(--s-3); align-items: flex-start; }
    .failure__code { font-family: var(--mono); font-size: var(--t-sm); font-weight: 600; color: var(--err-600); }
    .failure__text { font-size: var(--t-sm); color: var(--text-secondary); }

    .polling {
      display: flex; align-items: center; gap: var(--s-2);
      margin-top: var(--s-4); padding-top: var(--s-3);
      border-top: 1px solid var(--border);
      font-size: var(--t-xs); color: var(--text-muted);
    }

    .polling__dot {
      width: 6px; height: 6px; border-radius: 50%; background: var(--info-500); flex: none;
    }

    @media (prefers-reduced-motion: no-preference) {
      .polling__dot { animation: blink 1.4s ease-in-out infinite; }
    }

    @keyframes blink { 50% { opacity: 0.25; } }
  `,
})
export class JobProgressComponent {
  private readonly api = inject(CodeOopsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly pollSeconds = POLL_INTERVAL_MS / 1000;

  protected readonly job = signal<DocumentationJob | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly polling = signal(false);

  private subscription: Subscription | null = null;

  protected readonly completed = computed(
    () => (this.job()?.status ?? '').toUpperCase() === 'COMPLETED',
  );

  protected readonly failed = computed(
    () => (this.job()?.status ?? '').toUpperCase() === 'FAILED',
  );

  protected readonly heading = computed(() => {
    const job = this.job();
    return job ? repositoryLabel(job) : 'Documentation job';
  });

  protected readonly statusText = computed(() => humanStatus(this.job()?.status));
  protected readonly statusTone = computed(() => toneForStatus(this.job()?.status));

  protected readonly progressLabel = computed(() =>
    this.completed() ? 'Generation complete' : 'Module generation',
  );

  protected readonly elapsed = computed(() => {
    const job = this.job();
    if (!job) return '—';
    return formatElapsed(job.started_at ?? job.created_at, job.completed_at);
  });

  protected readonly moduleText = computed(() => {
    const job = this.job();
    const total = job?.modules_total;
    const done = job?.modules_completed;
    if (total === null || total === undefined) return '—';
    return `${done ?? 0} / ${total}`;
  });

  protected readonly engineDuration = computed(() =>
    formatDuration(this.job()?.codewiki?.duration_seconds ?? null),
  );

  protected readonly stages = computed(() => {
    const status = (this.job()?.status ?? '').toUpperCase();
    const failed = status === 'FAILED';
    const index = STAGES.findIndex((s) => s.status === status);

    return STAGES.map((stage, i) => {
      let state: StageState;
      if (failed) {
        state = i === 0 ? 'failed' : 'pending';
      } else if (index === -1) {
        state = 'pending';
      } else if (i < index) {
        state = 'done';
      } else if (i === index) {
        state = status === 'COMPLETED' ? 'done' : 'current';
      } else {
        state = 'pending';
      }
      return { ...stage, state };
    });
  });

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id');
      this.subscription?.unsubscribe();
      this.subscription = null;
      this.job.set(null);
      this.error.set(null);

      if (!id) {
        this.error.set('No job id was supplied in the URL.');
        return;
      }
      this.start(id);
    });
  }

  private start(id: string): void {
    this.polling.set(true);
    this.subscription = timer(0, POLL_INTERVAL_MS)
      .pipe(
        switchMap(() => this.api.getJob(id)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (job) => {
          this.job.set(job);
          this.error.set(null);
          if (isTerminal(job?.status)) {
            this.polling.set(false);
            this.subscription?.unsubscribe();
            this.subscription = null;
          }
        },
        error: (err: unknown) => {
          this.polling.set(false);
          this.error.set(httpErrorMessage(err, 'The request for this job did not complete.'));
        },
      });
  }

  protected dateOf(value: string | null | undefined): string {
    return formatDateTime(value);
  }
}
