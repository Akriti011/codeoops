import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { ToastService } from '../../core/services/toast.service';

/**
 * Renders notifications in a polite live region.
 * The application never uses browser alerts.
 */
@Component({
  selector: 'co-toast-host',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="host" role="region" aria-label="Notifications">
      <div class="stack" aria-live="polite" aria-atomic="false">
        @for (toast of toasts(); track toast.id) {
          <article class="toast" [attr.data-tone]="toast.tone">
            <span class="bar" aria-hidden="true"></span>
            <div class="body">
              <p class="title">{{ toast.title }}</p>
              @if (toast.message) {
                <p class="message">{{ toast.message }}</p>
              }
            </div>
            <button
              type="button"
              class="close"
              (click)="toastService.dismiss(toast.id)"
              [attr.aria-label]="'Dismiss notification: ' + toast.title"
            >
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <path
                  d="M4 4l8 8M12 4l-8 8"
                  stroke="currentColor"
                  stroke-width="1.6"
                  stroke-linecap="round"
                />
              </svg>
            </button>
          </article>
        }
      </div>
    </div>
  `,
  styles: `
    .host {
      position: fixed;
      right: clamp(1rem, 2vw, 2rem);
      bottom: clamp(1rem, 2vw, 2rem);
      z-index: 120;
      pointer-events: none;
    }

    .stack {
      display: flex;
      flex-direction: column;
      gap: 0.7rem;
      width: min(24rem, calc(100vw - 2rem));
    }

    .toast {
      display: flex;
      align-items: flex-start;
      gap: 0.85rem;
      padding: 0.9rem 0.9rem 0.9rem 0;
      overflow: hidden;
      pointer-events: auto;
      background: var(--co-white);
      border: 1px solid var(--co-border);
      border-radius: var(--co-radius-lg);
      box-shadow: var(--co-shadow-lg);
    }

    @media (prefers-reduced-motion: no-preference) {
      .toast {
        animation: slide-in 220ms var(--co-ease-out) both;
      }
    }

    @keyframes slide-in {
      from {
        opacity: 0;
        transform: translate3d(0, 10px, 0) scale(0.98);
      }
    }

    .bar {
      width: 3px;
      align-self: stretch;
      border-radius: 0 3px 3px 0;
      background: var(--tone, var(--co-neutral));
      flex: none;
    }

    .toast[data-tone='success'] {
      --tone: var(--co-success);
    }
    .toast[data-tone='error'] {
      --tone: var(--co-danger);
    }
    .toast[data-tone='info'] {
      --tone: var(--co-text-tertiary);
    }

    .body {
      flex: 1;
      min-width: 0;
    }

    .title {
      font-size: 0.92rem;
      font-weight: 650;
      letter-spacing: -0.01em;
      color: var(--co-text);
    }

    .message {
      margin-top: 0.2rem;
      font-size: 0.84rem;
      color: var(--co-text-secondary);
      overflow-wrap: anywhere;
    }

    .close {
      flex: none;
      display: grid;
      place-items: center;
      width: 26px;
      height: 26px;
      border-radius: 8px;
      border: 1px solid transparent;
      background: transparent;
      color: var(--co-text-tertiary);
      cursor: pointer;
      transition:
        color var(--co-fast) var(--co-ease),
        background var(--co-fast) var(--co-ease);

      svg {
        width: 14px;
        height: 14px;
      }

      &:hover {
        color: var(--co-text);
        background: var(--co-bg-subtle);
      }
    }
  `,
})
export class ToastHostComponent {
  protected readonly toastService = inject(ToastService);
  protected readonly toasts = this.toastService.toasts;
}
