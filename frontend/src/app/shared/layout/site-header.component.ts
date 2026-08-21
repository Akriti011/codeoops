import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

import { LogoComponent } from '../ui/logo.component';

/** Floating glass header used on the landing page. */
@Component({
  selector: 'co-site-header',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LogoComponent],
  template: `
    <header class="header">
      <div class="header__inner co-glass co-edge-lit">
        <a routerLink="/" class="brand" aria-label="CodeOops home">
          <co-logo />
        </a>

        <nav class="links" aria-label="Primary">
          <a routerLink="/repositories">Repositories</a>
          <a routerLink="/documentation">Workspace</a>
          <a routerLink="/settings">Settings</a>
        </nav>

        <a class="co-btn co-btn--primary cta" routerLink="/documentation">
          Open workspace
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
      </div>
    </header>
  `,
  styles: `
    .header {
      position: sticky;
      top: 0;
      z-index: 60;
      padding: 1rem var(--co-gutter) 0;
    }

    .header__inner {
      display: flex;
      align-items: center;
      gap: 1.5rem;
      max-width: var(--co-max-width);
      margin-inline: auto;
      padding: 0.7rem 0.75rem 0.7rem 1rem;
      border-radius: var(--co-radius-xl);
    }

    .brand {
      border-radius: var(--co-radius);
      padding: 0.15rem 0.25rem;
    }

    .links {
      display: flex;
      gap: 0.35rem;
      margin-left: auto;

      a {
        padding: 0.5rem 0.85rem;
        border-radius: var(--co-radius);
        font-size: 0.9rem;
        font-weight: 550;
        color: var(--co-text-secondary);
        transition:
          color var(--co-fast) var(--co-ease),
          background var(--co-fast) var(--co-ease);

        &:hover {
          color: var(--co-text);
          background: var(--co-bg-subtle);
        }
      }
    }

    .cta {
      padding-block: 0.6rem;
    }

    .arrow {
      width: 15px;
      height: 15px;
      transition: transform var(--co-base) var(--co-ease-out);
    }

    .cta:hover .arrow {
      transform: translateX(3px);
    }

    @media (max-width: 860px) {
      .links {
        display: none;
      }
      .cta {
        margin-left: auto;
      }
    }
  `,
})
export class SiteHeaderComponent {}
