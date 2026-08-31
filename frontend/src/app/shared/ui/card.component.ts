import { ChangeDetectionStrategy, Component, booleanAttribute, input } from '@angular/core';

/**
 * The surface every panel in the product sits on: white, hairline border,
 * soft shadow. Optional header row with a title and projected actions.
 */
@Component({
  selector: 'co-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="card" [class.card--flush]="flush()">
      @if (title()) {
        <header class="card__head">
          <div class="card__titles">
            <h2 class="card__title">{{ title() }}</h2>
            @if (subtitle()) {
              <p class="card__subtitle">{{ subtitle() }}</p>
            }
          </div>
          <div class="card__actions">
            <ng-content select="[card-actions]" />
          </div>
        </header>
      }
      <div class="card__body">
        <ng-content />
      </div>
    </section>
  `,
  styles: `
    :host { display: block; }

    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-lg);
      box-shadow: var(--shadow-sm);
      overflow: hidden;
      height: 100%;
      display: flex;
      flex-direction: column;
    }

    .card__head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--s-4);
      padding: var(--s-5) var(--s-5) var(--s-3);
    }

    .card__title {
      font-size: var(--t-md);
      font-weight: 650;
      letter-spacing: -0.01em;
    }

    .card__subtitle {
      margin-top: 0.15rem;
      font-size: var(--t-sm);
      color: var(--text-secondary);
    }

    .card__actions { flex: none; }

    .card__body { padding: 0 var(--s-5) var(--s-5); flex: 1; min-height: 0; }
    .card--flush .card__body { padding: 0; }
    .card:not(:has(.card__head)) .card__body { padding-top: var(--s-5); }
  `,
})
export class CardComponent {
  readonly title = input<string | null>(null);
  readonly subtitle = input<string | null>(null);
  /** Remove body padding — for tables and full-bleed lists. */
  readonly flush = input(false, { transform: booleanAttribute });
}
