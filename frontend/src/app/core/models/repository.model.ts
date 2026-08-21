/** Wire contract for repositories, mirroring the FastAPI schemas. */

export type RepositoryStatus = 'READY' | 'GENERATING' | 'COMPLETED' | 'FAILED';

/** How a repository's source code reached CodeOops. */
export type RepositorySource = 'GITHUB' | 'UPLOAD';

export interface Repository {
  readonly id: string;
  readonly owner: string;
  readonly name: string;
  readonly repository_url: string;
  readonly default_branch: string;
  readonly source: RepositorySource;
  readonly upload_original_filename: string | null;
  readonly upload_file_count: number | null;
  readonly upload_total_bytes: number | null;
  readonly status: RepositoryStatus;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface RepositoryListResponse {
  readonly items: readonly Repository[];
  readonly total: number;
}

export interface CreateRepositoryRequest {
  readonly repository_url: string;
}

export function repositoryFullName(repository: Repository): string {
  return `${repository.owner}/${repository.name}`;
}
