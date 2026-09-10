/**
 * Minimal Markdown → HTML renderer, with real Mermaid diagram rendering as
 * its one dependency (see documentation-viewer.component.ts, which calls
 * `mermaid.run()` against the `pre.mermaid` elements this file emits).
 *
 * Scope is exactly what CodeWiki emits in `overview.md`: headings, paragraphs,
 * fenced code (including ```mermaid), inline code, bold/italic, links, bullet
 * and numbered lists, blockquotes, tables and horizontal rules.
 *
 * Everything is HTML-escaped before any markup is added, so repository content
 * cannot inject markup into the page — a ```mermaid fence is escaped exactly
 * like any other fenced block; only the fact that it lands in a `pre.mermaid`
 * element (mermaid.js's own diagram-source convention, not a raw-HTML sink)
 * differs, and mermaid.js only ever reads that element's already-decoded text
 * content, never re-parses it as HTML. Nothing here invents content: input
 * that this renderer does not recognise is emitted as escaped text.
 */

export interface Heading {
  level: number;
  text: string;
  id: string;
}

export interface RenderedMarkdown {
  html: string;
  headings: Heading[];
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .slice(0, 80);
}

/** Inline formatting. Operates on already-escaped text. */
function inline(escaped: string): string {
  let out = escaped;

  // `code`
  out = out.replace(/`([^`]+)`/g, '<code class="md-code">$1</code>');

  // [text](href) — only http(s), mailto and in-page anchors are linked.
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, text, href) => {
    const safe = /^(https?:\/\/|mailto:|#)/i.test(href);
    if (!safe) return text;
    const external = /^https?:/i.test(href);
    const attrs = external ? ' target="_blank" rel="noopener noreferrer"' : '';
    return `<a class="md-link" href="${href}"${attrs}>${text}</a>`;
  });

  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  out = out.replace(/(^|\W)_([^_\n]+)_(?=\W|$)/g, '$1<em>$2</em>');

  return out;
}

function renderTable(rows: string[]): string {
  const cells = (row: string): string[] =>
    row
      .replace(/^\s*\|/, '')
      .replace(/\|\s*$/, '')
      .split('|')
      .map((c) => c.trim());

  const head = cells(rows[0]);
  const body = rows.slice(2).map(cells);

  const thead =
    '<thead><tr>' +
    head.map((c) => `<th>${inline(escapeHtml(c))}</th>`).join('') +
    '</tr></thead>';

  const tbody =
    '<tbody>' +
    body
      .map(
        (row) =>
          '<tr>' + row.map((c) => `<td>${inline(escapeHtml(c))}</td>`).join('') + '</tr>',
      )
      .join('') +
    '</tbody>';

  return `<div class="md-table-wrap"><table class="md-table">${thead}${tbody}</table></div>`;
}

export function renderMarkdown(source: string | null | undefined): RenderedMarkdown {
  if (!source) return { html: '', headings: [] };

  const lines = source.replace(/\r\n/g, '\n').split('\n');
  const out: string[] = [];
  const headings: Heading[] = [];
  const seenIds = new Set<string>();

  let paragraph: string[] = [];

  const flushParagraph = (): void => {
    if (!paragraph.length) return;
    out.push(`<p>${inline(escapeHtml(paragraph.join(' ')))}</p>`);
    paragraph = [];
  };

  const uniqueId = (base: string): string => {
    let id = base || 'section';
    let n = 2;
    while (seenIds.has(id)) id = `${base}-${n++}`;
    seenIds.add(id);
    return id;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // fenced code / mermaid
    const fence = /^\s*```\s*([\w-]*)\s*$/.exec(line);
    if (fence) {
      flushParagraph();
      const lang = fence[1] ?? '';
      const buffer: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        buffer.push(lines[i]);
        i++;
      }
      const code = escapeHtml(buffer.join('\n'));
      if (lang.toLowerCase() === 'mermaid') {
        // mermaid.js's own convention: it scans for `pre.mermaid` elements
        // and replaces their content with the rendered SVG. The text here
        // is already HTML-escaped above, so the browser decodes it back to
        // plain diagram source as this is parsed into the DOM — mermaid.js
        // never sees or executes it as markup, only as text content.
        out.push(`<pre class="mermaid">${code}</pre>`);
      } else {
        const langClass = lang ? ` data-lang="${escapeHtml(lang)}"` : '';
        out.push(`<pre class="md-pre"${langClass}><code>${code}</code></pre>`);
      }
      continue;
    }

    // table
    if (
      /^\s*\|/.test(line) &&
      i + 1 < lines.length &&
      /^\s*\|?[\s:-]*-[-\s:|]*$/.test(lines[i + 1])
    ) {
      flushParagraph();
      const rows: string[] = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) {
        rows.push(lines[i]);
        i++;
      }
      i--;
      if (rows.length >= 2) out.push(renderTable(rows));
      continue;
    }

    // heading
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flushParagraph();
      const level = heading[1].length;
      const text = heading[2].replace(/\s*#+\s*$/, '').trim();
      const id = uniqueId(slugify(text));
      headings.push({ level, text, id });
      out.push(`<h${level} id="${id}" class="md-h md-h${level}">${inline(escapeHtml(text))}</h${level}>`);
      continue;
    }

    // horizontal rule
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flushParagraph();
      out.push('<hr class="md-hr" />');
      continue;
    }

    // blockquote
    if (/^\s*>\s?/.test(line)) {
      flushParagraph();
      const buffer: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buffer.push(lines[i].replace(/^\s*>\s?/, ''));
        i++;
      }
      i--;
      out.push(`<blockquote class="md-quote">${inline(escapeHtml(buffer.join(' ')))}</blockquote>`);
      continue;
    }

    // lists (single level — CodeWiki output does not nest deeply)
    if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
      flushParagraph();
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items: string[] = [];
      while (
        i < lines.length &&
        (ordered ? /^\s*\d+[.)]\s+/.test(lines[i]) : /^\s*[-*+]\s+/.test(lines[i]))
      ) {
        const text = lines[i].replace(ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*+]\s+/, '');
        items.push(`<li>${inline(escapeHtml(text))}</li>`);
        i++;
      }
      i--;
      const tag = ordered ? 'ol' : 'ul';
      out.push(`<${tag} class="md-list md-list--${ordered ? 'ordered' : 'bullet'}">${items.join('')}</${tag}>`);
      continue;
    }

    // blank line ends a paragraph
    if (!line.trim()) {
      flushParagraph();
      continue;
    }

    paragraph.push(line.trim());
  }

  flushParagraph();

  return { html: out.join('\n'), headings };
}
