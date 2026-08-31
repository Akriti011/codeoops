import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { CodeOopsApiService, repositoryLabel } from '../../shared/data/codeoops-api.service';
import { httpErrorMessage, relativeTime } from '../../shared/data/format';
import { DocumentationJob } from '../../shared/data/models';
import { PageHeaderComponent } from '../../shared/layout/page-header.component';
import { CardComponent } from '../../shared/ui/card.component';
import { EmptyStateComponent } from '../../shared/ui/empty-state.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { IconTileComponent } from '../../shared/ui/icon-tile.component';
import {
  StatusPillComponent,
  humanStatus,
  toneForStatus,
} from '../../shared/ui/status-pill.component';

/** Accepts https:// and git@host:owner/repo forms. */
const REPO_PATTERN =
  /^(https?:\/\/[\w.-]+(?::\d+)?\/[\w.\-~/]+|git@[\w.-]+:[\w.\-~/]+)(\.git)?\/?$/i;

/**
 * The backend's `POST /documentation/jobs` accepts only a repository URL (or
 * an already-registered repository id) — no branch parameter. It always
 * generates from the repository's default branch. So this form does not
 * offer a branch field: an input the backend silently ignores would be a
 * lie, not a convenience.
 */
@Component({
  selector: 'co-analyze-repository',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    RouterLink,
    PageHeaderComponent,
    CardComponent,
    IconComponent,
    IconTileComponent,
    StatusPillComponent,
    EmptyStateComponent,
  ],
  template: `
    <div class="page stack-lg">
      <co-page-header
        title="Analyze repository"
        subtitle="Point CodeOops at a repository. It runs CodeWiki and returns the generated overview."
        [crumbs]="[{ label: 'Dashboard', link: '/dashboard' }, { label: 'Analyze repository' }]"
      />

      <div class="split">
        <!-- ---------------- form ---------------- -->
        <co-card title="Repository" subtitle="Git URL">
          <form class="form stack" [formGroup]="form" (ngSubmit)="submit()">
            <div class="field">
              <label class="field__label" for="repoUrl">Repository URL</label>
              <input
                id="repoUrl"
                class="input"
                type="text"
                formControlName="repositoryUrl"
                placeholder="https://github.com/owner/repository"
                autocomplete="off"
                spellcheck="false"
                [attr.aria-invalid]="showUrlError() ? 'true' : null"
                [attr.aria-describedby]="showUrlError() ? 'repoUrlError' : 'repoUrlHint'"
              />
              @if (showUrlError()) {
                <p class="field__error" id="repoUrlError">
                  Enter a Git URL, for example https://github.com/owner/repository
                </p>
              } @else {
                <p class="field__hint" id="repoUrlHint">
                  HTTPS. The repository must be reachable from the CodeOops backend. Generation
                  always uses the repository's default branch.
                </p>
              }
            </div>

            @if (submitError(); as message) {
              <div class="alert" role="alert">
                <co-icon name="alert" class="alert__icon" />
                <div>
                  <p class="alert__title">Submission failed</p>
                  <p class="alert__text">{{ message }}</p>
                </div>
              </div>
            }

            <div class="row">
              <button type="submit" class="btn btn--primary" [disabled]="submitting()">
                <co-icon [name]="submitting() ? 'clock' : 'play'" />
                <span>{{ submitting() ? 'Submitting…' : 'Generate documentation' }}</span>
              </button>
              <button
                type="button"
                class="btn btn--quiet"
                (click)="reset()"
                [disabled]="submitting()"
              >
                Clear
              </button>
            </div>
          </form>
        </co-card>

        <!-- ---------------- what happens ---------------- -->
        <co-card title="What happens next">
          <ol class="steps">
            @for (step of steps; track step.title; let i = $index) {
              <li class="steps__item">
                <span class="steps__index">{{ i + 1 }}</span>
                <div>
                  <p class="steps__title">{{ step.title }}</p>
                  <p class="steps__text">{{ step.text }}</p>
                </div>
              </li>
            }
          </ol>
          <p class="note">
            <co-icon name="shield" class="note__icon" />
            <span>
              The overview is produced by CodeWiki and bound to this job. CodeOops does not
              summarise, rewrite or substitute the engine's output.
            </span>
          </p>
        </co-card>
      </div>

      <!-- ---------------- recent submissions ---------------- -->
      <co-card title="Recently submitted" subtitle="From this backend" flush>
        <a card-actions class="btn btn--quiet btn--sm" routerLink="/jobs">
          <span>All jobs</span>
          <co-icon name="arrow-right" />
        </a>

        @if (recent().length) {
          <ul class="rows">
            @for (job of recent(); track job.id) {
              <li class="rows__item">
                <co-icon-tile name="git" tone="grey" size="sm" />
                <a class="rows__main" [routerLink]="['/jobs', job.id]">
                  <span class="rows__title truncate">{{ nameOf(job) }}</span>
                  <span class="rows__meta truncate">{{ ago(job) }}</span>
                </a>
                <co-status-pill [label]="statusText(job)" [tone]="statusTone(job)" />
              </li>
            }
          </ul>
        } @else {
          <co-empty-state
            title="Nothing submitted yet"
            message="Repositories you submit will be listed here."
            icon="folder"
            compact
          />
        }
      </co-card>
    </div>
  `,
  styles: `
    :host { display: block; }

    .split {
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
      gap: var(--s-6);
      align-items: start;
    }

    @media (max-width: 1080px) {
      .split { grid-template-columns: minmax(0, 1fr); }
    }

    .form { gap: var(--s-5); }

    .alert {
      display: flex;
      gap: var(--s-3);
      padding: var(--s-3) var(--s-4);
      background: var(--err-50);
      border: 1px solid #FECDCA;
      border-radius: var(--r-md);
    }

    .alert__icon { width: 1.15rem; height: 1.15rem; color: var(--err-600); flex: none; margin-top: 0.1rem; }
    .alert__title { font-weight: 650; color: var(--err-600); font-size: var(--t-sm); }
    .alert__text { font-size: var(--t-sm); color: var(--grey-700); }

    .steps { display: grid; gap: var(--s-4); }
    .steps__item { display: flex; gap: var(--s-3); align-items: flex-start; }

    .steps__index {
      flex: none;
      width: 1.5rem; height: 1.5rem;
      display: grid; place-items: center;
      border-radius: 50%;
      background: var(--red-50);
      color: var(--red-500);
      font-size: var(--t-xs);
      font-weight: 700;
    }

    .steps__title { font-size: var(--t-sm); font-weight: 650; }
    .steps__text { font-size: var(--t-sm); color: var(--text-secondary); }

    .note {
      display: flex;
      gap: var(--s-3);
      margin-top: var(--s-5);
      padding: var(--s-3) var(--s-4);
      background: var(--grey-50);
      border: 1px solid var(--border);
      border-radius: var(--r-md);
      font-size: var(--t-sm);
      color: var(--text-secondary);
    }

    .note__icon { width: 1.1rem; height: 1.1rem; color: var(--grey-500); flex: none; margin-top: 0.1rem; }

    .rows { display: grid; }

    .rows__item {
      display: flex;
      align-items: center;
      gap: var(--s-3);
      padding: var(--s-3) var(--s-5);
      border-top: 1px solid var(--border);
    }

    .rows__item:first-child { border-top: 0; }
    .rows__item:hover { background: var(--grey-50); }
    .rows__main { display: grid; gap: 0.05rem; flex: 1; min-width: 0; }
    .rows__title { font-weight: 600; font-size: var(--t-sm); }
    .rows__item:hover .rows__title { color: var(--red-500); }
    .rows__meta { font-size: var(--t-xs); color: var(--text-muted); }
  `,
})
export class AnalyzeRepositoryComponent {
  private readonly api = inject(CodeOopsApiService);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly form = this.fb.nonNullable.group({
    repositoryUrl: ['', [Validators.required, Validators.pattern(REPO_PATTERN)]],
  });

  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);
  protected readonly attempted = signal(false);
  protected readonly jobs = signal<DocumentationJob[]>([]);

  protected readonly steps = [
    {
      title: 'CodeOops creates a job',
      text: 'The URL is validated and a documentation job is queued.',
    },
    {
      title: 'CodeWiki analyses the repository',
      text: 'Files are parsed, dependencies resolved and modules clustered.',
    },
    {
      title: 'The overview is generated',
      text: 'Each module is summarised, then reduced into one overview document.',
    },
    {
      title: 'The artifact is bound to the job',
      text: 'CodeOops verifies the artifact came from this repository before showing it.',
    },
  ];

  protected readonly recent = computed(() => this.jobs().slice(0, 5));

  protected readonly showUrlError = computed(() => {
    void this.attempted();
    const control = this.form.controls.repositoryUrl;
    return control.invalid && (control.touched || this.attempted());
  });

  constructor() {
    this.api
      .listJobs()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (jobs) => this.jobs.set(jobs ?? []),
        error: () => this.jobs.set([]),
      });
  }

  protected submit(): void {
    this.attempted.set(true);
    this.submitError.set(null);

    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { repositoryUrl } = this.form.getRawValue();
    this.submitting.set(true);

    this.api
      .createJob({ repository_url: repositoryUrl.trim() })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (job) => {
          this.submitting.set(false);
          if (job?.id) {
            void this.router.navigate(['/jobs', job.id]);
          } else {
            void this.router.navigate(['/jobs']);
          }
        },
        error: (err: unknown) => {
          this.submitting.set(false);
          this.submitError.set(
            httpErrorMessage(err, 'The backend rejected the request without a message.'),
          );
        },
      });
  }

  protected reset(): void {
    this.form.reset({ repositoryUrl: '' });
    this.attempted.set(false);
    this.submitError.set(null);
  }

  protected nameOf(job: DocumentationJob): string {
    return repositoryLabel(job);
  }

  protected ago(job: DocumentationJob): string {
    return relativeTime(job.created_at ?? job.started_at);
  }

  protected statusText(job: DocumentationJob): string {
    return humanStatus(job.status);
  }

  protected statusTone(job: DocumentationJob) {
    return toneForStatus(job.status);
  }
}
