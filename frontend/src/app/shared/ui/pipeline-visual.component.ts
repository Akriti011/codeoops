import { ChangeDetectionStrategy, Component } from '@angular/core';

/**
 * Conceptual product illustration: Repository → CodeWiki → Documentation.
 *
 * Three tilted CSS-3D cards (perspective + preserve-3d, no WebGL/canvas)
 * connected by thin flow lines. Purely decorative — no repository-specific
 * or generation-specific data is ever rendered here.
 */
@Component({
  selector: 'co-pipeline-visual',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="stage" aria-hidden="true">
      <div class="card card--repo">
        <span class="card__icon">
          <svg viewBox="0 0 20 20"><path d="M3 6.5 10 3l7 3.5-7 3.5zM3 10l7 3.5 7-3.5M3 13.5 10 17l7-3.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </span>
        <span class="card__label">Repository</span>
        <span class="card__sub">GitHub</span>
      </div>

      <div class="link link--1">
        <span class="link__pulse"></span>
      </div>

      <div class="card card--engine">
        <span class="card__glow" aria-hidden="true"></span>
        <span class="card__icon card__icon--accent">
          <svg viewBox="0 0 20 20"><path d="M10 2.5v3M10 14.5v3M17.5 10h-3M5.5 10h-3M15.3 4.7l-2.1 2.1M6.8 13.2l-2.1 2.1M15.3 15.3l-2.1-2.1M6.8 6.8 4.7 4.7" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="10" cy="10" r="3" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>
        </span>
        <span class="card__label">CodeWiki</span>
        <span class="card__sub">Documentation engine</span>
      </div>

      <div class="link link--2">
        <span class="link__pulse"></span>
      </div>

      <div class="card card--docs">
        <span class="card__icon">
          <svg viewBox="0 0 20 20"><path d="M5 3h7l3 3v11H5zM12 3v3h3M7.5 10h5M7.5 13h3.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </span>
        <span class="card__label">Documentation</span>
        <span class="card__sub">Generated output</span>
      </div>
    </div>
  `,
  styles: `
    :host {
      display: block;
    }

    .stage {
      position: relative;
      display: grid;
      justify-items: center;
      gap: 0;
      width: min(100%, 20rem);
      margin-inline: auto;
      perspective: 1200px;
    }

    .card {
      position: relative;
      display: grid;
      justify-items: start;
      gap: 0.15rem;
      width: 13.5rem;
      padding: 0.95rem 1.1rem;
      border-radius: var(--co-radius-lg);
      background: var(--co-white);
      border: 1px solid var(--co-border);
      box-shadow: var(--co-shadow-md);
      transform-style: preserve-3d;
    }

    .card--repo {
      transform: rotateX(6deg) rotateY(-16deg);
      margin-right: 3.5rem;
    }

    .card--engine {
      transform: rotateX(6deg) rotateY(0deg) translateZ(6px) scale(1.04);
      z-index: 1;
      border-color: rgba(230, 0, 0, 0.22);
    }

    .card--docs {
      transform: rotateX(6deg) rotateY(16deg);
      margin-left: 3.5rem;
    }

    .card__glow {
      position: absolute;
      inset: -1px;
      border-radius: inherit;
      background: radial-gradient(120% 140% at 20% 0%, rgba(230, 0, 0, 0.1), transparent 60%);
      pointer-events: none;
    }

    .card__icon {
      display: grid;
      place-items: center;
      width: 30px;
      height: 30px;
      margin-bottom: 0.35rem;
      border-radius: 9px;
      color: var(--co-text-secondary);
      background: var(--co-bg-subtle);
      border: 1px solid var(--co-border);

      svg {
        width: 16px;
        height: 16px;
      }
    }

    .card__icon--accent {
      color: var(--co-red-500);
      background: var(--co-red-50);
      border-color: var(--co-red-100);
    }

    .card__label {
      font-size: 0.88rem;
      font-weight: 650;
      letter-spacing: -0.01em;
      color: var(--co-text);
    }

    .card__sub {
      font-size: 0.72rem;
      color: var(--co-text-tertiary);
    }

    .link {
      position: relative;
      width: 1px;
      height: 1.6rem;
      background: linear-gradient(180deg, var(--co-border-strong), var(--co-border));
    }

    .link__pulse {
      position: absolute;
      left: 50%;
      top: 0;
      width: 5px;
      height: 5px;
      translate: -50% 0;
      border-radius: 50%;
      background: var(--co-red-500);
      box-shadow: 0 0 0 3px rgba(230, 0, 0, 0.14);
      opacity: 0;
    }

    @media (prefers-reduced-motion: no-preference) {
      .card--repo,
      .card--docs {
        animation: float 7s var(--co-ease) infinite alternate;
      }
      .card--docs {
        animation-delay: 0.4s;
      }
      .link--1 .link__pulse {
        animation: flow 2.6s var(--co-ease) infinite;
      }
      .link--2 .link__pulse {
        animation: flow 2.6s var(--co-ease) infinite;
        animation-delay: 1.3s;
      }
    }

    @keyframes float {
      to {
        transform: rotateX(6deg) rotateY(var(--tilt, -16deg)) translateY(-5px);
      }
    }

    .card--docs {
      --tilt: 16deg;
    }

    @keyframes flow {
      0% {
        opacity: 0;
        top: 0;
      }
      15% {
        opacity: 1;
      }
      85% {
        opacity: 1;
      }
      100% {
        opacity: 0;
        top: 100%;
      }
    }

    @media (max-width: 640px) {
      .stage {
        width: min(100%, 16rem);
      }
      .card {
        width: 11.5rem;
        padding: 0.8rem 0.9rem;
      }
      .card--repo,
      .card--docs {
        margin-inline: 2rem;
      }
    }
  `,
})
export class PipelineVisualComponent {}
