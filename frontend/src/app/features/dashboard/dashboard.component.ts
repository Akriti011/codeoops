import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';

import { CodeOopsApiService, repositoryLabel } from '../../shared/data/codeoops-api.service';
import { httpErrorMessage, relativeTime } from '../../shared/data/format';
import { DocumentationJob } from '../../shared/data/models';
import { CardComponent } from '../../shared/ui/card.component';
import { EmptyStateComponent } from '../../shared/ui/empty-state.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { IconTileComponent } from '../../shared/ui/icon-tile.component';
import { SkeletonComponent } from '../../shared/ui/skeleton.component';
import {
  StatusPillComponent,
  humanStatus,
  toneForStatus,
} from '../../shared/ui/status-pill.component';

/**
 * Home screen inside the shell.
 *
 * Framed as a document generator, not an analytics dashboard: a hero
 * invites a new generation, and the rest of the page is the list of
 * documents already produced. Every row is counted from jobs the backend
 * returned — nothing here is ever filled in with a sample value.
 */
@Component({
  selector: 'co-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    CardComponent,
    StatusPillComponent,
    EmptyStateComponent,
    IconComponent,
    IconTileComponent,
    SkeletonComponent,
  ],
  template: `
    <div class="page stack-lg">
      <!-- ---------------- hero ---------------- -->
      <section class="hero animate-in">
        <div class="hero__text">
          <p class="hero__eyebrow">
            <span class="hero__dot" aria-hidden="true"></span>
            Document generator
          </p>
          <h1 class="hero__title">Turn a repository into a document.</h1>
          <p class="hero__lede">
            Point it at a Git URL or upload a ZIP. It reads the code and writes the document.
          </p>
        </div>
        <a class="btn btn--primary btn--lg hero__cta" routerLink="/analyze">
          <co-icon name="plus" />
          <span>Generate a document</span>
        </a>
      </section>

      @if (error(); as message) {
        <div class="banner" role="alert">
          <co-icon name="alert" class="banner__icon" />
          <div>
            <p class="banner__title">Could not load your documents</p>
            <p class="banner__text">{{ message }}</p>
          </div>
          <button type="button" class="btn btn--ghost btn--sm" (click)="reload()">Try again</button>
        </div>
      }

      <!-- ---------------- document list ---------------- -->
      <co-card title="Your documents" subtitle="Most recent generation runs" flush>
        <div card-actions class="row">
          <button type="button" class="btn btn--ghost btn--sm" (click)="reload()" [disabled]="loading()">
            <co-icon name="refresh" />
            <span>Refresh</span>
          </button>
          <a class="btn btn--quiet btn--sm" routerLink="/jobs">
            <span>View all</span>
            <co-icon name="arrow-right" />
          </a>
        </div>

        @if (loading()) {
          <ul class="rows">
            @for (row of [1, 2, 3, 4]; track row) {
              <li class="rows__item rows__item--skeleton">
                <co-skeleton width="2.5rem" height="2.5rem" radius="var(--r-md)" />
                <div class="grow stack-sm">
                  <co-skeleton width="45%" height="0.9rem" />
                  <co-skeleton width="30%" height="0.75rem" />
                </div>
                <co-skeleton width="5rem" height="1.4rem" radius="var(--r-pill)" />
              </li>
            }
          </ul>
        } @else if (recentJobs().length) {
          <ul class="rows">
            @for (job of recentJobs(); track job.id) {
              <li class="rows__item animate-in">
                <co-icon-tile name="git" [tone]="tileTone(job)" size="md" />
                <a class="rows__main" [routerLink]="['/jobs', job.id]">
                  <span class="rows__title truncate">{{ label(job) }}</span>
                  <span class="rows__meta truncate">
                    {{ job.branch || 'default branch' }} · {{ when(job) }}
                  </span>
                </a>
                <co-status-pill
                  [label]="statusText(job)"
                  [tone]="statusTone(job)"
                  [class.pulse-live]="statusTone(job) === 'progress'"
                />
              </li>
            }
          </ul>
        } @else {
          <co-empty-state
            title="No documents yet"
            message="Generate your first document from a repository — it will show up here."
            icon="documentation"
            tone="red"
            compact
          >
            <a class="btn btn--primary btn--sm" routerLink="/analyze">
              <co-icon name="plus" />
              <span>Generate a document</span>
            </a>
          </co-empty-state>
        }
      </co-card>
    </div>
  `,
  styles: `
    :host { display: block; }

    .hero {
      position: relative;
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--s-6);
      padding: var(--s-10) var(--s-8);
      border-radius: var(--r-xl);
      background:
        radial-gradient(46rem 20rem at 92% -30%, var(--red-50), transparent 60%),
        var(--white);
      border: 1px solid var(--border);
      box-shadow: var(--shadow-sm);
    }

    .hero__eyebrow {
      display: inline-flex; align-items: center; gap: var(--s-2);
      padding: 0.3rem 0.75rem;
      border-radius: var(--r-pill);
      background: var(--white);
      border: 1px solid var(--red-100);
      color: var(--red-600);
      font-size: var(--t-sm); font-weight: 600;
      box-shadow: var(--shadow-xs);
    }

    .hero__dot { width: 6px; height: 6px; border-radius: 50%; background: var(--red-500); }

    .hero__title {
      margin-top: var(--s-4);
      font-size: var(--t-2xl, 1.75rem);
      font-weight: 700;
      letter-spacing: -0.01em;
      max-width: 30rem;
    }

    .hero__lede { margin-top: var(--s-2); color: var(--text-secondary); max-width: 30rem; }

    .hero__cta { flex: none; }

    @media (max-width: 720px) {
      .hero { flex-direction: column; align-items: flex-start; }
      .hero__cta { width: 100%; justify-content: center; }
    }

    .banner {
      display: flex;
      align-items: flex-start;
      gap: var(--s-3);
      padding: var(--s-4) var(--s-5);
      background: var(--err-50);
      border: 1px solid #FECDCA;
      border-radius: var(--r-lg);
    }

    .banner__icon { width: 1.25rem; height: 1.25rem; color: var(--err-600); flex: none; margin-top: 0.1rem; }
    .banner__title { font-weight: 650; color: var(--err-600); }
    .banner__text { font-size: var(--t-sm); color: var(--grey-700); }
    .banner > :last-child { margin-left: auto; flex: none; }

    .rows { display: grid; }

    .rows__item {
      display: flex;
      align-items: center;
      gap: var(--s-4);
      padding: var(--s-4) var(--s-5);
      border-top: 1px solid var(--border);
    }

    .rows__item:first-child { border-top: 0; }
    .rows__item:hover { background: var(--grey-50); }
    .rows__item--skeleton:hover { background: none; }

    .rows__main { display: grid; gap: 0.1rem; flex: 1; min-width: 0; }
    .rows__title { font-weight: 600; }
    .rows__item:hover .rows__title { color: var(--red-500); }
    .rows__meta { font-size: var(--t-sm); color: var(--text-muted); }

  `,
})
export class DashboardComponent {
  private readonly api = inject(CodeOopsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly jobs = signal<DocumentationJob[]>([]);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);

  protected readonly recentJobs = computed(() => this.jobs().slice(0, 6));

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.api
      .listJobs()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (jobs) => {
          this.jobs.set(jobs ?? []);
          this.error.set(null);
          this.loading.set(false);
        },
        error: (err: unknown) => {
          this.jobs.set([]);
          this.error.set(httpErrorMessage(err, 'The request for jobs did not complete.'));
          this.loading.set(false);
        },
      });
  }

  protected label(job: DocumentationJob): string {
    return repositoryLabel(job);
  }

  protected when(job: DocumentationJob): string {
    return relativeTime(job.created_at ?? job.started_at);
  }

  protected statusText(job: DocumentationJob): string {
    return humanStatus(job.status);
  }

  protected statusTone(job: DocumentationJob) {
    return toneForStatus(job.status);
  }

  protected tileTone(job: DocumentationJob): 'green' | 'blue' | 'amber' | 'grey' {
    switch (toneForStatus(job.status)) {
      case 'success':
        return 'green';
      case 'progress':
        return 'blue';
      case 'danger':
        return 'amber';
      default:
        return 'grey';
    }
  }
}
