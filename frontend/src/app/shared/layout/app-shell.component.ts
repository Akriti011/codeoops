import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';

import { DocumentationJobService } from '../../core/services/documentation-job.service';
import { LogoComponent } from '../ui/logo.component';

interface NavItem {
  readonly label: string;
  readonly path: string;
  readonly icon: string;
  readonly exact: boolean;
}

/**
 * Workspace chrome: a black sidebar on desktop that collapses into a top bar
 * with a slide-in panel on mobile/tablet. Used by every screen except the
 * landing page.
 */
@Component({
  selector: 'co-app-shell',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, RouterLinkActive, LogoComponent],
  template: `
    <div class="shell">
      <header class="topbar">
        <a class="brand" routerLink="/" aria-label="CodeOops home" (click)="closeMenu()">
          <co-logo [compact]="true" />
        </a>
        <button
          type="button"
          class="menu-toggle"
          (click)="toggleMenu()"
          [attr.aria-expanded]="menuOpen()"
          aria-controls="primary-nav"
          aria-label="Toggle navigation menu"
        >
          @if (menuOpen()) {
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path d="M5 5l10 10M15 5 5 15" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
            </svg>
          } @else {
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path d="M3 6h14M3 10h14M3 14h14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
            </svg>
          }
        </button>
      </header>

      @if (menuOpen()) {
        <button
          type="button"
          class="backdrop"
          (click)="closeMenu()"
          aria-hidden="true"
          tabindex="-1"
        ></button>
      }

      <aside class="rail" [class.rail--open]="menuOpen()" id="primary-nav" aria-label="Primary">
        <a class="brand brand--desktop" routerLink="/" aria-label="CodeOops home">
          <co-logo [compact]="true" />
        </a>

        <nav class="nav">
          <ul>
            @for (item of navItems; track item.path) {
              <li>
                <a
                  class="nav__link"
                  [routerLink]="item.path"
                  routerLinkActive="is-active"
                  [routerLinkActiveOptions]="{ exact: item.exact }"
                  #rla="routerLinkActive"
                  [attr.aria-current]="rla.isActive ? 'page' : null"
                  (click)="closeMenu()"
                >
                  <svg class="nav__icon" viewBox="0 0 20 20" aria-hidden="true">
                    <path
                      [attr.d]="item.icon"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="1.5"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                  </svg>
                  <span>{{ item.label }}</span>
                </a>
              </li>
            }
          </ul>
        </nav>

        <div class="engine" role="status" [class.engine--live]="engineReachable()">
          <p class="engine__label">Documentation engine</p>
          <p class="engine__value">
            <span class="engine__dot" aria-hidden="true"></span>
            @switch (engineReachable()) {
              @case (true) {
                CodeWiki — connected
              }
              @case (false) {
                CodeWiki — not reachable
              }
              @default {
                CodeWiki — checking…
              }
            }
          </p>
          <p class="engine__hint">
            @if (engineReachable() === false) {
              The configured CodeWiki instance did not respond.
            } @else {
              Repository submission and job orchestration only — CodeWiki produces the documentation.
            }
          </p>
        </div>
      </aside>

      <main id="main-content" class="main" tabindex="-1">
        <ng-content />
      </main>
    </div>
  `,
  styles: `
    :host {
      display: block;
      min-height: 100dvh;
    }

    .shell {
      display: grid;
      grid-template-columns: 16rem minmax(0, 1fr);
      gap: clamp(1rem, 1.6vw, 1.75rem);
      padding: clamp(1rem, 1.6vw, 1.75rem);
      min-height: 100dvh;
      align-items: start;
    }

    .topbar {
      display: none;
    }

    .backdrop {
      display: none;
    }

    .rail {
      position: sticky;
      top: clamp(1rem, 1.6vw, 1.75rem);
      display: flex;
      flex-direction: column;
      gap: 1.5rem;
      padding: 1.3rem 1rem;
      border-radius: var(--co-radius-lg);
      max-height: calc(100dvh - 2 * clamp(1rem, 1.6vw, 1.75rem));
      background: var(--co-black);
      border: 1px solid var(--co-border-on-dark);
    }

    .brand {
      padding: 0.2rem 0.35rem;
      border-radius: var(--co-radius-sm);
      color: var(--co-text-on-dark);
    }

    .brand--desktop {
      display: inline-flex;
    }

    .nav {
      flex: 1;
      min-height: 0;
      overflow-y: auto;
    }

    .nav ul {
      display: grid;
      gap: 0.2rem;
    }

    .nav__link {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      padding: 0.6rem 0.75rem;
      border-radius: var(--co-radius-sm);
      color: var(--co-text-on-dark-muted);
      font-size: 0.9rem;
      font-weight: 550;
      border: 1px solid transparent;
      transition:
        color var(--co-fast) var(--co-ease),
        background var(--co-fast) var(--co-ease),
        border-color var(--co-fast) var(--co-ease);

      &:hover {
        color: var(--co-text-on-dark);
        background: rgba(255, 255, 255, 0.06);
      }

      &.is-active {
        color: var(--co-text-on-dark);
        background: var(--co-red-500);
        border-color: var(--co-red-500);
      }
    }

    .nav__icon {
      width: 18px;
      height: 18px;
      flex: none;
      opacity: 0.92;
    }

    .engine {
      padding: 0.8rem 0.85rem;
      border-radius: var(--co-radius-sm);
      border: 1px solid var(--co-border-on-dark);
      background: rgba(255, 255, 255, 0.03);
    }

    .engine__label {
      font-size: 0.66rem;
      letter-spacing: 0.13em;
      text-transform: uppercase;
      color: var(--co-text-on-dark-faint);
    }

    .engine__value {
      display: flex;
      align-items: center;
      gap: 0.45rem;
      margin-top: 0.35rem;
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--co-text-on-dark-muted);
    }

    .engine__dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--co-text-on-dark-faint);
      flex: none;
    }

    .engine--live .engine__dot {
      background: var(--co-success);
      box-shadow: 0 0 0 3px rgba(21, 128, 61, 0.25);
    }

    .engine__hint {
      margin-top: 0.4rem;
      font-size: 0.72rem;
      line-height: 1.45;
      color: var(--co-text-on-dark-faint);
    }

    .main {
      min-width: 0;
      outline: none;
    }

    @media (max-width: 1024px) {
      .shell {
        grid-template-columns: minmax(0, 1fr);
        padding: 0.85rem 0.85rem clamp(1rem, 1.6vw, 1.75rem);
        gap: 0.85rem;
      }

      .topbar {
        position: sticky;
        top: 0;
        z-index: 70;
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin: -0.85rem -0.85rem 0;
        padding: 0.75rem 0.9rem;
        background: var(--co-black);
      }

      .brand--desktop {
        display: none;
      }

      .menu-toggle {
        display: grid;
        place-items: center;
        width: 38px;
        height: 38px;
        border-radius: var(--co-radius-sm);
        border: 1px solid var(--co-border-on-dark);
        background: transparent;
        color: var(--co-text-on-dark);
        cursor: pointer;

        svg {
          width: 18px;
          height: 18px;
        }
      }

      .backdrop {
        display: block;
        position: fixed;
        inset: 0;
        z-index: 65;
        border: 0;
        padding: 0;
        background: rgba(5, 5, 5, 0.4);
        cursor: default;
      }

      .rail {
        position: fixed;
        top: 0;
        left: 0;
        bottom: 0;
        z-index: 68;
        width: min(19rem, 84vw);
        max-height: none;
        border-radius: 0;
        transform: translateX(-100%);
        transition: transform var(--co-base) var(--co-ease-out);
        padding-top: 4.5rem;
      }

      .rail--open {
        transform: translateX(0);
      }
    }
  `,
})
export class AppShellComponent {
  private readonly jobService = inject(DocumentationJobService);

