import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';

import { CodeOopsApiService, repositoryLabel } from '../../shared/data/codeoops-api.service';
import { formatElapsed, httpErrorMessage, relativeTime } from '../../shared/data/format';
import { DocumentationJob } from '../../shared/data/models';
import { PageHeaderComponent } from '../../shared/layout/page-header.component';
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

type Filter = 'all' | 'running' | 'completed' | 'failed';

@Component({
  selector: 'co-job-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    PageHeaderComponent,
    CardComponent,
    StatusPillComponent,
    EmptyStateComponent,
    IconComponent,
    IconTileComponent,
    SkeletonComponent,
  ],
  template: `
    <div class="page stack-lg">
      <co-page-header
        title="Jobs"
        subtitle="Every documentation run submitted to this backend."
        [crumbs]="[{ label: 'Dashboard', link: '/dashboard' }, { label: 'Jobs' }]"
      >
        <div page-actions class="row">
          <button type="button" class="btn btn--ghost btn--sm" (click)="reload()" [disabled]="loading()">
            <co-icon name="refresh" />
            <span>Refresh</span>
          </button>
          <a class="btn btn--primary btn--sm" routerLink="/analyze">
            <co-icon name="plus" />
            <span>New job</span>
          </a>
        </div>
      </co-page-header>

      <co-card flush>
        <div class="toolbar">
          <div class="tabs" role="tablist" aria-label="Filter jobs">
            @for (tab of tabs; track tab.key) {
              <button
                type="button"
                role="tab"
                class="tabs__btn"
                [class.tabs__btn--active]="filter() === tab.key"
                [attr.aria-selected]="filter() === tab.key"
                (click)="filter.set(tab.key)"
              >
                {{ tab.label }}
                <span class="tabs__count">{{ countFor(tab.key) }}</span>
              </button>
            }
          </div>

          <label class="search">
            <co-icon name="search" class="search__icon" />
            <span class="sr-only">Search jobs by repository</span>
            <input
              class="search__input"
              type="search"
              placeholder="Search repository"
              [value]="query()"
              (input)="onQuery($event)"
            />
          </label>
        </div>

        @if (error(); as message) {
          <p class="state state--error" role="alert">{{ message }}</p>
        } @else if (loading()) {
          <ul class="rows">
            @for (row of [1, 2, 3, 4, 5]; track row) {
              <li class="rows__item">
                <co-skeleton width="2.5rem" height="2.5rem" radius="var(--r-md)" />
                <div class="grow stack-sm">
                  <co-skeleton width="35%" height="0.9rem" />
                  <co-skeleton width="22%" height="0.75rem" />
                </div>
                <co-skeleton width="6rem" height="1.4rem" radius="var(--r-pill)" />
              </li>
            }
          </ul>
        } @else if (visible().length) {
          <ul class="rows">
            @for (job of visible(); track job.id) {
              <li class="rows__item">
                <co-icon-tile name="git" [tone]="tileTone(job)" size="md" />

                <a class="rows__main" [routerLink]="['/jobs', job.id]">
                  <span class="rows__title truncate">{{ nameOf(job) }}</span>
                  <span class="rows__meta truncate">{{ job.repository_url }}</span>
                </a>

                <span class="rows__col rows__col--branch">
                  <span class="t-label">Branch</span>
                  <span class="truncate">{{ job.branch || 'default' }}</span>
                </span>

                <span class="rows__col">
                  <span class="t-label">Duration</span>
                  <span>{{ duration(job) }}</span>
                </span>

                <span class="rows__col">
                  <span class="t-label">Submitted</span>
                  <span>{{ submitted(job) }}</span>
                </span>

                <co-status-pill [label]="statusText(job)" [tone]="statusTone(job)" />

                <a class="rows__go" [routerLink]="['/jobs', job.id]" [attr.aria-label]="'Open ' + nameOf(job)">
                  <co-icon name="chevron-right" />
                </a>
              </li>
            }
          </ul>
        } @else if (jobs().length) {
          <co-empty-state
            title="No jobs match this filter"
            message="Change the filter or clear the search to see the rest."
            icon="search"
            compact
          />
        } @else {
          <co-empty-state
            title="No jobs yet"
            message="Submit a repository and it will appear here with live status."
            icon="jobs"
            tone="red"
            compact
          >
            <a class="btn btn--primary btn--sm" routerLink="/analyze">
              <co-icon name="plus" />
              <span>Analyze a repository</span>
            </a>
          </co-empty-state>
        }
      </co-card>
    </div>
  `,
  styles: `
    :host { display: block; }

    .toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--s-4);
      padding: var(--s-4) var(--s-5);
      border-bottom: 1px solid var(--border);
      flex-wrap: wrap;
    }

    .tabs { display: flex; gap: var(--s-1); background: var(--grey-100);
      padding: 0.25rem; border-radius: var(--r-md); flex-wrap: wrap; }

    .tabs__btn {
      display: inline-flex; align-items: center; gap: var(--s-2);
      padding: 0.375rem 0.75rem;
      border: 0; background: none; cursor: pointer;
      border-radius: var(--r-sm);
      font-size: var(--t-sm); font-weight: 600;
      color: var(--text-secondary);
    }

    .tabs__btn--active { background: var(--white); color: var(--text); box-shadow: var(--shadow-xs); }

    .tabs__count {
      font-size: var(--t-xs);
      padding: 0 0.35rem;
      border-radius: var(--r-pill);
      background: var(--grey-200);
      color: var(--grey-700);
    }

    .tabs__btn--active .tabs__count { background: var(--red-50); color: var(--red-500); }

    .search { position: relative; display: flex; align-items: center; min-width: 14rem; }
    .search__icon {
      position: absolute; left: 0.7rem; width: 1.05rem; height: 1.05rem; color: var(--text-muted);
      pointer-events: none;
    }
    .search__input {
      width: 100%;
      padding: 0.5rem 0.75rem 0.5rem 2.25rem;
      border: 1px solid var(--border);
      border-radius: var(--r-md);
      background: var(--white);
      font-size: var(--t-sm);
      &:focus { outline: none; border-color: var(--red-400); box-shadow: 0 0 0 3px var(--red-50); }
    }

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

    .rows__main { display: grid; gap: 0.1rem; flex: 1.6; min-width: 8rem; }
    .rows__title { font-weight: 600; }
    .rows__item:hover .rows__title { color: var(--red-500); }
    .rows__meta { font-size: var(--t-sm); color: var(--text-muted); }

    .rows__col {
      display: grid; gap: 0.1rem; flex: 0 0 7.5rem; min-width: 0;
      font-size: var(--t-sm);
    }

    .rows__go {
      width: 1.75rem; height: 1.75rem; flex: none;
      display: grid; place-items: center;
      border-radius: var(--r-sm);
      color: var(--text-muted);
      co-icon { width: 1.05rem; height: 1.05rem; }
      &:hover { background: var(--grey-100); color: var(--text); }
    }

    .state { padding: var(--s-8) var(--s-5); text-align: center; }
    .state--error { color: var(--err-600); }

    @media (max-width: 980px) {
      .rows__col { display: none; }
    }
  `,
})
export class JobListComponent {
  private readonly api = inject(CodeOopsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly jobs = signal<DocumentationJob[]>([]);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly filter = signal<Filter>('all');
  protected readonly query = signal('');

  protected readonly tabs: ReadonlyArray<{ key: Filter; label: string }> = [
    { key: 'all', label: 'All' },
    { key: 'running', label: 'Running' },
    { key: 'completed', label: 'Completed' },
    { key: 'failed', label: 'Failed' },
  ];

  protected readonly visible = computed(() => {
    const needle = this.query().trim().toLowerCase();
    return this.jobs()
      .filter((job) => this.matchesFilter(job, this.filter()))
      .filter((job) => {
        if (!needle) return true;
        const haystack = `${job.repository_url ?? ''} ${job.repository_name ?? ''} ${job.branch ?? ''}`;
        return haystack.toLowerCase().includes(needle);
      });
  });

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

  protected onQuery(event: Event): void {
    this.query.set((event.target as HTMLInputElement).value);
  }

  protected countFor(filter: Filter): number {
    return this.jobs().filter((job) => this.matchesFilter(job, filter)).length;
  }

  private matchesFilter(job: DocumentationJob, filter: Filter): boolean {
    const status = (job.status ?? '').toUpperCase();
    switch (filter) {
      case 'running':
        return ['QUEUED', 'SUBMITTING', 'GENERATING', 'RETRIEVING'].includes(status);
      case 'completed':
        return status === 'COMPLETED';
      case 'failed':
        return status === 'FAILED';
      default:
        return true;
    }
  }

  protected nameOf(job: DocumentationJob): string {
    return repositoryLabel(job);
  }

  protected submitted(job: DocumentationJob): string {
    return relativeTime(job.created_at ?? job.started_at);
  }

  protected duration(job: DocumentationJob): string {
    return formatElapsed(job.started_at ?? job.created_at, job.completed_at);
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
