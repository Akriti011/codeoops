/** Normalised API error, produced by the HTTP error interceptor. */
export interface ApiError {
  /** HTTP status, or 0 when the request never reached the backend. */
  readonly status: number;
  /** Stable machine-readable code from the backend, or a client-side code. */
  readonly code: string;
  /** Message safe to show a user. */
  readonly message: string;
  readonly details: Readonly<Record<string, unknown>>;
  /** True when the backend could not be reached at all. */
  readonly offline: boolean;
}

export function isApiError(value: unknown): value is ApiError {
  return (
    typeof value === 'object' &&
    value !== null &&
    'code' in value &&
    'message' in value &&
    'offline' in value
  );
}