  protected readonly menuOpen = signal(false);
  /** `null` until the one-shot probe on load resolves. */
  protected readonly engineReachable = signal<boolean | null>(null);

  protected readonly navItems: readonly NavItem[] = [
    {
      label: 'New Repository',
      path: '/',
      exact: true,
      icon: 'M10 4v12M4 10h12',
    },
    {
      label: 'Repositories',
      path: '/repositories',
      exact: false,
      icon: 'M3 6.5 10 3l7 3.5-7 3.5zM3 10l7 3.5L17 10M3 13.5 10 17l7-3.5',
    },
    {
      label: 'Documentation',
      path: '/documentation',
      exact: false,
      icon: 'M5 3h7l3 3v11H5zM12 3v3h3M7.5 10h5M7.5 13h3.5',
    },
    {
      label: 'Settings',
      path: '/settings',
      exact: false,
      icon: 'M10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM10 2.5v2M10 15.5v2M17.5 10h-2M4.5 10h-2M15.3 4.7l-1.4 1.4M6.1 13.9l-1.4 1.4M15.3 15.3l-1.4-1.4M6.1 6.1 4.7 4.7',
    },
  ];

  constructor() {
    this.jobService.probeEngine().subscribe({
      next: (status) => this.engineReachable.set(status.reachable),
      error: () => this.engineReachable.set(false),
    });
  }

  protected toggleMenu(): void {
    this.menuOpen.update((open) => !open);
  }

  protected closeMenu(): void {
    this.menuOpen.set(false);
  }
}
