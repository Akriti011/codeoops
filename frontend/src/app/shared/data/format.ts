import { HttpErrorResponse } from '@angular/common/http';

/**
 * Display helpers. Each one returns an explicit "unknown" marker rather than a
 * plausible-looking substitute when the backend gave us nothing.
 */

const UNKNOWN = '—';

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return UNKNOWN;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return UNKNOWN;
  return new Intl.DateTimeFormat(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return UNKNOWN;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return UNKNOWN;

  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const abs = Math.abs(seconds);
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });

  if (abs < 60) return rtf.format(Math.round(seconds), 'second');
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), 'minute');
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), 'hour');
  return rtf.format(Math.round(seconds / 86400), 'day');
}

/** Elapsed time between two timestamps, or since `from` when `to` is absent. */
export function formatElapsed(
  from: string | null | undefined,
  to?: string | null | undefined,
): string {
  if (!from) return UNKNOWN;
  const start = new Date(from).getTime();
  if (Number.isNaN(start)) return UNKNOWN;

  const end = to ? new Date(to).getTime() : Date.now();
  if (Number.isNaN(end)) return UNKNOWN;

  return formatDuration(Math.max(0, Math.round((end - start) / 1000)));
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return UNKNOWN;
  const total = Math.max(0, Math.round(seconds));
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  if (mins === 0) return `${secs}s`;
  if (mins < 60) return `${mins}m ${secs}s`;
  const hours = Math.floor(mins / 60);
  return `${hours}h ${mins % 60}m`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return UNKNOWN;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Turns a failed request into something a developer can act on, without
 * inventing a cause. Backend detail is preferred over our own wording.
 */
export function httpErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof HttpErrorResponse) {
    if (error.status === 0) {
      return 'Could not reach the CodeOops API. Check that the backend is running.';
    }
    const body = error.error as
      | { error?: { message?: unknown }; detail?: unknown; message?: unknown }
      | string
      | null;
    if (typeof body === 'string' && body.trim()) return body.trim();
    if (body && typeof body === 'object') {
      // AppError.to_payload() (backend/app/core/errors.py) nests the real
      // message under `error.message` — that shape covers every application
      // error (including ARCHIVE_TOO_LARGE). `detail`/top-level `message`
      // remain as fallbacks for the few routes still using a raw FastAPI
      // HTTPException(detail=...).
      const detail = body.error?.message ?? body.detail ?? body.message;
      if (typeof detail === 'string' && detail.trim()) return detail.trim();
    }
    return `${error.status} ${error.statusText || 'Request failed'}`;
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

export function isNotFound(error: unknown): boolean {
  return error instanceof HttpErrorResponse && error.status === 404;
}

/**
 * True for both ways the backend says "no document exists for this job":
 * `404` (unknown job) and `409` (job known, but has no verified overview yet
 * — see `GET /documentation/jobs/{id}/overview` in the real API). Both mean
 * the same thing to a viewer: there is nothing to render, honestly.
 */
export function isDocumentUnavailable(error: unknown): boolean {
  return error instanceof HttpErrorResponse && (error.status === 404 || error.status === 409);
}

export const TERMINAL_STATUSES = ['COMPLETED', 'FAILED'] as const;

export function isTerminal(status: string | null | undefined): boolean {
  return TERMINAL_STATUSES.includes((status ?? '').toUpperCase() as 'COMPLETED' | 'FAILED');
}
