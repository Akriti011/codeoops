import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { IconComponent, IconName } from '../ui/icon.component';
import { LogoComponent } from '../ui/logo.component';

interface NavItem {
  label: string;
  icon: IconName;
  link: string;
}

/**
 * Application chrome: near-black rail on the left, white topbar, content well.
 *
 * Only routes that exist appear in the rail. There are no decorative nav items
 * pointing at screens that were never built.
 */
@Component({
  selector: 'co-app-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, IconComponent, LogoComponent],
  template: `
    <a class="skip-link" href="#co-main">Skip to content</a>

    <div class="shell" [class.shell--collapsed]="collapsed()" [class.shell--open]="drawerOpen()">
      <!-- ================= sidebar ================= -->
      <aside class="rail" [attr.data-open]="drawerOpen() ? '' : null">
        <div class="rail__brand">
          <a routerLink="/dashboard" class="rail__brand-link" aria-label="CodeOops home">
            <co-logo variant="dark" size="sm" [showWordmark]="!collapsed()" />
          </a>
          <button
            type="button"
            class="rail__close"
            (click)="closeDrawer()"
            aria-label="Close navigation"
          >
            <co-icon name="x" />
          </button>
        </div>

        <nav class="rail__nav" aria-label="Main">
          <p class="rail__section" [class.sr-only]="collapsed()">Platform</p>
          <ul>
            @for (item of nav; track item.link) {
              <li>
                <a
                  class="rail__item"
                  [routerLink]="item.link"
                  routerLinkActive="rail__item--active"
                  [attr.title]="collapsed() ? item.label : null"
                  (click)="closeDrawer()"
                >
                  <co-icon class="rail__icon" [name]="item.icon" />
                  <span class="rail__label">{{ item.label }}</span>
                </a>
              </li>
            }
          </ul>
        </nav>

        <div class="rail__foot">
          <div class="rail__engine">
            <co-icon class="rail__icon" name="cpu" />
            <span class="rail__label">
              <span class="rail__engine-title">CodeWiki engine</span>
              <span class="rail__engine-sub">Local model runtime</span>
            </span>
          </div>
          <button
            type="button"
            class="rail__collapse"
            (click)="toggleCollapsed()"
            [attr.aria-label]="collapsed() ? 'Expand sidebar' : 'Collapse sidebar'"
          >
            <co-icon class="rail__icon" [name]="collapsed() ? 'chevron-right' : 'menu'" />
            <span class="rail__label">Collapse</span>
          </button>
        </div>
      </aside>

      <button
        type="button"
        class="scrim"
        (click)="closeDrawer()"
        tabindex="-1"
        aria-hidden="true"
      ></button>

      <!-- ================= main column ================= -->
      <div class="col">
        <header class="topbar">
          <button
            type="button"
            class="topbar__menu"
            (click)="openDrawer()"
            aria-label="Open navigation"
          >
            <co-icon name="menu" />
          </button>

          <div class="topbar__spacer"></div>

          <a class="btn btn--primary btn--sm topbar__cta" routerLink="/analyze">
            <co-icon name="plus" />
            <span>Analyze repository</span>
          </a>
        </header>

        <main id="co-main" class="content" tabindex="-1">
          <div class="content__inner">
            <router-outlet />
          </div>
        </main>
      </div>
    </div>
  `,
  styles: `
    :host { display: block; min-height: 100dvh; }

    .shell {
      --rail-w: var(--sidebar-w);
      display: grid;
      grid-template-columns: var(--rail-w) minmax(0, 1fr);
      min-height: 100dvh;
    }

    .shell--collapsed { --rail-w: var(--sidebar-w-collapsed); }

    /* ---------------- sidebar ---------------- */

    .rail {
      grid-column: 1;
      position: sticky;
      top: 0;
      align-self: start;
      height: 100dvh;
      display: flex;
      flex-direction: column;
      background: var(--sidebar-bg);
      border-right: 1px solid var(--sidebar-border);
      padding: var(--s-4) var(--s-3);
      gap: var(--s-4);
      z-index: 40;
      overflow: hidden;
    }

    .rail__brand {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--s-2);
      padding: var(--s-2) var(--s-2) var(--s-4);
      border-bottom: 1px solid var(--sidebar-border);
    }

    .rail__brand-link { display: inline-flex; min-width: 0; }

    .rail__close {
      display: none;
      background: none;
      border: 0;
      color: var(--sidebar-text);
      cursor: pointer;
      width: 2rem; height: 2rem;
      border-radius: var(--r-sm);
      align-items: center; justify-content: center;
      co-icon { width: 1.1rem; height: 1.1rem; }
      &:hover { background: var(--sidebar-hover); color: #fff; }
    }

    .rail__nav { flex: 1; overflow-y: auto; }
    .rail__nav ul { display: grid; gap: 2px; }

    .rail__section {
      font-size: var(--t-xs);
      letter-spacing: 0.09em;
      text-transform: uppercase;
      font-weight: 700;
      color: #5C6478;
      padding: 0 var(--s-3);
      margin-bottom: var(--s-2);
    }

    .rail__item,
    .rail__collapse,
    .rail__engine {
      display: flex;
      align-items: center;
      gap: var(--s-3);
      padding: 0.625rem var(--s-3);
      border-radius: var(--r-md);
      color: var(--sidebar-text);
      font-size: var(--t-base);
      font-weight: 550;
      width: 100%;
      text-align: left;
      background: none;
      border: 0;
      cursor: pointer;
      transition: background var(--fast) var(--ease), color var(--fast) var(--ease);
      white-space: nowrap;
    }

    .rail__icon { width: 1.15rem; height: 1.15rem; flex: none; }

    .rail__item:hover,
    .rail__collapse:hover { background: var(--sidebar-hover); color: #fff; }

    .rail__item--active {
      background: var(--sidebar-active);
      color: var(--sidebar-text-active);
      box-shadow: inset 2px 0 0 var(--red-500);
    }

    .rail__foot {
      border-top: 1px solid var(--sidebar-border);
      padding-top: var(--s-3);
      display: grid;
      gap: 2px;
    }

    .rail__engine { cursor: default; align-items: flex-start; }
    .rail__engine .rail__icon { margin-top: 0.15rem; color: var(--red-400); }
    .rail__engine .rail__label { display: grid; line-height: 1.3; }
    .rail__engine-title { color: #fff; font-size: var(--t-sm); font-weight: 600; }
    .rail__engine-sub { color: #5C6478; font-size: var(--t-xs); }

    .shell--collapsed .rail__label { display: none; }
    .shell--collapsed .rail__item,
    .shell--collapsed .rail__collapse,
    .shell--collapsed .rail__engine { justify-content: center; padding-inline: 0; }
    .shell--collapsed .rail__brand { justify-content: center; }

    /* ---------------- main column ---------------- */

    .col { grid-column: 2; display: flex; flex-direction: column; min-width: 0; }

    .topbar {
      position: sticky;
      top: 0;
      z-index: 30;
      height: var(--topbar-h);
      display: flex;
      align-items: center;
      gap: var(--s-4);
      padding: 0 var(--s-6);
      background: rgba(255, 255, 255, 0.88);
      backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--border);
    }

    .topbar__menu {
      display: none;
      width: 2.25rem; height: 2.25rem;
      align-items: center; justify-content: center;
      border: 1px solid var(--border);
      border-radius: var(--r-sm);
      background: var(--white);
      cursor: pointer;
      co-icon { width: 1.15rem; height: 1.15rem; }
    }

    .topbar__spacer { flex: 1; }

    .content { flex: 1; padding: var(--s-8) var(--s-6) var(--s-12); outline: none; }
    .content__inner { max-width: var(--content-max); margin: 0 auto; }

    .scrim { display: none; }

    /* ---------------- responsive ---------------- */

    @media (max-width: 900px) {
      .shell { grid-template-columns: minmax(0, 1fr); }

      .rail {
        position: fixed;
        inset: 0 auto 0 0;
        width: var(--sidebar-w);
        translate: -100% 0;
        transition: translate var(--base) var(--ease);
      }

      .rail[data-open] { translate: 0 0; box-shadow: var(--shadow-xl); }

      .rail__close { display: inline-flex; }
      .rail__collapse { display: none; }

      .col { grid-column: 1; }
      .topbar__menu { display: inline-flex; }

      .shell--open .scrim {
        display: block;
        position: fixed;
        inset: 0;
        z-index: 35;
        background: rgba(11, 13, 18, 0.45);
        border: 0;
        cursor: pointer;
      }

      .shell--collapsed .rail__label { display: inline; }
      .shell--collapsed .rail__item { justify-content: flex-start; padding-inline: var(--s-3); }
      .shell--collapsed .rail__brand { justify-content: space-between; }

      .content { padding: var(--s-6) var(--s-4) var(--s-10); }
    }

    @media (max-width: 520px) {
      .topbar__cta span { display: none; }
    }
  `,
})
export class AppShellComponent {
  protected readonly nav: readonly NavItem[] = [
    { label: 'Dashboard', icon: 'dashboard', link: '/dashboard' },
    { label: 'Analyze repository', icon: 'repositories', link: '/analyze' },
    { label: 'Jobs', icon: 'jobs', link: '/jobs' },
    { label: 'Documentation', icon: 'documentation', link: '/documentation' },
  ];

  protected readonly collapsed = signal(false);
  protected readonly drawerOpen = signal(false);

  protected toggleCollapsed(): void {
    this.collapsed.update((v) => !v);
  }

  protected openDrawer(): void {
    this.drawerOpen.set(true);
  }

  protected closeDrawer(): void {
    this.drawerOpen.set(false);
  }
}
