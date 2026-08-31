import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * Product mark. The glyph is a rounded red tile holding a code caret; the
 * wordmark sits beside it. `variant` controls which palette the text uses so
 * the same component works on the white topbar and the near-black sidebar.
 */
@Component({
  selector: 'co-logo',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="logo" [attr.data-variant]="variant()" [attr.data-size]="size()">
      <span class="logo__glyph" aria-hidden="true">
        <svg viewBox="0 0 32 32" fill="none">
          <rect width="32" height="32" rx="9" fill="url(#coLogoGrad)" />
          <path
            d="M12.6 11.4 9 15.9l3.6 4.5M19.4 11.4 23 15.9l-3.6 4.5"
            stroke="#fff"
            stroke-width="2.1"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <defs>
            <linearGradient id="coLogoGrad" x1="0" y1="0" x2="32" y2="32">
              <stop stop-color="#FF2A4E" />
              <stop offset="1" stop-color="#C41230" />
            </linearGradient>
          </defs>
        </svg>
      </span>
      @if (showWordmark()) {
        <span class="logo__text">
          <span class="logo__name">Code<span class="logo__accent">Oops</span></span>
          @if (tagline()) {
            <span class="logo__tagline">{{ tagline() }}</span>
          }
        </span>
      }
    </span>
  `,
  styles: `
    :host { display: inline-flex; }

    .logo { display: inline-flex; align-items: center; gap: var(--s-3); min-width: 0; }

    .logo__glyph { flex: none; display: block; }
    .logo[data-size='sm'] .logo__glyph { width: 1.75rem; height: 1.75rem; }
    .logo[data-size='md'] .logo__glyph { width: 2.125rem; height: 2.125rem; }
    .logo[data-size='lg'] .logo__glyph { width: 2.75rem; height: 2.75rem; }

    .logo__text { display: grid; min-width: 0; }

    .logo__name {
      font-weight: 700;
      letter-spacing: -0.025em;
      line-height: 1.15;
      white-space: nowrap;
    }

    .logo[data-size='sm'] .logo__name { font-size: var(--t-md); }
    .logo[data-size='md'] .logo__name { font-size: var(--t-lg); }
    .logo[data-size='lg'] .logo__name { font-size: var(--t-2xl); }

    .logo__tagline {
      font-size: var(--t-xs);
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 600;
      line-height: 1.3;
    }

    .logo[data-variant='light'] .logo__name { color: var(--text); }
    .logo[data-variant='light'] .logo__accent { color: var(--red-500); }
    .logo[data-variant='light'] .logo__tagline { color: var(--text-muted); }

    .logo[data-variant='dark'] .logo__name { color: #fff; }
    .logo[data-variant='dark'] .logo__accent { color: var(--red-400); }
    .logo[data-variant='dark'] .logo__tagline { color: var(--sidebar-text); }
  `,
})
export class LogoComponent {
  readonly variant = input<'light' | 'dark'>('light');
  readonly size = input<'sm' | 'md' | 'lg'>('md');
  readonly showWordmark = input(true);
  readonly tagline = input<string | null>(null);
}
