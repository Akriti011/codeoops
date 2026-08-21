import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { Subject, debounceTime, distinctUntilChanged } from 'rxjs';

import { ApiError, isApiError } from '../../core/models/api-error.model';
import { Repository, repositoryFullName } from '../../core/models/repository.model';
import { RelativeTimePipe } from '../../core/pipes/relative-time.pipe';
import { RepositoryService } from '../../core/services/repository.service';
import { AppShellComponent } from '../../shared/layout/app-shell.component';
import { StatusPillComponent } from '../../shared/ui/status-pill.component';
import { RepositorySubmitFormComponent } from './repository-submit-form.component';

type LoadState = 'IDLE' | 'SUBMITTING' | 'READY' | 'FAILED';

@Component({
  selector: 'co-repository-list',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    RelativeTimePipe,
    AppShellComponent,
    StatusPillComponent,
    RepositorySubmitFormComponent,
  ],
  template: `
    <co-app-shell>
      <section class="page">
        <header class="page__head">
          <div>
            <p class="co-eyebrow">Repositories</p>
            <h1 class="co-h1">Tracked repositories</h1>
            <p class="co-lede head__lede">
              Every repository submitted to CodeOops, with the state reported
              by the backend.
            </p>
          </div>
          <button
            type="button"
            class="co-btn co-btn--ghost"
            (click)="reload()"
            [disabled]="state() === 'SUBMITTING'"
          >
            Refresh
          </button>
        </header>

        <div class="toolbar">
          <div class="co-field search">
            <label class="sr-only" for="repo-search">Search repositories</label>
            <svg class="search__icon" viewBox="0 0 20 20" aria-hidden="true">
              <circle cx="9" cy="9" r="6" fill="none" stroke="currentColor" stroke-width="1.5" />
              <path d="m17 17-4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
            </svg>
            <input
              id="repo-search"
              class="co-input search__input"
              type="search"
              placeholder="Search repositories…"
              [disabled]="repositories().length === 0"
              (input)="onSearchInput($any($event.target).value)"
            />
          </div>

          <button
            type="button"
            class="co-btn co-btn--primary"
            (click)="toggleAddForm()"
            [attr.aria-expanded]="showAddForm()"
            aria-controls="add-repository-panel"
          >
            <svg viewBox="0 0 16 16" aria-hidden="true" class="plus">
              <path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
            </svg>
            New Repository
          </button>
        </div>

        @if (showAddForm()) {
          <div class="co-panel add" id="add-repository-panel">
            <h2 class="co-h3">Add a repository</h2>
            <co-repository-submit-form
              [navigateOnSuccess]="false"
              (submitted)="onSubmitted()"
            />
          </div>
        }

        @switch (state()) {
          @case ('SUBMITTING') {
            <div class="co-panel table-wrap" aria-hidden="true">
              <div class="skeleton-rows">
                @for (placeholder of [1, 2, 3, 4]; track placeholder) {
                  <div class="skeleton-row"></div>
                }
              </div>
            </div>
            <p class="sr-only" role="status">Loading repositories…</p>
          }

          @case ('FAILED') {
            <div class="co-panel error" role="alert">
              <h2 class="co-h3">Could not load repositories</h2>
              <p class="error__message">{{ error()?.message }}</p>
              @if (error()?.offline) {
                <p class="co-help">
                  Start the API with
                  <code class="co-code">uvicorn app.main:app --reload --port 8000</code>
                  and try again.
                </p>
              }
              <button type="button" class="co-btn co-btn--ghost" (click)="reload()">
                Try again
              </button>
            </div>
          }

          @default {
            @if (repositories().length === 0) {
              <div class="co-panel empty">
                <h2 class="co-h3">No repositories yet</h2>
                <p class="co-help">
                  Submit a GitHub repository to start tracking it.
                </p>
              </div>
            } @else if (filteredRepositories().length === 0) {
              <div class="co-panel empty">
                <h2 class="co-h3">No matches</h2>
                <p class="co-help">No repository matches your search.</p>
              </div>
            } @else {
              <div class="co-panel table-wrap">
                <table class="table">
                  <caption class="sr-only">Tracked repositories</caption>
                  <thead>
                    <tr>
                      <th scope="col">Repository</th>
                      <th scope="col">Status</th>
                      <th scope="col">Updated</th>
                      <th scope="col"><span class="sr-only">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (repository of filteredRepositories(); track repository.id) {
                      <tr>
                        <td class="cell-repo">
                          <a class="repo-link" [routerLink]="['/documentation', repository.id]">
                            <span class="repo-name">{{ repositoryFullName(repository) }}</span>
                            <span class="repo-url co-mono">{{ repository.repository_url }}</span>
                          </a>
                        </td>
                        <td>
                          <co-status-pill [state]="repository.status" />
                        </td>
                        <td class="cell-updated">
                          {{ repository.updated_at | relativeTime }}
                        </td>
                        <td class="cell-actions">
                          <a
                            class="co-btn co-btn--quiet open"
                            [routerLink]="['/documentation', repository.id]"
                          >
                            Open
                            <svg viewBox="0 0 16 16" aria-hidden="true" class="arrow">
                              <path
                                d="M3 8h9M8.5 4.5 12 8l-3.5 3.5"
                                fill="none"
                                stroke="currentColor"
                                stroke-width="1.5"
                                stroke-linecap="round"
                                stroke-linejoin="round"
                              />
                            </svg>
                          </a>
                        </td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
            }
          }
        }
      </section>
    </co-app-shell>
  `,
  styles: `
    .page {
      display: grid;
      gap: 1.1rem;
      padding-block: 0.5rem 2rem;
    }

    .page__head {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 1.5rem;
      flex-wrap: wrap;
    }

    .head__lede {
      margin-top: 0.5rem;
      max-width: 52ch;
    }

    .toolbar {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      flex-wrap: wrap;
    }

    .search {
      flex: 1 1 18rem;
      min-width: 0;
      position: relative;
    }

    .search__icon {
      position: absolute;
      left: 0.85rem;
      top: 50%;
      translate: 0 -50%;
      width: 16px;
      height: 16px;
      color: var(--co-text-tertiary);
      pointer-events: none;
    }

    .search__input {
      padding-left: 2.4rem;
      font-family: var(--co-font);
    }

    .plus {
      width: 14px;
      height: 14px;
    }

    .add {
      padding: clamp(1.1rem, 2vw, 1.6rem);
      display: grid;
      gap: 1rem;
    }

    .table-wrap {
      overflow-x: auto;
      padding: 0;
    }

    .table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
      min-width: 40rem;

      th {
        text-align: left;
        padding: 0.85rem 1.25rem;
        font-size: 0.7rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--co-text-tertiary);
        border-bottom: 1px solid var(--co-border);
        font-weight: 650;
      }

      td {
        padding: 0.95rem 1.25rem;
        border-bottom: 1px solid var(--co-border);
        vertical-align: middle;
      }

      tbody tr {
        transition: background var(--co-fast) var(--co-ease);

        &:hover {
          background: var(--co-bg-subtle);
        }

        &:last-child td {
          border-bottom: none;
        }
      }
    }

    .cell-repo {
      min-width: 16rem;
    }

    .repo-link {
      display: grid;
      gap: 0.2rem;
    }

    .repo-name {
      font-weight: 620;
      font-size: 0.95rem;
      color: var(--co-text);
      overflow-wrap: anywhere;
    }

    .repo-url {
      font-size: 0.78rem;
      color: var(--co-text-tertiary);
      overflow-wrap: anywhere;
    }

    .cell-updated {
      color: var(--co-text-secondary);
      white-space: nowrap;
    }

    .cell-actions {
      text-align: right;
      white-space: nowrap;
    }

    .open {
      padding: 0.4rem 0.6rem;
    }

    .arrow {
      width: 13px;
      height: 13px;
      transition: transform var(--co-micro) var(--co-ease-out);
    }

    .open:hover .arrow {
      transform: translateX(2px);
    }

    .skeleton-rows {
      display: grid;
      gap: 1px;
      background: var(--co-border);
    }

    .skeleton-row {
      height: 3.4rem;
      background: var(--co-white);
      position: relative;
      overflow: hidden;

      &::after {
        content: '';
        position: absolute;
        inset: 0;
        background: linear-gradient(
          90deg,
          transparent,
          var(--co-bg-subtle),
          transparent
        );
      }
    }

    @media (prefers-reduced-motion: no-preference) {
      .skeleton-row::after {
        animation: shimmer 1.3s ease-in-out infinite;
      }
    }

    @keyframes shimmer {
      0% {
        transform: translateX(-100%);
      }
      100% {
        transform: translateX(100%);
      }
    }

    .empty,
    .error {
      padding: clamp(1.5rem, 3vw, 2.25rem);
      display: grid;
      gap: 0.6rem;
      justify-items: start;
    }

    .error {
      border-color: var(--co-danger-border);
    }

    .error__message {
      color: var(--co-text-secondary);
      font-size: 0.92rem;
    }

    @media (max-width: 640px) {
      .cell-updated {
        display: none;
      }
    }
  `,
})
export class RepositoryListComponent {
  private readonly service = inject(RepositoryService);
  private readonly searchInput$ = new Subject<string>();

