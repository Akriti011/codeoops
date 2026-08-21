import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AppShellComponent } from '../../shared/layout/app-shell.component';

@Component({
  selector: 'co-not-found',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, AppShellComponent],
  template: `
    <co-app-shell>
      <section class="page co-panel">
        <p class="code">404</p>
        <h1 class="co-h1">That page does not exist</h1>
        <p class="co-lede">
          The route you followed is not part of the CodeOops workspace.
        </p>
        <div class="actions">
          <a class="co-btn co-btn--primary" routerLink="/">Back to home</a>
          <a class="co-btn co-btn--ghost" routerLink="/repositories">
            View repositories
          </a>
        </div>
      </section>
    </co-app-shell>
  `,
  styles: `
    .page {
      display: grid;
      justify-items: start;
      gap: 0.7rem;
      padding: clamp(2rem, 5vw, 3.5rem);
      margin-top: 0.5rem;
    }

    .code {
      font-family: var(--co-mono);
      font-size: 3rem;
      font-weight: 700;
      letter-spacing: -0.05em;
      color: var(--co-red-500);
    }

    .actions {
      display: flex;
      gap: 0.6rem;
      margin-top: 0.8rem;
      flex-wrap: wrap;
    }
  `,
})
export class NotFoundComponent {}
