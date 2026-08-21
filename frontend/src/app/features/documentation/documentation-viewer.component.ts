import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { DatePipe } from '@angular/common';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

import { DocumentationState } from '../../core/models/documentation.model';
import { Repository } from '../../core/models/repository.model';
import {
  DocumentationTocItem,
  MarkdownService,
} from '../../core/services/markdown.service';
import { DocumentationPrismComponent } from '../../shared/ui/documentation-prism.component';

/**
 * The documentation reader.
 *
 * When no artifact exists it renders an explicit empty state — never
 * substitute prose, sample Markdown or a "preview". When an artifact exists,
 * its `entry_document` is the only source of content: rendered Markdown,
 * syntax-highlighted code and Mermaid diagrams, all derived from that single
 * string. The table of contents is extracted from the document's own
 * headings and reported to the parent via `tocChange` — never a fixed list.
 */
@Component({
  selector: 'co-documentation-viewer',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, DocumentationPrismComponent],
  template: `
    <article class="viewer" aria-live="polite">
      <header class="viewer__head">
        <div class="viewer__titles">
          <p class="co-eyebrow">Documentation</p>
          <h2 class="co-h1 viewer__title">{{ repository().name }}</h2>
        </div>

        <dl class="viewer__meta">
          <div>
            <dt>Repository</dt>
            <dd class="co-mono">{{ repository().owner }}/{{ repository().name }}</dd>
          </div>
          <div>
            <dt>Branch</dt>
            <dd>{{ repository().default_branch }}</dd>
          </div>
          <div>
            <dt>Engine</dt>
            <dd>{{ providerName() }}</dd>
          </div>
          <div>
            <dt>Generated</dt>
            <dd>
              {{
                state().artifact
                  ? (state().artifact!.generated_at | date: 'medium')
                  : 'Not generated yet'
              }}
            </dd>
          </div>
        </dl>
      </header>

      @if (state().artifact === null) {
        <!-- Empty state. No document content is rendered here, by design. -->
        <section class="empty" aria-labelledby="empty-title">
          <co-documentation-prism />
          <h3 id="empty-title" class="empty__title">
            No CodeWiki documentation available.
          </h3>
          <p class="empty__body">
            Documentation has not been generated yet for
            <span class="co-mono">{{ repository().owner }}/{{ repository().name }}</span
            >.
          </p>
          @if (state().detail) {
            <p class="empty__detail">{{ state().detail }}</p>
          }
          <p class="empty__rule">
            CodeOops does not write documentation itself. Nothing appears in this
            reader until CodeWiki has produced an artifact for this repository.
          </p>
        </section>

        <section class="diagram" aria-labelledby="diagram-title">
          <div class="diagram__head">
            <h3 id="diagram-title" class="co-h3">Architecture visualization</h3>
            <span class="diagram__flag">Mermaid-ready</span>
          </div>
          <div class="diagram__canvas">
            <p class="diagram__note">
              Diagrams are rendered from the engine's own Mermaid output. There is
              nothing to render yet.
            </p>
          </div>
        </section>
      } @else {
        <section class="document">
          @if (renderedHtml(); as html) {
            <div class="doc-prose" #docProse [innerHTML]="html"></div>
          } @else {
            <p class="co-help">Rendering documentation…</p>
          }
        </section>
      }
    </article>
  `,
  styleUrl: './documentation-viewer.component.scss',
})
export class DocumentationViewerComponent {
  readonly repository = input.required<Repository>();
  readonly state = input.required<DocumentationState>();

  /** Reports the live table of contents extracted from the rendered document. */
  readonly tocChange = output<readonly DocumentationTocItem[]>();

  private readonly markdown = inject(MarkdownService);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly elementRef = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);

  private renderToken = 0;

  protected readonly providerName = computed(
    () => this.state().artifact?.provider ?? 'CodeWiki (not connected)',
  );

  private readonly rendered = signal<SafeHtml | null>(null);
  protected readonly renderedHtml = this.rendered.asReadonly();

  constructor() {
    effect(() => {
      const artifact = this.state().artifact;

      if (!artifact) {
        this.rendered.set(null);
        this.tocChange.emit([]);
        return;
      }

      const token = ++this.renderToken;
      this.markdown.render(artifact.entry_document).then((result) => {
        if (token !== this.renderToken) {
          return;
        }
        this.rendered.set(this.sanitizer.bypassSecurityTrustHtml(result.html));
        this.tocChange.emit(result.toc);
        if (result.hasDiagrams) {
          afterNextRender(() => this.renderDiagrams(), { injector: this.injector });
        }
      });
    });
  }

  private renderDiagrams(): void {
    const nodes = this.elementRef.nativeElement.querySelectorAll<HTMLElement>(
      '.doc-prose pre.mermaid',
    );
    if (nodes.length === 0) {
      return;
    }
    import('mermaid').then(({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, theme: 'neutral', securityLevel: 'strict' });
      void mermaid.run({ nodes: Array.from(nodes) });
    });
  }
}
