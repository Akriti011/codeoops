import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import {
  StateTone,
  WORKFLOW_STATE_LABELS,
  WORKFLOW_STATE_TONES,
  WorkflowState,
} from '../../core/models/workflow-state';

/** Compact status indicator with a live dot. */
@Component({
  selector: 'co-status-pill',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="pill" [attr.data-tone]="tone()">
      <span class="dot" aria-hidden="true"></span>
      <span class="label">{{ label() }}</span>
    </span>
  `,
  styles: `
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.24rem 0.6rem 0.24rem 0.5rem;
      border-radius: var(--co-radius-full);
      border: 1px solid var(--tone-border, var(--co-neutral-border));
      background: var(--tone-bg, var(--co-neutral-bg));
      color: var(--tone-fg, var(--co-neutral));
      font-size: 0.72rem;
      font-weight: 650;
      letter-spacing: 0.03em;
      white-space: nowrap;
    }

    .dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: currentColor;
      flex: none;
    }

    .pill[data-tone='neutral'] {
      --tone-fg: var(--co-neutral);
      --tone-bg: var(--co-neutral-bg);
      --tone-border: var(--co-neutral-border);
    }
    .pill[data-tone='progress'] {
      --tone-fg: var(--co-progress);
      --tone-bg: var(--co-progress-bg);
      --tone-border: var(--co-progress-border);
    }
    .pill[data-tone='success'] {
      --tone-fg: var(--co-success);
      --tone-bg: var(--co-success-bg);
      --tone-border: var(--co-success-border);
    }
    .pill[data-tone='danger'] {
      --tone-fg: var(--co-danger);
      --tone-bg: var(--co-danger-bg);
      --tone-border: var(--co-danger-border);
    }

    @media (prefers-reduced-motion: no-preference) {
      .pill[data-tone='progress'] .dot {
        animation: blink 1.4s ease-in-out infinite;
      }
    }

    @keyframes blink {
      50% {
        opacity: 0.3;
      }
    }
  `,
})
export class StatusPillComponent {
  readonly state = input.required<WorkflowState>();

  protected readonly label = computed(() => WORKFLOW_STATE_LABELS[this.state()]);
  protected readonly tone = computed<StateTone>(
    () => WORKFLOW_STATE_TONES[this.state()],
  );
}
