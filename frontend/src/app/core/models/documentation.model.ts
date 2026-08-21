/**
 * Wire contract for documentation state.
 *
 * `artifact` is null until a documentation provider (CodeWiki) has produced a
 * verified artifact. The UI must render an explicit empty state when it is
 * null — never substitute or placeholder document content.
 */

export type DocumentationStatus =
  | 'NOT_GENERATED'
  | 'QUEUED'
  | 'GENERATING'
  | 'COMPLETED'
  | 'FAILED';

export interface DocumentationArtifact {
  readonly id: string;
  readonly repository_id: string;
  readonly entry_document: string;
  readonly generated_at: string;
  readonly provider: string;
}

export interface DocumentationState {
  readonly repository_id: string;
  readonly status: DocumentationStatus;
  readonly artifact: DocumentationArtifact | null;
  readonly detail: string | null;
}
