import { InjectionToken } from '@angular/core';

/**
 * Base URL of the CodeOops API, including the version prefix.
 *
 * Provided once in `app.config.ts` from the environment file. Nothing else in
 * the application may read an origin from anywhere else.
 */
export const API_BASE_URL = new InjectionToken<string>('CODEOOPS_API_BASE_URL');
