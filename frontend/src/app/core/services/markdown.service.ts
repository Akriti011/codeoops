import { Injectable } from '@angular/core';
import DOMPurify from 'dompurify';
import { Marked } from 'marked';

export interface DocumentationTocItem {
  readonly id: string;
  readonly text: string;
  readonly depth: number;
}

export interface RenderedDocumentation {
  readonly html: string;
  readonly toc: readonly DocumentationTocItem[];
  readonly hasDiagrams: boolean;
}

/** Highlight.js grammars registered on first use — kept small and lazy-loaded. */
const LANGUAGE_LOADERS: Readonly<Record<string, () => Promise<{ default: unknown }>>> = {
  typescript: () => import('highlight.js/lib/languages/typescript'),
  javascript: () => import('highlight.js/lib/languages/javascript'),
  python: () => import('highlight.js/lib/languages/python'),
  json: () => import('highlight.js/lib/languages/json'),
  bash: () => import('highlight.js/lib/languages/bash'),
  yaml: () => import('highlight.js/lib/languages/yaml'),
  xml: () => import('highlight.js/lib/languages/xml'),
  css: () => import('highlight.js/lib/languages/css'),
  markdown: () => import('highlight.js/lib/languages/markdown'),
  sql: () => import('highlight.js/lib/languages/sql'),
  java: () => import('highlight.js/lib/languages/java'),
  go: () => import('highlight.js/lib/languages/go'),
  rust: () => import('highlight.js/lib/languages/rust'),
  dockerfile: () => import('highlight.js/lib/languages/dockerfile'),
};

let hljsPromise: Promise<typeof import('highlight.js/lib/core').default> | null = null;

async function loadHighlighter(): Promise<typeof import('highlight.js/lib/core').default> {
  if (!hljsPromise) {
    hljsPromise = (async () => {
      const core = (await import('highlight.js/lib/core')).default;
      const entries = Object.entries(LANGUAGE_LOADERS);
      const modules = await Promise.all(entries.map(([, load]) => load()));
      entries.forEach(([name], index) => {
        core.registerLanguage(name, modules[index].default as never);
      });
      return core;
    })();
  }
  return hljsPromise;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function slugify(text: string, seen: Map<string, number>): string {
  const base =
    text
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9\s-]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-') || 'section';
  const count = seen.get(base) ?? 0;
  seen.set(base, count + 1);
  return count === 0 ? base : `${base}-${count}`;
}

interface InlineToken {
  readonly text?: string;
  readonly raw?: string;
  readonly tokens?: readonly InlineToken[];
}

function plainText(tokens: readonly InlineToken[] | undefined): string {
  if (!tokens) {
    return '';
  }
  return tokens
    .map((token) => {
      if (token.tokens && token.tokens.length > 0) {
        return plainText(token.tokens);
      }
      return token.text ?? token.raw ?? '';
    })
    .join('');
}

/**
 * Renders CodeWiki-produced Markdown into sanitized, syntax-highlighted HTML
 * and extracts a heading-based table of contents from the same pass, so the
 * reader's navigation always matches the headings actually present in the
 * document — nothing about the document structure is invented client-side.
 */
@Injectable({ providedIn: 'root' })
export class MarkdownService {
  async render(markdown: string): Promise<RenderedDocumentation> {
    const hljs = await loadHighlighter();

    const toc: DocumentationTocItem[] = [];
    const seen = new Map<string, number>();
    let hasDiagrams = false;

    const marked = new Marked({ gfm: true, breaks: false });
    marked.use({
      renderer: {
        heading(token) {
          const depth = token.depth;
          const label = plainText(token.tokens).trim();
          const id = slugify(label, seen);
          const inner = this.parser.parseInline(token.tokens);
          if (depth >= 2 && depth <= 4 && label) {
            toc.push({ id, text: label, depth });
          }
          return `<h${depth} id="${id}">${inner}</h${depth}>\n`;
        },
        code(token) {
          const language = (token.lang ?? '').trim().split(/\s+/)[0]?.toLowerCase();

          if (language === 'mermaid') {
            hasDiagrams = true;
            return `<pre class="mermaid">${escapeHtml(token.text)}</pre>\n`;
          }

          const grammar = language && hljs.getLanguage(language) ? language : null;
          const highlighted = grammar
            ? hljs.highlight(token.text, { language: grammar }).value
            : escapeHtml(token.text);
          const cssClass = grammar ? ` language-${grammar}` : '';
          return `<pre><code class="hljs${cssClass}">${highlighted}</code></pre>\n`;
        },
        link(token) {
          const inner = this.parser.parseInline(token.tokens);
          const href = token.href ?? '';
          const external = /^https?:\/\//i.test(href);
          const title = token.title ? ` title="${escapeHtml(token.title)}"` : '';
          const externalAttrs = external ? ' target="_blank" rel="noopener noreferrer"' : '';
          return `<a href="${escapeHtml(href)}"${title}${externalAttrs}>${inner}</a>`;
        },
      },
    });

    const rawHtml = marked.parse(markdown, { async: false });
    const html = DOMPurify.sanitize(rawHtml, { ADD_ATTR: ['target', 'rel'] });

    return { html, toc, hasDiagrams };
  }
}
