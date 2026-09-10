import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { BinItem, CodeOopsApiService } from '../../shared/data/codeoops-api.service';
import { httpErrorMessage, relativeTime } from '../../shared/data/format';
import { PageHeaderComponent } from '../../shared/layout/page-header.component';
import { CardComponent } from '../../shared/ui/card.component';
import { EmptyStateComponent } from '../../shared/ui/empty-state.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { IconTileComponent } from '../../shared/ui/icon-tile.component';
import { SkeletonComponent } from '../../shared/ui/skeleton.component';

@Component({
  selector: 'co-bin',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PageHeaderComponent,
    CardComponent,
    EmptyStateComponent,
    IconComponent,
    IconTileComponent,
    SkeletonComponent,
  ],
  template: `
    <div class="page stack-lg">
      <co-page-header
        title="Bin"
        subtitle="Deleted repositories. Restore brings back the documentation and everything generated for it."
        [crumbs]="[{ label: 'Dashboard', link: '/dashboard' }, { label: 'Bin' }]"
      >
        <div page-actions class="row">
          <button
            type="button"
            class="btn btn--ghost btn--sm"
            (click)="reload()"
            [disabled]="loading()"
          >
            <co-icon name="refresh" />
            <span>Refresh</span>
          </button>
        </div>
      </co-page-header>

      <co-card flush>
        @if (error(); as message) {
          <p class="state state--error" role="alert">{{ message }}</p>
        } @else if (loading()) {
          <ul class="rows">
            @for (row of [1, 2, 3]; track row) {
              <li class="rows__item">
                <co-skeleton width="2.5rem" height="2.5rem" radius="var(--r-md)" />
                <div class="grow stack-sm">
                  <co-skeleton width="35%" height="0.9rem" />
                  <co-skeleton width="22%" height="0.75rem" />
                </div>
              </li>
            }
          </ul>
        } @else if (items().length) {
          <ul class="rows">
            @for (item of items(); track item.repository_id) {
              <li class="rows__item">
                <co-icon-tile name="trash" tone="grey" size="md" />

                <div class="rows__main">
                  <span class="rows__title truncate">{{ item.label }}</span>
                  <span class="rows__meta truncate">{{ item.repository_url }}</span>
                </div>

                <span class="rows__col">
                  <span class="t-label">Deleted</span>
                  <span>{{ when(item) }}</span>
                </span>

                <span class="rows__col">
                  <span class="t-label">Documentation</span>
                  <span>{{ item.has_overview ? 'Available' : '—' }}</span>
                </span>

                <div class="rows__actions">
                  <button
                    type="button"
                    class="btn btn--ghost btn--sm"
                    [disabled]="busyId() === item.repository_id"
                    (click)="restore(item)"
                  >
                    <co-icon [name]="busyId() === item.repository_id ? 'clock' : 'refresh'" />
                    <span>Restore</span>
                  </button>
                  <button
                    type="button"
                    class="btn btn--ghost btn--sm btn--danger"
                    [disabled]="busyId() === item.repository_id"
                    (click)="purge(item)"
                  >
                    <co-icon name="trash" />
                    <span>Delete forever</span>
                  </button>
                </div>
              </li>
            }
          </ul>
        } @else {
          <co-empty-state
            title="Bin is empty"
            message="Repositories you delete from Documentation land here and can be restored."
            icon="trash"
            tone="grey"
            compact
          />
        }
      </co-card>
    </div>
  `,
  styles: `
    :host { display: block; }

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
    .rows__meta { font-size: var(--t-sm); color: var(--text-muted); }

    .rows__col {
      display: grid; gap: 0.1rem; flex: 0 0 8rem; min-width: 0;
      font-size: var(--t-sm);
    }

    .rows__actions { display: flex; gap: var(--s-2); flex: none; }

    .state { padding: var(--s-8) var(--s-5); text-align: center; }
    .state--error { color: var(--err-600); }

    @media (max-width: 980px) {
      .rows__col { display: none; }
      .rows__item { flex-wrap: wrap; }
    }
  `,
})
export class BinComponent {
  private readonly api = inject(CodeOopsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly items = signal<BinItem[]>([]);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  /** repository_id of the row currently restoring / purging. */
  protected readonly busyId = signal<string | null>(null);

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.api
      .listBin()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (items) => {
          this.items.set(items ?? []);
          this.error.set(null);
          this.loading.set(false);
        },
        error: (err: unknown) => {
          this.items.set([]);
          this.error.set(httpErrorMessage(err, 'The request for the bin did not complete.'));
          this.loading.set(false);
        },
      });
  }

  protected when(item: BinItem): string {
    return relativeTime(item.binned_at);
  }

  protected restore(item: BinItem): void {
    if (this.busyId()) return;
    this.busyId.set(item.repository_id);
    this.api
      .restoreRepository(item.repository_id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.dropRow(item.repository_id),
        error: (err: unknown) => {
          this.busyId.set(null);
          this.error.set(httpErrorMessage(err, `Could not restore "${item.label}".`));
        },
      });
  }

  protected purge(item: BinItem): void {
    if (this.busyId()) return;
    const extra = item.job_count > 1 ? ` and all ${item.job_count} runs` : '';
    if (
      !confirm(
        `Permanently delete "${item.label}"${extra}? This erases the generated ` +
          `documentation and cannot be undone.`,
      )
    ) {
      return;
    }
    this.busyId.set(item.repository_id);
    this.api
      .purgeRepository(item.repository_id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.dropRow(item.repository_id),
        error: (err: unknown) => {
          this.busyId.set(null);
          this.error.set(httpErrorMessage(err, `Could not delete "${item.label}".`));
        },
      });
  }

  private dropRow(repositoryId: string): void {
    this.items.update((list) => list.filter((i) => i.repository_id !== repositoryId));
    this.busyId.set(null);
  }
}
