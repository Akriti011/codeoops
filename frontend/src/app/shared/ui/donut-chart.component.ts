import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type DonutTone = 'success' | 'progress' | 'danger' | 'idle' | 'info';

export interface DonutSegment {
  label: string;
  value: number;
  tone: DonutTone;
}

const TONE_COLOR: Record<DonutTone, string> = {
  success: 'var(--ok-500)',
  progress: 'var(--info-500)',
  info: 'var(--warn-500)',
  danger: 'var(--err-500)',
  idle: 'var(--idle-500)',
};

const RADIUS = 42;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

interface Arc {
  label: string;
  value: number;
  color: string;
  dash: string;
  offset: number;
  percent: number;
}

/**
 * Ring chart drawn with plain SVG — no charting dependency.
 *
 * Renders nothing but an honest empty state when every segment is zero. It
 * will not draw a full grey ring and let it read as data.
 */
@Component({
  selector: 'co-donut-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="donut">
      <div class="donut__chart">
        <svg viewBox="0 0 100 100" role="img" [attr.aria-label]="ariaLabel()">
          <circle class="donut__track" cx="50" cy="50" [attr.r]="radius" />
          @for (arc of arcs(); track arc.label) {
            <circle
              class="donut__arc"
              cx="50"
              cy="50"
              [attr.r]="radius"
              [attr.stroke]="arc.color"
              [attr.stroke-dasharray]="arc.dash"
              [attr.stroke-dashoffset]="arc.offset"
            />
          }
        </svg>
        <div class="donut__center">
          <span class="donut__total">{{ hasData() ? total() : '—' }}</span>
          <span class="donut__caption">{{ centerLabel() }}</span>
        </div>
      </div>

      <ul class="legend">
        @for (arc of arcs(); track arc.label) {
          <li class="legend__row">
            <span class="legend__swatch" [style.background]="arc.color" aria-hidden="true"></span>
            <span class="legend__label">{{ arc.label }}</span>
            <span class="legend__value">{{ arc.value }}</span>
          </li>
        } @empty {
          <li class="legend__none">No job activity yet.</li>
        }
      </ul>
    </div>
  `,
  styles: `
    :host { display: block; }

    .donut {
      display: flex;
      align-items: center;
      gap: var(--s-6);
      flex-wrap: wrap;
    }

    .donut__chart { position: relative; width: 9.5rem; height: 9.5rem; flex: none; }

    svg { width: 100%; height: 100%; transform: rotate(-90deg); }

    .donut__track {
      fill: none;
      stroke: var(--grey-100);
      stroke-width: 12;
    }

    .donut__arc {
      fill: none;
      stroke-width: 12;
      stroke-linecap: butt;
      transition: stroke-dasharray var(--base) var(--ease);
    }

    .donut__center {
      position: absolute;
      inset: 0;
      display: grid;
      place-content: center;
      justify-items: center;
      text-align: center;
    }

    .donut__total {
      font-size: var(--t-2xl);
      font-weight: 700;
      letter-spacing: -0.03em;
      line-height: 1.1;
    }

    .donut__caption {
      font-size: var(--t-xs);
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-weight: 600;
    }

    .legend { display: grid; gap: var(--s-3); flex: 1; min-width: 10rem; }

    .legend__row { display: flex; align-items: center; gap: var(--s-3); }

    .legend__swatch {
      width: 0.625rem; height: 0.625rem; border-radius: 3px; flex: none;
    }

    .legend__label { flex: 1; font-size: var(--t-sm); color: var(--text-secondary); }
    .legend__value { font-size: var(--t-sm); font-weight: 650; }
    .legend__none { font-size: var(--t-sm); color: var(--text-muted); }
  `,
})
export class DonutChartComponent {
  readonly segments = input<readonly DonutSegment[]>([]);
  readonly centerLabel = input('Total');

  protected readonly radius = RADIUS;

  protected readonly total = computed(() =>
    this.segments().reduce((sum, s) => sum + Math.max(0, s.value), 0),
  );

  protected readonly hasData = computed(() => this.total() > 0);

  protected readonly arcs = computed<Arc[]>(() => {
    const total = this.total();
    if (total <= 0) return [];

    let consumed = 0;
    return this.segments()
      .filter((s) => s.value > 0)
      .map((s) => {
        const fraction = s.value / total;
        const length = fraction * CIRCUMFERENCE;
        const arc: Arc = {
          label: s.label,
          value: s.value,
          color: TONE_COLOR[s.tone] ?? TONE_COLOR.idle,
          dash: `${length} ${CIRCUMFERENCE - length}`,
          offset: -consumed,
          percent: Math.round(fraction * 100),
        };
        consumed += length;
        return arc;
      });
  });

  protected readonly ariaLabel = computed(() => {
    const arcs = this.arcs();
    if (!arcs.length) return 'No job activity yet';
    return arcs.map((a) => `${a.label}: ${a.value}`).join(', ');
  });
}
