import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import mermaid from 'mermaid';

import { CodeOopsApiService, repositoryLabel } from '../../shared/data/codeoops-api.service';
import { formatDateTime, httpErrorMessage, isDocumentUnavailable } from '../../shared/data/format';
import { DocumentationJob } from '../../shared/data/models';
import { renderMarkdown } from '../../shared/markdown/markdown';
import { PageHeaderComponent } from '../../shared/layout/page-header.component';
import { CardComponent } from '../../shared/ui/card.component';
import { EmptyStateComponent } from '../../shared/ui/empty-state.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { SkeletonComponent } from '../../shared/ui/skeleton.component';
import {
  StatusPillComponent,
  humanStatus,
  toneForStatus,
} from '../../shared/ui/status-pill.component';

/** The one document this pipeline actually produces. */
const PRIMARY_DOCUMENT = 'overview.md';

@Component({
  selector: 'co-documentation-viewer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    PageHeaderComponent,
    CardComponent,
    EmptyStateComponent,
    StatusPillComponent,
    IconComponent,
    SkeletonComponent,
  ],
  template: `
    <div class="page stack-lg">
      <co-page-header
        [title]="heading()"
        [subtitle]="job()?.repository_url ?? null"
        [crumbs]="[
          { label: 'Home', link: '/dashboard' },
          { label: 'Documents', link: '/jobs' },
          { label: 'Overview' }
        ]"
      >
        <div page-actions class="row">
          @if (job(); as j) {
            <co-status-pill [label]="statusText()" [tone]="statusTone()" />
            <a class="btn btn--ghost btn--sm" [routerLink]="['/jobs', j.id]">
              <co-icon name="jobs" />
              <span>Job details</span>
            </a>
          }
          @if (markdown()) {
            <button type="button" class="btn btn--ghost btn--sm" (click)="copy()">
              <co-icon [name]="copied() ? 'check' : 'file'" />
              <span>{{ copied() ? 'Copied' : 'Copy Markdown' }}</span>
            </button>
            <button type="button" class="btn btn--ghost btn--sm" (click)="download()">
              <co-icon name="download" />
              <span>Markdown</span>
            </button>
            <button type="button" class="btn btn--primary btn--sm" (click)="printPdf()">
              <co-icon name="file" />
              <span>Save as PDF</span>
            </button>
          }
          @if (job()?.repository_id) {
            <button
              type="button"
              class="btn btn--ghost btn--sm btn--danger"
              [disabled]="deleting()"
              (click)="deleteRepo()"
            >
              <co-icon [name]="deleting() ? 'clock' : 'trash'" />
              <span>{{ deleting() ? 'Deleting…' : 'Delete' }}</span>
            </button>
          }
        </div>
      </co-page-header>

      <div class="layout">
        <aside class="rail">
          @if (headings().length) {
            <co-card title="On this page">
              <nav class="toc" aria-label="Table of contents">
                @for (heading of headings(); track heading.id) {
                  <a
                    class="toc__link"
                    [class.toc__link--sub]="heading.level > 2"
                    [href]="'#' + heading.id"
                  >
                    {{ heading.text }}
                  </a>
                }
              </nav>
            </co-card>
          }

          @if (job()?.codewiki; as run) {
            <co-card title="Generation info">
              <dl class="meta">
                <div class="meta__row">
                  <dt>Model</dt>
                  <dd>{{ run.model || '—' }}</dd>
                </div>
                <div class="meta__row">
                  <dt>Engine job</dt>
                  <dd class="t-mono">{{ run.job_id || '—' }}</dd>
                </div>
                <div class="meta__row">
                  <dt>Finished</dt>
                  <dd>{{ finished() }}</dd>
                </div>
              </dl>
            </co-card>
          }
        </aside>

        <!-- ---------------- document ---------------- -->
        <co-card flush>
          @if (availableDocs().length > 1) {
            <div class="docstrip" role="tablist" aria-label="Documents">
              @for (d of availableDocs(); track d) {
                <button
                  type="button"
                  role="tab"
                  class="docstrip__btn"
                  [class.docstrip__btn--active]="activeDoc() === d"
                  [attr.aria-selected]="activeDoc() === d"
                  (click)="selectDoc(d)"
                >
                  {{ docLabel(d) }}
                </button>
              }
            </div>
          }
          <div class="docbody">
          @if (loading()) {
            <div class="stack">
              <co-skeleton width="55%" height="1.75rem" />
              <co-skeleton width="100%" height="0.9rem" />
              <co-skeleton width="92%" height="0.9rem" />
              <co-skeleton width="80%" height="0.9rem" />
              <co-skeleton width="100%" height="12rem" radius="var(--r-md)" />
            </div>
          } @else if (error(); as message) {
            <co-empty-state
              title="Could not load the overview"
              [message]="message"
              icon="alert"
              tone="amber"
            >
              <button type="button" class="btn btn--ghost btn--sm" (click)="reload()">
                <co-icon name="refresh" />
                <span>Try again</span>
              </button>
            </co-empty-state>
          } @else if (notGenerated()) {
            <co-empty-state
              title="No overview for this job"
              [message]="notGeneratedMessage()"
              icon="documentation"
              tone="grey"
            >
              <a class="btn btn--ghost btn--sm" [routerLink]="['/jobs', jobId()]">
                <co-icon name="jobs" />
                <span>Open job progress</span>
              </a>
            </co-empty-state>
          } @else {
            <article #articleRef class="md" [innerHTML]="html()"></article>
          }
          </div>
        </co-card>
      </div>
    </div>
  `,
  styles: `
    :host { display: block; }

    .docstrip {
      display: flex; gap: var(--s-1);
      padding: var(--s-3) var(--s-4) 0;
      border-bottom: 1px solid var(--border);
      flex-wrap: wrap;
    }
    .docstrip__btn {
      border: 0; background: none; cursor: pointer;
      padding: 0.5rem 0.9rem;
      font-size: var(--t-sm); font-weight: 600;
      color: var(--text-secondary);
      border-bottom: 2px solid transparent;
      margin-bottom: -1px;
    }
    .docstrip__btn:hover { color: var(--text); }
    .docstrip__btn--active { color: var(--red-600); border-bottom-color: var(--red-500); }

    .docbody { padding: var(--s-6); }

    .layout {
      display: grid;
      grid-template-columns: 17rem minmax(0, 1fr);
      gap: var(--s-6);
      align-items: start;
    }

    @media (max-width: 1080px) {
      .layout { grid-template-columns: minmax(0, 1fr); }
    }

    .rail { display: grid; gap: var(--s-4); position: sticky; top: calc(var(--topbar-h) + var(--s-4)); }

    @media (max-width: 1080px) {
      .rail { position: static; }
    }

    .toc { display: grid; gap: var(--s-2); }
    .toc__link {
      font-size: var(--t-sm);
      color: var(--text-secondary);
      border-left: 2px solid var(--border);
      padding-left: var(--s-3);
      line-height: 1.4;
    }
    .toc__link:hover { color: var(--red-500); border-left-color: var(--red-500); }
    .toc__link--sub { padding-left: var(--s-5); font-size: var(--t-xs); }

    .meta { display: grid; gap: var(--s-3); }
    .meta__row { display: flex; justify-content: space-between; gap: var(--s-3); font-size: var(--t-sm); }
    .meta__row dt { color: var(--text-secondary); flex: none; }
    .meta__row dd { margin: 0; text-align: right; font-weight: 600; word-break: break-all; }
  `,
})
export class DocumentationViewerComponent {
  private readonly api = inject(CodeOopsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly jobId = signal<string | null>(null);
  private readonly injector = inject(Injector);
  private readonly articleRef = viewChild<ElementRef<HTMLElement>>('articleRef');

  protected readonly job = signal<DocumentationJob | null>(null);
  protected readonly markdown = signal<string | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly notGenerated = signal(false);
  protected readonly copied = signal(false);
  protected readonly deleting = signal(false);

  private readonly rendered = computed(() => renderMarkdown(this.markdown()));

  protected readonly headings = computed(() =>
    this.rendered().headings.filter((h) => h.level >= 2 && h.level <= 3),
  );

  protected readonly html = computed<SafeHtml>(() =>
    // renderMarkdown() escapes every character of the source before adding its
    // own markup, so the result contains no repository-supplied HTML.
    this.sanitizer.bypassSecurityTrustHtml(this.rendered().html),
  );

  /** Which generated document is shown. overview.md is always available. */
  protected readonly activeDoc = signal<'overview' | 'hld' | 'lld'>('overview');
  protected readonly availableDocs = computed<Array<'overview' | 'hld' | 'lld'>>(() => {
    const docs = this.job()?.documents ?? [];
    const out: Array<'overview' | 'hld' | 'lld'> = ['overview'];
    if (docs.includes('hld.md')) out.push('hld');
    if (docs.includes('lld.md')) out.push('lld');
    return out;
  });

  protected docLabel(d: 'overview' | 'hld' | 'lld'): string {
    return { overview: 'Overview', hld: 'High-Level Design', lld: 'Low-Level Design' }[d];
  }

  protected selectDoc(d: 'overview' | 'hld' | 'lld'): void {
    if (this.activeDoc() === d) return;
    const id = this.jobId();
    if (!id) return;
    this.activeDoc.set(d);
    this.loading.set(true);
    this.error.set(null);
    const req =
      d === 'overview'
        ? this.api.getDocument(id, 'overview.md').pipe(map((a) => a.content ?? ''))
        : this.api.getJobDocument(id, `${d}.md`);
    req.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (text) => {
        this.markdown.set((text ?? '').trim());
        this.notGenerated.set(!(text ?? '').trim());
        this.loading.set(false);
      },
      error: (err: unknown) => {
        this.loading.set(false);
        this.error.set(httpErrorMessage(err, `The ${this.docLabel(d)} could not be loaded.`));
      },
    });
  }

  protected readonly heading = computed(() => {
    const job = this.job();
    return job ? repositoryLabel(job) : 'Overview';
  });

  protected readonly statusText = computed(() => humanStatus(this.job()?.status));
  protected readonly statusTone = computed(() => toneForStatus(this.job()?.status));
  protected readonly finished = computed(() =>
    formatDateTime(this.job()?.codewiki?.finished_at ?? this.job()?.completed_at),
  );

  protected readonly notGeneratedMessage = computed(() => {
    const status = (this.job()?.status ?? '').toUpperCase();
    if (status === 'FAILED') {
      return 'This job failed before an overview was produced. Open the job to see the failure reported by the backend.';
    }
    if (status && status !== 'COMPLETED') {
      return 'This job has not finished yet. The overview appears here once generation completes.';
    }
    return 'The backend has no overview.md stored for this job.';
  });

  constructor() {
    // Config only — no rendering happens until mermaid.run() is called
    // below, once real diagram markup actually exists in the DOM.
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'default' });

    // Re-render diagrams every time new markdown produces new `pre.mermaid`
    // elements. afterNextRender (not a plain effect body) is what actually
    // guarantees this runs after Angular has written html() into the DOM —
    // mermaid.run() reads live elements, not the HTML string.
    effect(() => {
      this.html();
      afterNextRender(() => this.renderMermaidDiagrams(), { injector: this.injector });
    });

    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.jobId.set(params.get('id'));
      this.reload();
    });
  }

  private renderMermaidDiagrams(): void {
    const article = this.articleRef()?.nativeElement;
    if (!article) return;
    const nodes = Array.from(article.querySelectorAll<HTMLElement>('pre.mermaid'));
    if (nodes.length === 0) return;
    // Real diagram source from the backend's own overview.md, rendered by
    // the actual mermaid library — never a placeholder or hardcoded image.
    // A malformed diagram fails to render on its own node; it doesn't take
    // the rest of the document down with it.
    mermaid.run({ nodes }).catch((err: unknown) => {
      console.error('Mermaid diagram rendering failed', err);
    });
  }

  protected reload(): void {
    const id = this.jobId();
    this.markdown.set(null);
    this.notGenerated.set(false);
    this.error.set(null);
    this.activeDoc.set('overview');

    if (!id) {
      this.loading.set(false);
      this.error.set('No job id was supplied in the URL.');
      return;
    }

    this.loading.set(true);

    this.api
      .getJob(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (job) => this.job.set(job),
        error: () => this.job.set(null),
      });

    this.api
      .getDocument(id, PRIMARY_DOCUMENT)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (doc) => {
          const content = (doc.content ?? '').trim();
          if (!content) {
            this.notGenerated.set(true);
          } else {
            this.markdown.set(doc.content ?? '');
          }
          this.loading.set(false);
        },
        error: (err: unknown) => {
          this.loading.set(false);
          // 404 = unknown job, 409 = job known but no verified overview yet —
          // both mean the same thing to a viewer: nothing to render.
          if (isDocumentUnavailable(err)) {
            this.notGenerated.set(true);
            return;
          }
          this.error.set(
            httpErrorMessage(err, 'The request for the overview did not complete.'),
          );
        },
      });
  }

  protected async copy(): Promise<void> {
    const text = this.markdown();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 2000);
    } catch {
      this.copied.set(false);
    }
  }

  protected download(): void {
    const text = this.markdown();
    if (!text) return;

    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = PRIMARY_DOCUMENT;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  /**
   * Save as PDF via the browser's own print pipeline. The global
   * `@media print` rules (styles.scss, keyed on `body.printing-doc`) strip the
   * app chrome and print just the `.md` article — the Mermaid diagrams come
   * through as real vector SVG because they are already rendered in the DOM.
   * No server round-trip and no PDF library: the backend's xhtml2pdf export
   * can only emit the diagrams as code blocks.
   */
  protected printPdf(): void {
    if (!this.markdown()) return;

    const body = document.body;
    const previousTitle = document.title;
    // Chrome/Edge/Firefox seed the default PDF filename from document.title.
    const slug = this.heading()
      .replace(/[^\w.-]+/g, '-')
      .replace(/^-/, '')
      .replace(/-$/, '');
    document.title = `${slug || 'overview'} - overview`;
    body.classList.add('printing-doc');

    const restore = (): void => {
      body.classList.remove('printing-doc');
      document.title = previousTitle;
      window.removeEventListener('afterprint', restore);
    };
    window.addEventListener('afterprint', restore);
    // Fallback for the rare browser that never fires afterprint.
    setTimeout(restore, 60_000);

    window.print();
  }

  /**
   * Move the repository this overview belongs to — with every run for it and
   * the generated overview — to the bin. Recoverable from the Bin section;
   * on success we leave for the Documentation list.
   */
  protected deleteRepo(): void {
    const repoId = this.job()?.repository_id;
    if (!repoId || this.deleting()) return;

    const label = this.heading();
    if (!confirm(`Move "${label}" to the bin? You can restore it from the Bin section.`)) {
      return;
    }

    this.deleting.set(true);
    this.api
      .deleteRepository(repoId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deleting.set(false);
          void this.router.navigate(['/jobs']);
        },
        error: (err: unknown) => {
          this.deleting.set(false);
          this.error.set(httpErrorMessage(err, `Could not move "${label}" to the bin.`));
        },
      });
  }
}
