import { HttpErrorResponse, provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { apiErrorInterceptor } from '../api/api-error.interceptor';
import { API_BASE_URL } from '../api/api.config';
import { ApiError } from '../models/api-error.model';
import { DocumentationState } from '../models/documentation.model';
import { Repository } from '../models/repository.model';
import { RepositoryService } from './repository.service';

const BASE = 'http://test.local/api/v1';

const REPOSITORY: Repository = {
  id: '11111111-1111-4111-8111-111111111111',
  owner: 'octocat',
  name: 'Hello-World',
  repository_url: 'https://github.com/octocat/Hello-World',
  default_branch: 'main',
  status: 'READY',
  created_at: '2026-08-14T10:00:00Z',
  updated_at: '2026-08-14T10:00:00Z',
};

describe('RepositoryService', () => {
  let service: RepositoryService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([apiErrorInterceptor])),
        provideHttpClientTesting(),
        { provide: API_BASE_URL, useValue: BASE },
      ],
    });

    service = TestBed.inject(RepositoryService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('POSTs the repository URL to the configured API', () => {
    let received: Repository | undefined;
    service
      .createRepository('https://github.com/octocat/Hello-World')
      .subscribe((repository) => (received = repository));

    const request = http.expectOne(`${BASE}/repositories`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({
      repository_url: 'https://github.com/octocat/Hello-World',
    });

    request.flush(REPOSITORY);
    expect(received).toEqual(REPOSITORY);
  });

  it('caches a created repository in its signal', () => {
    service.createRepository(REPOSITORY.repository_url).subscribe();
    http.expectOne(`${BASE}/repositories`).flush(REPOSITORY);

    expect(service.repositoryCount()).toBe(1);
    expect(service.repositories()[0].id).toBe(REPOSITORY.id);
  });

  it('lists repositories', () => {
    service.listRepositories().subscribe();

    const request = http.expectOne(`${BASE}/repositories`);
    expect(request.request.method).toBe('GET');
    request.flush({ items: [REPOSITORY], total: 1 });

    expect(service.repositories().length).toBe(1);
  });

  it('fetches a single repository by id', () => {
    service.getRepository(REPOSITORY.id).subscribe();

    const request = http.expectOne(`${BASE}/repositories/${REPOSITORY.id}`);
    expect(request.request.method).toBe('GET');
    request.flush(REPOSITORY);
  });

  it('reads documentation state without inventing content', () => {
    const expected: DocumentationState = {
      repository_id: REPOSITORY.id,
      status: 'NOT_GENERATED',
      artifact: null,
      detail: 'No documentation provider is connected.',
    };

    let received: DocumentationState | undefined;
    service
      .getDocumentationState(REPOSITORY.id)
      .subscribe((state) => (received = state));

    http
      .expectOne(`${BASE}/repositories/${REPOSITORY.id}/documentation`)
      .flush(expected);

    expect(received).toEqual(expected);
    expect(received?.artifact).toBeNull();
  });

  it('surfaces a backend validation error as a typed ApiError', () => {
    let error: ApiError | undefined;
    service.createRepository('https://gitlab.com/a/b').subscribe({
      error: (caught: ApiError) => (error = caught),
    });

    http.expectOne(`${BASE}/repositories`).flush(
      {
        error: {
          code: 'INVALID_REPOSITORY_URL',
          message: 'Only repositories hosted on github.com are supported.',
          details: { host: 'gitlab.com' },
        },
      },
      { status: 422, statusText: 'Unprocessable Entity' },
    );

    expect(error?.code).toBe('INVALID_REPOSITORY_URL');
    expect(error?.status).toBe(422);
    expect(error?.offline).toBeFalse();
  });

  it('reports an unreachable backend distinctly', () => {
    let error: ApiError | undefined;
    service.listRepositories().subscribe({
      error: (caught: ApiError) => (error = caught),
    });

    http
      .expectOne(`${BASE}/repositories`)
      .error(new ProgressEvent('error'), { status: 0, statusText: '' });

    expect(error?.code).toBe('BACKEND_UNAVAILABLE');
    expect(error?.offline).toBeTrue();
  });

  it('never receives an HttpErrorResponse directly', () => {
    let error: unknown;
    service.getRepository('missing').subscribe({ error: (e) => (error = e) });

    http
      .expectOne(`${BASE}/repositories/missing`)
      .flush(null, { status: 500, statusText: 'Server Error' });

    expect(error instanceof HttpErrorResponse).toBeFalse();
  });
});
