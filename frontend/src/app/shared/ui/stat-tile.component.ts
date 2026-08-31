import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { IconTileComponent, TileTone } from './icon-tile.component';
import { IconName } from './icon.component';

/**
 * Dashboard metric tile: icon, label, value.
 *
 * `value` is nullable on purpose — while stats are loading, or when the
 * backend cannot supply a figure, the tile shows a dash rather than a zero.
 * A zero is a claim; a dash is not.
 */
@Component({
  selector: 'co-stat-tile',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconTileComponent],
  template: `
    <div class="tile">
      <co-icon-tile [name]="icon()" [tone]="tone()" size="lg" />
      <div class="tile__text">
        <p class="tile__label">{{ label() }}</p>
        @if (loading()) {
          <span class="tile__skeleton" aria-hidden="true"></span>
          <span class="sr-only">Loading</span>
        } @else {
          <p class="tile__value">{{ value() ?? '—' }}</p>
        }
      </div>
    </div>
  `,
  styles: `
    :host { display: block; }

    .tile {
      display: flex;
      align-items: center;
      gap: var(--s-4);
      padding: var(--s-5);
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-lg);
      box-shadow: var(--shadow-sm);
      height: 100%;
    }

    .tile__text { min-width: 0; }

    .tile__label {
      font-size: var(--t-sm);
      color: var(--text-secondary);
      font-weight: 500;
    }

    .tile__value {
      margin-top: 0.15rem;
      font-size: var(--t-3xl);
      font-weight: 700;
      letter-spacing: -0.03em;
      line-height: 1.1;
    }

    .tile__skeleton {
      display: block;
      margin-top: 0.45rem;
      width: 2.5rem;
      height: 1.5rem;
      border-radius: var(--r-xs);
      background: linear-gradient(90deg, var(--grey-100), var(--grey-200), var(--grey-100));
      background-size: 200% 100%;
      animation: shimmer 1.4s linear infinite;
    }

    @keyframes shimmer { to { background-position: -200% 0; } }
  `,
})
export class StatTileComponent {
  readonly label = input.required<string>();
  readonly icon = input.required<IconName>();
  readonly value = input<number | string | null>(null);
  readonly tone = input<TileTone>('red');
  readonly loading = input(false);
}
