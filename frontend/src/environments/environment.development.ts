/**
 * Development environment.
 *
 * Points at the local FastAPI server. The backend must allow this origin via
 * its `ALLOWED_ORIGINS` setting (defaults to http://localhost:4200).
 */
export const environment = {
  production: false,
  apiBaseUrl: 'http://127.0.0.1:8000/api/v1',
  appVersion: '0.1.0',
} as const;
