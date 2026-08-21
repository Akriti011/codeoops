import { HttpErrorResponse } from '@angular/common/http';

import { toApiError } from './api-error.interceptor';

describe('toApiError', () => {
  it('maps a status 0 response to BACKEND_UNAVAILABLE', () => {
    const error = toApiError(
      new HttpErrorResponse({ status: 0, statusText: 'Unknown Error' }),
    );

    expect(error.code).toBe('BACKEND_UNAVAILABLE');
    expect(error.offline).toBeTrue();
  });

  it('unwraps the backend error envelope', () => {
    const error = toApiError(
      new HttpErrorResponse({
        status: 404,
        error: {
          error: {
            code: 'REPOSITORY_NOT_FOUND',
            message: 'No repository with that id.',
            details: { repository_id: 'abc' },
          },
        },
      }),
    );

    expect(error.code).toBe('REPOSITORY_NOT_FOUND');
    expect(error.message).toBe('No repository with that id.');
    expect(error.details['repository_id']).toBe('abc');
    expect(error.offline).toBeFalse();
  });

  it('falls back for responses without an envelope', () => {
    const error = toApiError(
      new HttpErrorResponse({
        status: 500,
        statusText: 'Internal Server Error',
        error: 'boom',
      }),
    );

    expect(error.code).toBe('API_ERROR');
    expect(error.status).toBe(500);
  });

  it('handles non-HTTP errors', () => {
    expect(toApiError(new Error('nope')).code).toBe('UNEXPECTED_ERROR');
  });
});