  protected readonly repositoryFullName = repositoryFullName;

  protected readonly repositories = signal<readonly Repository[]>([]);
  protected readonly state = signal<LoadState>('IDLE');
  protected readonly error = signal<ApiError | null>(null);
  protected readonly showAddForm = signal(false);

  private readonly searchQuery = toSignal(
    this.searchInput$.pipe(debounceTime(200), distinctUntilChanged()),
    { initialValue: '' },
  );

  protected readonly filteredRepositories = computed(() => {
    const query = this.searchQuery().trim().toLowerCase();
    const all = this.repositories();
    if (!query) {
      return all;
    }
    return all.filter(
      (repository) =>
        repositoryFullName(repository).toLowerCase().includes(query) ||
        repository.repository_url.toLowerCase().includes(query),
    );
  });

  constructor() {
    this.reload();
  }

  protected onSearchInput(value: string): void {
    this.searchInput$.next(value);
  }

  protected toggleAddForm(): void {
    this.showAddForm.update((open) => !open);
  }

  protected onSubmitted(): void {
    this.showAddForm.set(false);
    this.reload();
  }

  protected reload(): void {
    this.state.set('SUBMITTING');
    this.error.set(null);

    this.service.listRepositories().subscribe({
      next: (page) => {
        this.repositories.set(page.items);
        this.state.set('READY');
      },
      error: (error: unknown) => {
        this.error.set(
          isApiError(error)
            ? error
            : {
                status: 0,
                code: 'UNEXPECTED_ERROR',
                message: 'Unexpected error while loading repositories.',
                details: {},
                offline: false,
              },
        );
        this.state.set('FAILED');
      },
    });
  }
}
