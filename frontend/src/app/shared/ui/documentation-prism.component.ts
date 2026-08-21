import { ChangeDetectionStrategy, Component } from '@angular/core';

/**
 * A rotating triangular prism made of layered "document sheets".
 *
 * Used as the visual anchor of the empty documentation state. It represents an
 * unwritten document — deliberately blank, with no text on the sheets, so it
 * can never read as sample documentation.
 */
@Component({
  selector: 'co-documentation-prism',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="stage" aria-hidden="true">
      <div class="prism">
        <span class="pane pane--a"></span>
        <span class="pane pane--b"></span>
        <span class="pane pane--c"></span>
      </div>
      <div class="halo"></div>
    </div>
  `,
  styles: `
    :host {
      display: block;
    }

    .stage {
      position: relative;
      display: grid;
      place-items: center;
      width: 120px;
      height: 120px;
      perspective: 700px;
    }

    .prism {
      position: relative;
      width: 62px;
      height: 80px;
      transform-style: preserve-3d;
      transform: rotateX(-12deg) rotateY(28deg);
    }

    .pane {
      position: absolute;
      inset: 0;
      border-radius: 7px;
      border: 1px solid var(--co-border);
      background: linear-gradient(150deg, #ffffff, var(--co-bg-subtle) 70%);
      box-shadow: var(--co-shadow-sm);
    }

    .pane--a {
      transform: rotateY(0deg) translateZ(17px);
      border-color: rgba(230, 0, 0, 0.18);
    }
    .pane--b {
      transform: rotateY(120deg) translateZ(17px);
    }
    .pane--c {
      transform: rotateY(240deg) translateZ(17px);
    }

    .halo {
      position: absolute;
      bottom: 10px;
      width: 70px;
      height: 14px;
      border-radius: 50%;
      background: radial-gradient(ellipse, rgba(230, 0, 0, 0.16), transparent 70%);
      filter: blur(7px);
    }

    @media (prefers-reduced-motion: no-preference) {
      .prism {
        animation: rotate 18s linear infinite;
      }
    }

    @keyframes rotate {
      from {
        transform: rotateX(-12deg) rotateY(0deg);
      }
      to {
        transform: rotateX(-12deg) rotateY(360deg);
      }
    }
  `,
})
export class DocumentationPrismComponent {}
