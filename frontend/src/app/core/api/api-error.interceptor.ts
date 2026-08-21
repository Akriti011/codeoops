import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { catchError, throwError } from 'rxjs';

import { ApiError } from '../models/api-error.model';

interface BackendErrorBody {
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
  };
}

const GENERIC_MESSAGE = 'Something went wrong talking to the CodeOops API.';

/**
 * Turns every HTTP failure into a typed {@link ApiError}.
 *
 * Errors are never swallowed here — they are normalised and re-thrown so the
 * calling feature decides how to surface them.
 */
export const apiErrorInterceptor: HttpInterceptorFn = (request, next) =>
  next(request).pipe(
    catchError((error: unknown) => throwError(() => toApiError(error))),
  );

export function toApiError(error: unknown): ApiError {
  if (!(error instanceof HttpErrorResponse)) {
    return {
      status: 0,
      code: 'UNEXPECTED_ERROR',
      message: GENERIC_MESSAGE,
      details: {},
      offline: false,
    };
  }

  // status 0 means the request never reached the server (server down, DNS,
  // blocked by CORS preflight, offline).
  if (error.status === 0) {
    return {
      status: 0,
      code: 'BACKEND_UNAVAILABLE',
      message:
        'Cannot reach the CodeOops API. Check that the backend is running on ' +
        'the configured address.',
      details: {},
      offline: true,
    };
  }

  const body = parseErrorBody(error.error);

  if (body && typeof body === 'object' && body.error) {
    return {
      status: error.status,
      code: body.error.code ?? 'API_ERROR',
      message: body.error.message ?? GENERIC_MESSAGE,
      details: body.error.details ?? {},
      offline: false,
    };
  }

  return {
    status: error.status,
    code: 'API_ERROR',
    message: error.statusText || GENERIC_MESSAGE,
    details: {},
    offline: false,
  };
}

/**
 * Requests made with `responseType: 'text'` (e.g. fetching a raw Markdown
 * document) still receive a JSON error envelope on failure, but Angular
 * delivers it as an unparsed string rather than an object — parse it here so
 * the envelope-unwrapping branch above still applies.
 */
function parseErrorBody(raw: unknown): BackendErrorBody | string | null {
  if (typeof raw !== 'string') {
    return raw as BackendErrorBody | string | null;
  }
  try {
    return JSON.parse(raw) as BackendErrorBody;
  } catch {
    return raw;
  }
}
