import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type StatusTone = 'success' | 'progress' | 'danger' | 'idle' | 'info';

/**
 * Small status indicator. Takes a tone plus whatever label the backend gave
 * us — it never maps or invents its own vocabulary.
 */
@Component({
  selector: 'co-status-pill',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="pill" [attr.data-tone]="tone()">
      <span class="dot" aria-hidden="true"></span>
      <span>{{ label() }}</span>
    </span>
  `,
  styles: `
    :host { display: inline-flex; }

    .pill {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.2rem 0.6rem 0.2rem 0.45rem;
      border-radius: var(--r-pill);
      background: var(--tone-bg);
      color: var(--tone-fg);
      border: 1px solid var(--tone-border);
      font-size: var(--t-xs);
      font-weight: 600;
      white-space: nowrap;
    }

    .dot {
      width: 6px; height: 6px; border-radius: 50%;
      background: currentColor; flex: none;
    }

    .pill[data-tone='success']  { --tone-bg: var(--ok-50);   --tone-fg: var(--ok-600);   --tone-border: #ABEFC6; }
    .pill[data-tone='progress'] { --tone-bg: var(--info-50); --tone-fg: var(--info-600); --tone-border: #B2DDFF; }
    .pill[data-tone='info']     { --tone-bg: var(--warn-50); --tone-fg: var(--warn-600); --tone-border: #FEDF89; }
    .pill[data-tone='danger']   { --tone-bg: var(--err-50);  --tone-fg: var(--err-600);  --tone-border: #FECDCA; }
    .pill[data-tone='idle']     { --tone-bg: var(--idle-50); --tone-fg: var(--grey-500); --tone-border: var(--border); }

    @media (prefers-reduced-motion: no-preference) {
      .pill[data-tone='progress'] .dot { animation: blink 1.4s ease-in-out infinite; }
    }
    @keyframes blink { 50% { opacity: 0.3; } }
  `,
})
export class StatusPillComponent {
  /** Text to display — pass the backend's own status string. */
  readonly label = input.required<string>();
  readonly tone = input<StatusTone>('idle');
}

/** Shared mapping so every screen colours the same status identically. */
export function toneForStatus(status: string | null | undefined): StatusTone {
  switch ((status ?? '').toUpperCase()) {
    case 'COMPLETED':
      return 'success';
    case 'GENERATING':
    case 'SUBMITTING':
    case 'RETRIEVING':
    case 'IN_PROGRESS':
      return 'progress';
    case 'QUEUED':
    case 'PENDING':
      return 'info';
    case 'FAILED':
      return 'danger';
    default:
      return 'idle';
  }
}

/** Title-cases a backend status for display without inventing new wording. */
export function humanStatus(status: string | null | undefined): string {
  if (!status) return 'Unknown';
  return status
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
