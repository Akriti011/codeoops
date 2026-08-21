import { HttpClient, HttpEventType } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, filter, map } from 'rxjs';

import { API_BASE_URL } from './api.config';

/** Real upload progress, sourced only from the browser's own byte counters. */
export interface UploadProgress {
  readonly type: 'progress';
  readonly loaded: number;
  readonly total: number | null;
}

export interface UploadComplete<T> {
  readonly type: 'complete';
  readonly body: T;
}

export type UploadEvent<T> = UploadProgress | UploadComplete<T>;

/**
 * The single place in the frontend that turns a path into a backend URL.
 *
 * Feature code calls domain services (e.g. `RepositoryService`); those services
 * call this. No component ever concatenates a backend URL.
 */
@Injectable({ providedIn: 'root' })
export class ApiClient {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);

  get<T>(path: string): Observable<T> {
    return this.http.get<T>(this.url(path));
  }

  post<TResponse, TBody>(path: string, body: TBody): Observable<TResponse> {
    return this.http.post<TResponse>(this.url(path), body);
  }

  /**
   * POST a `FormData` body, emitting real browser upload-progress events as
   * they occur, then a single completion event carrying the parsed response.
   * Never emits a synthesized/interpolated progress value.
   */
  postFormData<T>(path: string, formData: FormData): Observable<UploadEvent<T>> {
    return this.http
      .post<T>(this.url(path), formData, { reportProgress: true, observe: 'events' })
      .pipe(
        filter(
          (event) =>
            event.type === HttpEventType.UploadProgress || event.type === HttpEventType.Response,
        ),
        map((event): UploadEvent<T> => {
          if (event.type === HttpEventType.UploadProgress) {
            return { type: 'progress', loaded: event.loaded, total: event.total ?? null };
          }
          // event.type === HttpEventType.Response, guaranteed by the filter above.
          return { type: 'complete', body: (event as { body: T }).body };
        }),
      );
  }

  /** For endpoints that return a raw body (e.g. `text/markdown`), not JSON. */
  getText(path: string): Observable<string> {
    return this.http.get(this.url(path), { responseType: 'text' });
  }

  /** The fully-qualified backend URL for `path` — for building an `<a href>`. */
  buildUrl(path: string): string {
    return this.url(path);
  }

  private url(path: string): string {
    const base = this.baseUrl.replace(/\/+$/, '');
    const suffix = path.startsWith('/') ? path : `/${path}`;
    return `${base}${suffix}`;
  }
}
