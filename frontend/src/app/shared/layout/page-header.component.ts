import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';

import { IconComponent } from '../ui/icon.component';

export interface Crumb {
  label: string;
  link?: string | null;
}

/** Title block that sits at the top of every screen inside the shell. */
@Component({
  selector: 'co-page-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, IconComponent],
  template: `
    <header class="head">
      @if (crumbs().length) {
        <nav class="crumbs" aria-label="Breadcrumb">
          @for (crumb of crumbs(); track crumb.label; let last = $last) {
            @if (crumb.link && !last) {
              <a class="crumbs__link" [routerLink]="crumb.link">{{ crumb.label }}</a>
            } @else {
              <span class="crumbs__current" [attr.aria-current]="last ? 'page' : null">
                {{ crumb.label }}
              </span>
            }
            @if (!last) {
              <co-icon class="crumbs__sep" name="chevron-right" />
            }
          }
        </nav>
      }

      <div class="head__row">
        <div class="head__titles">
          <h1 class="t-h1">{{ title() }}</h1>
          @if (subtitle()) {
            <p class="head__subtitle">{{ subtitle() }}</p>
          }
        </div>
        <div class="head__actions">
          <ng-content select="[page-actions]" />
        </div>
      </div>
    </header>
  `,
  styles: `
    :host { display: block; }

    .head { display: grid; gap: var(--s-3); }

    .crumbs {
      display: flex;
      align-items: center;
      gap: var(--s-2);
      font-size: var(--t-sm);
      color: var(--text-muted);
      flex-wrap: wrap;
    }

    .crumbs__link { color: var(--text-secondary); }
    .crumbs__link:hover { color: var(--red-500); }
    .crumbs__current { color: var(--text-secondary); font-weight: 600; }
    .crumbs__sep { width: 0.9rem; height: 0.9rem; color: var(--grey-300); }

    .head__row {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: var(--s-6);
      flex-wrap: wrap;
    }

    .head__subtitle {
      margin-top: var(--s-2);
      font-size: var(--t-md);
      color: var(--text-secondary);
      max-width: 62ch;
    }

    .head__actions { display: flex; align-items: center; gap: var(--s-3); flex-wrap: wrap; }
  `,
})
export class PageHeaderComponent {
  readonly title = input.required<string>();
  readonly subtitle = input<string | null>(null);
  readonly crumbs = input<readonly Crumb[]>([]);
}
