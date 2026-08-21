"""Export CodeWiki's overview.md to PDF and CSV.

Confined here so no other module knows the export mechanics: Markdown to HTML
(``markdown``), HTML to PDF (``xhtml2pdf``) — both pure Python, no system
binaries. Mermaid fences render as formatted code blocks in the PDF (the same
``fenced_code`` extension used for every other code block in the document);
the web viewer already renders them as real diagrams via the frontend's
mermaid package, so the PDF's code-block fallback only affects that one
export path. This module only reformats bytes CodeWiki already produced; it
never generates, edits, or summarizes documentation content.
"""

from __future__ import annotations

import csv
import io

import markdown as markdown_lib
from xhtml2pdf import pisa

from app.core.errors import AppError

_PDF_STYLE = """
<style>
body { font-family: Helvetica, Arial, sans-serif; font-size: 10pt; line-height: 1.45; }
h1 { font-size: 18pt; }
h2 { font-size: 14pt; margin-top: 1.2em; }
h3 { font-size: 12pt; }
code, pre { font-family: Courier, monospace; font-size: 8pt; background-color: #f4f4f4; }
pre { padding: 6px; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #ccc; padding: 4px 8px; font-size: 9pt; }
img { max-width: 100%; }
</style>
"""


class PdfRenderingError(AppError):
    """xhtml2pdf failed to render the assembled HTML to PDF."""

    status_code = 500
    code = "PDF_RENDERING_FAILED"


def render_pdf(markdown_text: str) -> bytes:
    """Render overview markdown to PDF bytes."""
    html_body = markdown_lib.markdown(markdown_text, extensions=["fenced_code", "tables"])
    full_html = f"<html><head>{_PDF_STYLE}</head><body>{html_body}</body></html>"

    buffer = io.BytesIO()
    result = pisa.CreatePDF(src=full_html, dest=buffer)
    if result.err:
        raise PdfRenderingError(
            "Failed to render the overview to PDF.", details={"pisa_err": result.err}
        )
    return buffer.getvalue()


def render_csv(markdown_text: str) -> bytes:
    """Structured export: one row per top-level (``## ``) section.

    A CSV can never substitute for the Markdown/PDF report — it's a flat
    section/content table for spreadsheet consumers, nothing more.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["section", "content"])
    for title, content in _split_sections(markdown_text):
        writer.writerow([title, content])
    return buffer.getvalue().encode("utf-8")


def _split_sections(markdown_text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_title = "Preamble"
    current_lines: list[str] = []
    for line in markdown_text.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))
    return [(title, content) for title, content in sections if content]
