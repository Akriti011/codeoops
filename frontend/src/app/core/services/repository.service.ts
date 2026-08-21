import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

import { ApiClient, UploadEvent } from '../api/api-client.service';
import {
  CreateRepositoryRequest,
  Repository,
  RepositoryListResponse,
} from '../models/repository.model';
import { DocumentationState } from '../models/documentation.model';

/**
 * Domain service for repositories and their documentation state.
 *
 * Owns every backend path the feature layer needs. Components inject this and
 * never touch `HttpClient` or a URL directly.
 */
@Injectable({ providedIn: 'root' })
export class RepositoryService {
  private readonly api = inject(ApiClient);

  private readonly repositoriesSignal = signal<readonly Repository[]>([]);

  /** Locally cached repositories, newest first. */
  readonly repositories = this.repositoriesSignal.asReadonly();
  readonly repositoryCount = computed(() => this.repositoriesSignal().length);

  /** Submit a repository URL. The backend validates it and owns the identity. */
  createRepository(repositoryUrl: string): Observable<Repository> {
    const body: CreateRepositoryRequest = { repository_url: repositoryUrl };
    return this.api
      .post<Repository, CreateRepositoryRequest>('/repositories', body)
      .pipe(tap((repository) => this.upsert(repository)));
  }

  /**
   * Upload a ZIP archive as a new repository.
   *
   * Emits real browser upload-progress events as the archive is sent, then a
   * single `UploadEvent` carrying the registered repository once the backend
   * has validated, extracted, and registered it — the same
   * validate-then-register contract `POST /repositories/upload` implements
   * server-side. Never emits a synthesized progress value for the
   * validation/extraction step itself; the caller sees "uploading" progress
   * end, then waits for the completion event.
   */
  uploadRepository(file: File): Observable<UploadEvent<Repository>> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    return this.api.postFormData<Repository>('/repositories/upload', formData).pipe(
      tap((event) => {
        if (event.type === 'complete') {
          this.upsert(event.body);
        }
      }),
    );
  }

  listRepositories(): Observable<RepositoryListResponse> {
    return this.api
      .get<RepositoryListResponse>('/repositories')
      .pipe(tap((page) => this.repositoriesSignal.set([...page.items])));
  }

  getRepository(repositoryId: string): Observable<Repository> {
    return this.api
      .get<Repository>(`/repositories/${encodeURIComponent(repositoryId)}`)
      .pipe(tap((repository) => this.upsert(repository)));
  }

  /**
   * Read the documentation state of a repository.
   *
   * Returns whatever the backend reports — including `NOT_GENERATED` with a
   * null artifact. The service never invents a state or a document.
   */
  getDocumentationState(repositoryId: string): Observable<DocumentationState> {
    return this.api.get<DocumentationState>(
      `/repositories/${encodeURIComponent(repositoryId)}/documentation`,
    );
  }

  private upsert(repository: Repository): void {
    const others = this.repositoriesSignal().filter(
      (item) => item.id !== repository.id,
    );
    this.repositoriesSignal.set([repository, ...others]);
  }
}
