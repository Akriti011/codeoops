import { ChangeDetectionStrategy, Component, booleanAttribute, input } from '@angular/core';

import { IconTileComponent, TileTone } from './icon-tile.component';
import { IconName } from './icon.component';

/**
 * The honest answer when there is nothing to show.
 *
 * Used wherever the backend returns no data. It is never a placeholder for
 * data that exists — it is the rendering of genuine absence.
 */
@Component({
  selector: 'co-empty-state',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconTileComponent],
  template: `
    <div class="empty" [attr.data-compact]="compact() ? '' : null">
      <co-icon-tile [name]="icon()" [tone]="tone()" size="xl" />
      <h3 class="empty__title">{{ title() }}</h3>
      @if (message()) {
        <p class="empty__message">{{ message() }}</p>
      }
      <div class="empty__actions">
        <ng-content />
      </div>
    </div>
  `,
  styles: `
    :host { display: block; }

    .empty {
      display: grid;
      justify-items: center;
      text-align: center;
      gap: var(--s-3);
      padding: var(--s-12) var(--s-6);
    }

    .empty[data-compact] { padding: var(--s-8) var(--s-4); }

    .empty__title {
      margin-top: var(--s-1);
      font-size: var(--t-md);
      font-weight: 650;
    }

    .empty__message {
      font-size: var(--t-base);
      color: var(--text-secondary);
      max-width: 40ch;
    }

    .empty__actions:not(:empty) { margin-top: var(--s-2); }
  `,
})
export class EmptyStateComponent {
  readonly title = input.required<string>();
  readonly message = input<string | null>(null);
  readonly icon = input<IconName>('folder');
  readonly tone = input<TileTone>('grey');
  readonly compact = input(false, { transform: booleanAttribute });
}
