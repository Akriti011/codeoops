import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

/**
 * Progress bar backed by a real fraction.
 *
 * Takes `completed` and `total` rather than a percentage, so a caller cannot
 * hand it a number that isn't derived from countable work. When `total` is
 * unknown the bar renders indeterminate instead of guessing.
 */
@Component({
  selector: 'co-progress-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="wrap">
      @if (showLabel()) {
        <div class="wrap__head">
          <span class="wrap__label">{{ label() }}</span>
          <span class="wrap__value">
            {{ indeterminate() ? indeterminateLabel() : percent() + '%' }}
          </span>
        </div>
      }
      <div
        class="track"
        role="progressbar"
        [attr.aria-valuenow]="indeterminate() ? null : percent()"
        [attr.aria-valuemin]="indeterminate() ? null : 0"
        [attr.aria-valuemax]="indeterminate() ? null : 100"
        [attr.aria-label]="label()"
      >
        <span
          class="fill"
          [class.fill--indeterminate]="indeterminate()"
          [style.width.%]="indeterminate() ? null : percent()"
        ></span>
      </div>
    </div>
  `,
  styles: `
    :host { display: block; }

    .wrap__head {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: var(--s-4);
      margin-bottom: var(--s-2);
    }

    .wrap__label { font-size: var(--t-sm); color: var(--text-secondary); }
    .wrap__value { font-size: var(--t-lg); font-weight: 700; letter-spacing: -0.02em; }

    .track {
      height: 0.5rem;
      border-radius: var(--r-pill);
      background: var(--grey-100);
      overflow: hidden;
    }

    .fill {
      display: block;
      height: 100%;
      border-radius: var(--r-pill);
      background: linear-gradient(90deg, var(--red-500), var(--red-400));
      transition: width var(--base) var(--ease);
    }

    .fill--indeterminate { width: 35%; }

    @media (prefers-reduced-motion: no-preference) {
      .fill--indeterminate { animation: slide 1.6s var(--ease) infinite; }
    }

    @keyframes slide {
      0%   { transform: translateX(-100%); }
      100% { transform: translateX(300%); }
    }
  `,
})
export class ProgressBarComponent {
  readonly completed = input<number | null>(null);
  readonly total = input<number | null>(null);
  readonly label = input('Overall progress');
  readonly showLabel = input(true);
  /** Shown in place of a percentage while `total` is unknown. */
  readonly indeterminateLabel = input('In progress');

  protected readonly indeterminate = computed(() => {
    const total = this.total();
    return total === null || total <= 0 || this.completed() === null;
  });

  protected readonly percent = computed(() => {
    const total = this.total() ?? 0;
    const done = this.completed() ?? 0;
    if (total <= 0) return 0;
    return Math.min(100, Math.round((done / total) * 100));
  });
}
