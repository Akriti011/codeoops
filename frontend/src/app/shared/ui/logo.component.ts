import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * The CodeOops mark: a hexagonal repository outline with a live core.
 * Pure SVG + CSS — no image assets, no brand assets from anyone else.
 */
@Component({
  selector: 'co-logo',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="logo" [class.logo--compact]="compact()">
      <svg
        class="mark"
        viewBox="0 0 64 64"
        role="img"
        [attr.aria-label]="showWordmark() ? null : 'CodeOops'"
        [attr.aria-hidden]="showWordmark() ? 'true' : null"
      >
        <defs>
          <linearGradient [attr.id]="gradientId" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#ff4d4d" />
            <stop offset="1" stop-color="#c90000" />
          </linearGradient>
        </defs>
        <path
          class="shell"
          d="M32 6 55 19v26L32 58 9 45V19z"
          fill="none"
          [attr.stroke]="'url(#' + gradientId + ')'"
          stroke-width="3"
          stroke-linejoin="round"
        />
        <path
          class="inner"
          d="M32 17 45 24.5v15L32 47l-13-7.5v-15z"
          fill="none"
          stroke="rgba(17,17,17,0.14)"
          stroke-width="1.5"
          stroke-linejoin="round"
        />
        <circle
          class="core"
          cx="32"
          cy="32"
          r="5.5"
          [attr.fill]="'url(#' + gradientId + ')'"
        />
      </svg>

      @if (showWordmark()) {
        <span class="wordmark">
          <span class="wordmark__name">Code<em>Oops</em></span>
          @if (!compact()) {
            <span class="wordmark__tag">Your code broke. Your docs shouldn't.</span>
          }
        </span>
      }
    </span>
  `,
  styles: `
    .logo {
      display: inline-flex;
      align-items: center;
      gap: 0.7rem;
    }

    .mark {
      width: 38px;
      height: 38px;
      flex: none;
      filter: drop-shadow(0 2px 8px rgba(230, 0, 0, 0.22));
    }

    .logo--compact .mark {
      width: 30px;
      height: 30px;
    }

    .wordmark {
      display: flex;
      flex-direction: column;
      line-height: 1.1;
    }

    .wordmark__name {
      font-weight: 700;
      font-size: 1.16rem;
      letter-spacing: -0.035em;

      em {
        font-style: normal;
        color: var(--co-red-500);
      }
    }

    .logo--compact .wordmark__name {
      font-size: 1rem;
    }

    .wordmark__tag {
      font-size: 0.68rem;
      color: var(--co-text-secondary);
      letter-spacing: 0.005em;
    }

    @media (prefers-reduced-motion: no-preference) {
      .core {
        transform-origin: 32px 32px;
        animation: pulse 3.6s var(--co-ease) infinite;
      }
    }

    @keyframes pulse {
      0%,
      100% {
        transform: scale(1);
        opacity: 1;
      }
      50% {
        transform: scale(0.82);
        opacity: 0.7;
      }
    }
  `,
})
export class LogoComponent {
  readonly showWordmark = input(true);
  readonly compact = input(false);

  /** Unique per instance so multiple logos don't share one gradient node. */
  protected readonly gradientId = `co-logo-${Math.random().toString(36).slice(2, 9)}`;
}
