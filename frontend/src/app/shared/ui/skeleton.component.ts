import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/** Loading placeholder. A UI state, never stand-in application data. */
@Component({
  selector: 'co-skeleton',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span
      class="skeleton"
      [style.width]="width()"
      [style.height]="height()"
      [style.border-radius]="radius()"
      role="status"
      aria-label="Loading"
    ></span>
  `,
  styles: `
    :host { display: block; }

    .skeleton {
      display: block;
      background: linear-gradient(90deg, var(--grey-100), var(--grey-200), var(--grey-100));
      background-size: 200% 100%;
    }

    @media (prefers-reduced-motion: no-preference) {
      .skeleton { animation: shimmer 1.4s linear infinite; }
    }

    @keyframes shimmer { to { background-position: -200% 0; } }
  `,
})
export class SkeletonComponent {
  readonly width = input('100%');
  readonly height = input('1rem');
  readonly radius = input('var(--r-xs)');
}
