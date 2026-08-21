/**
 * Production environment.
 *
 * `apiBaseUrl` is the only place a backend origin appears in the frontend.
 * Components and features never build backend URLs; they go through
 * `ApiClient`, which is the sole consumer of this value.
 */
export const environment = {
  production: true,
  apiBaseUrl: '/api/v1',
  appVersion: '0.1.0',
} as const;
