import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { ApiError, isApiError } from '../../core/models/api-error.model';
import { Repository } from '../../core/models/repository.model';
import { WorkflowState } from '../../core/models/workflow-state';
import { FileSizePipe } from '../../core/pipes/file-size.pipe';
import { RepositoryService } from '../../core/services/repository.service';
import { ToastService } from '../../core/services/toast.service';
import { checkRepositoryUrl } from '../../core/validation/repository-url';
import { StatusPillComponent } from '../../shared/ui/status-pill.component';

type SourceMode = 'GITHUB' | 'UPLOAD';

const ZIP_MIME_TYPES = new Set([
  'application/zip',
  'application/x-zip-compressed',
  'application/x-zip',
]);

/**
 * Repository intake: a GitHub URL, or a ZIP archive upload.
 *
 * Either mode only registers the repository with the backend. It does **not**
 * start documentation generation — that stays a separate, explicit step
 * (the workspace's "Generate Documentation" button) regardless of how the
 * repository's source arrived.
 */
@Component({
  selector: 'co-repository-submit-form',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, StatusPillComponent, FileSizePipe],
  template: `
    <div class="tabs" role="tablist" aria-label="Repository source">
      <button
        type="button"
        role="tab"
        class="tab"
        [class.tab--active]="mode() === 'GITHUB'"
        [attr.aria-selected]="mode() === 'GITHUB'"
        (click)="setMode('GITHUB')"
      >
        GitHub Repository
      </button>
      <button
        type="button"
        role="tab"
        class="tab"
        [class.tab--active]="mode() === 'UPLOAD'"
        [attr.aria-selected]="mode() === 'UPLOAD'"
        (click)="setMode('UPLOAD')"
      >
        Upload ZIP
      </button>
    </div>

    @if (mode() === 'GITHUB') {
      <form class="form" (ngSubmit)="submit()" novalidate>
        <div class="row">
          <div class="co-field field">
            <label class="co-label" [attr.for]="inputId"> GitHub repository URL </label>
            <input
              [id]="inputId"
              class="co-input"
              type="url"
              name="repositoryUrl"
              inputmode="url"
              autocomplete="off"
              spellcheck="false"
              placeholder="https://github.com/owner/repository"
              [ngModel]="url()"
              (ngModelChange)="onUrlChange($event)"
              [attr.aria-invalid]="showInlineError() ? 'true' : null"
              [attr.aria-describedby]="describedBy()"
              [disabled]="state() === 'SUBMITTING'"
            />
          </div>

          <button
            type="submit"
            class="co-btn co-btn--primary submit"
            [disabled]="state() === 'SUBMITTING'"
          >
            @if (state() === 'SUBMITTING') {
              <span class="spinner" aria-hidden="true"></span>
              Submitting…
            } @else {
              Generate Documentation
              <svg viewBox="0 0 16 16" aria-hidden="true" class="arrow">
                <path
                  d="M3 8h9M8.5 4.5 12 8l-3.5 3.5"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.6"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            }
          </button>
        </div>

        <div class="feedback">
          @if (showInlineError()) {
            <p class="co-error-text" [id]="errorId" role="alert">
              <svg viewBox="0 0 16 16" aria-hidden="true" class="icon">
                <circle cx="8" cy="8" r="6.4" fill="none" stroke="currentColor" stroke-width="1.4" />
                <path d="M8 4.8v4M8 11.2h.01" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
              </svg>
              {{ inlineError() }}
            </p>
          } @else {
            <p class="co-help" [id]="helpId">
              Public GitHub repositories, e.g.
              <code class="co-code">https://github.com/owner/repository</code>
            </p>
          }

          <span class="state">
            <span class="sr-only">Current state:</span>
            <co-status-pill [state]="state()" />
          </span>
        </div>

        @if (state() === 'READY') {
          <p class="notice" role="status">
            Repository registered. Documentation generation starts once you click Generate.
          </p>
        }
      </form>
    } @else {
      <form class="form" (ngSubmit)="submitUpload()" novalidate>
        <div
          class="dropzone"
          [class.dropzone--active]="dragActive()"
          [class.dropzone--has-file]="selectedFile() !== null"
          [attr.aria-disabled]="uploadState() === 'SUBMITTING' ? 'true' : null"
          (dragover)="onDragOver($event)"
          (dragleave)="onDragLeave($event)"
          (drop)="onDrop($event)"
          (click)="uploadState() !== 'SUBMITTING' && fileInputRef().nativeElement.click()"
        >
          <input
            #fileInput
            type="file"
            accept=".zip,application/zip,application/x-zip-compressed"
            class="sr-only"
            [attr.aria-describedby]="uploadHelpId"
            (change)="onFileSelected($event)"
            [disabled]="uploadState() === 'SUBMITTING'"
          />

          @if (selectedFile(); as file) {
            <div class="file-info">
              <svg viewBox="0 0 16 16" aria-hidden="true" class="file-icon">
                <path
                  d="M4 1.5h5.5L12.5 4.5V14.5H4z"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.3"
                  stroke-linejoin="round"
                />
                <path d="M9.5 1.5V4.5H12.5" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round" />
              </svg>
              <span class="file-name">{{ file.name }}</span>
              <span class="file-size">{{ file.size | fileSize }}</span>
            </div>
          } @else {
            <p class="dropzone-hint">Drop a ZIP file here, or click to browse.</p>
          }
        </div>

        @if (uploadProgressPercent(); as percent) {
          <div
            class="progress-track"
            role="progressbar"
            [attr.aria-valuenow]="percent"
            aria-valuemin="0"
            aria-valuemax="100"
            aria-label="Upload progress"
          >
            <div class="progress-fill" [style.width.%]="percent"></div>
          </div>
        }

        <div class="row">
          <button
            type="submit"
            class="co-btn co-btn--primary submit"
            [disabled]="selectedFile() === null || uploadState() === 'SUBMITTING'"
          >
            @if (uploadState() === 'SUBMITTING') {
              <span class="spinner" aria-hidden="true"></span>
              {{ uploadStatusLabel() }}
            } @else {
              Upload and Register
              <svg viewBox="0 0 16 16" aria-hidden="true" class="arrow">
                <path
                  d="M3 8h9M8.5 4.5 12 8l-3.5 3.5"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.6"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            }
          </button>
        </div>

        <div class="feedback">
          @if (showUploadInlineError()) {
            <p class="co-error-text" role="alert">
              <svg viewBox="0 0 16 16" aria-hidden="true" class="icon">
                <circle cx="8" cy="8" r="6.4" fill="none" stroke="currentColor" stroke-width="1.4" />
                <path d="M8 4.8v4M8 11.2h.01" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
              </svg>
              {{ uploadInlineError() }}
            </p>
          } @else {
            <p class="co-help" [id]="uploadHelpId">
              ZIP archives only. Files at the root or inside a single project folder are
              both supported.
            </p>
          }

          <span class="state">
            <span class="sr-only">Current state:</span>
            <co-status-pill [state]="uploadState()" />
          </span>
        </div>

        @if (uploadState() === 'READY') {
          <p class="notice" role="status">
            Repository registered from the archive. Documentation generation starts once
            you click Generate.
          </p>
        }
      </form>
    }
  `,
  styles: `
    :host {
      display: block;
    }

    .tabs {
      display: flex;
      gap: 0.4rem;
      margin-bottom: 0.9rem;
      border-bottom: 1px solid var(--co-border);
    }

    .tab {
      appearance: none;
      border: none;
      background: none;
      cursor: pointer;
      padding: 0.6rem 0.2rem;
      margin-bottom: -1px;
      font: inherit;
      font-size: 0.86rem;
      font-weight: 600;
      color: var(--co-text-tertiary);
      border-bottom: 2px solid transparent;
      transition:
        color var(--co-micro) var(--co-ease-out),
        border-color var(--co-micro) var(--co-ease-out);
    }

    .tab + .tab {
      margin-left: 1.1rem;
    }

    .tab:hover {
      color: var(--co-text);
    }

    .tab--active {
      color: var(--co-red-600);
      border-bottom-color: var(--co-red-500);
    }

    .form {
      display: grid;
      gap: 0.85rem;
    }

    .row {
      display: flex;
      gap: 0.75rem;
      align-items: flex-end;
      flex-wrap: wrap;
    }

    .field {
      flex: 1 1 22rem;
      min-width: 0;
    }

    .submit {
      flex: none;
      padding-block: 0.95rem;
      height: 3.25rem;
    }

    .arrow {
      width: 15px;
      height: 15px;
      transition: transform var(--co-micro) var(--co-ease-out);
    }

    .submit:not(:disabled):hover .arrow {
      transform: translateX(3px);
    }

    .spinner {
      width: 15px;
      height: 15px;
      border-radius: 50%;
      border: 2px solid rgba(255, 255, 255, 0.35);
      border-top-color: #fff;
      flex: none;
    }

    @media (prefers-reduced-motion: no-preference) {
      .spinner {
        animation: spin 700ms linear infinite;
      }
    }

    @keyframes spin {
      to {
        transform: rotate(360deg);
      }
    }

    .feedback {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      flex-wrap: wrap;
    }

    .icon {
      width: 15px;
      height: 15px;
      flex: none;
    }

    .notice {
      font-size: 0.86rem;
      line-height: 1.5;
      color: var(--co-success);
      padding: 0.7rem 0.9rem;
      border-radius: var(--co-radius-sm);
      border: 1px solid var(--co-success-border);
      background: var(--co-success-bg);
    }

    .dropzone {
      display: grid;
      place-items: center;
      gap: 0.4rem;
      min-height: 6rem;
      padding: 1.25rem;
      border-radius: var(--co-radius);
      border: 1.5px dashed var(--co-border-strong);
      background: var(--co-bg-subtle);
      cursor: pointer;
      text-align: center;
      transition:
        border-color var(--co-micro) var(--co-ease-out),
        background var(--co-micro) var(--co-ease-out);
    }

    .dropzone:hover,
    .dropzone--active {
      border-color: var(--co-red-500);
      background: var(--co-red-50);
    }

    .dropzone--has-file {
      border-style: solid;
      cursor: default;
    }

    .dropzone[aria-disabled='true'] {
      cursor: not-allowed;
      opacity: 0.6;
    }

    .dropzone-hint {
      font-size: 0.88rem;
      color: var(--co-text-secondary);
      margin: 0;
    }

    .file-info {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      font-size: 0.9rem;
      color: var(--co-text);
      max-width: 100%;
    }

    .file-icon {
      width: 20px;
      height: 20px;
      flex: none;
      color: var(--co-red-500);
    }

    .file-name {
      font-weight: 600;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-width: 24rem;
    }

    .file-size {
      color: var(--co-text-tertiary);
      font-variant-numeric: tabular-nums;
    }

    .progress-track {
      height: 6px;
      border-radius: 999px;
      background: var(--co-border);
      overflow: hidden;
    }

    .progress-fill {
      height: 100%;
      background: var(--co-red-500);
      border-radius: inherit;
      transition: width 120ms linear;
    }

    @media (max-width: 620px) {
      .submit {
        width: 100%;
      }

      .file-name {
        max-width: 12rem;
      }
    }
  `,
})
export class RepositorySubmitFormComponent {
  /** Navigate to the workspace for the repository after a successful submit. */
  readonly navigateOnSuccess = input(true);

  readonly submitted = output<Repository>();

  private readonly repositories = inject(RepositoryService);
  private readonly toasts = inject(ToastService);
  private readonly router = inject(Router);

  private readonly uid = Math.random().toString(36).slice(2, 8);
  protected readonly inputId = `repo-url-${this.uid}`;
  protected readonly helpId = `repo-help-${this.uid}`;
  protected readonly errorId = `repo-error-${this.uid}`;
  protected readonly uploadHelpId = `repo-upload-help-${this.uid}`;

  protected readonly mode = signal<SourceMode>('GITHUB');

  // --- GitHub URL mode ---------------------------------------------------

  protected readonly url = signal('');
  protected readonly state = signal<WorkflowState>('IDLE');
  protected readonly inlineError = signal<string | null>(null);

  protected readonly showInlineError = computed(() => this.inlineError() !== null);
  protected readonly describedBy = computed(() =>
    this.showInlineError() ? this.errorId : this.helpId,
  );

  // --- ZIP upload mode -----------------------------------------------------

  protected readonly fileInputRef = viewChild.required<ElementRef<HTMLInputElement>>('fileInput');

  protected readonly selectedFile = signal<File | null>(null);
  protected readonly uploadState = signal<WorkflowState>('IDLE');
  protected readonly uploadInlineError = signal<string | null>(null);
  protected readonly dragActive = signal(false);
  /** Bytes sent so far during the upload phase; null once uploading has ended
   * (either not started yet, or the browser has finished sending and the
   * backend is now validating/extracting — a phase with no progress signal
   * of its own, so none is shown rather than faked). */
  private readonly uploadedBytes = signal<{ loaded: number; total: number | null } | null>(null);

  protected readonly showUploadInlineError = computed(() => this.uploadInlineError() !== null);

  protected readonly uploadProgressPercent = computed(() => {
    const progress = this.uploadedBytes();
    if (!progress || !progress.total) {
      return null;
    }
    return Math.min(100, Math.round((progress.loaded / progress.total) * 100));
  });

  protected readonly uploadStatusLabel = computed(() => {
    const percent = this.uploadProgressPercent();
    if (percent === null || percent >= 100) {
      return 'Validating…';
    }
    return `Uploading… ${percent}%`;
  });

  protected setMode(mode: SourceMode): void {
    if (this.mode() === mode) {
      return;
    }
    this.mode.set(mode);
  }

  protected onUrlChange(value: string): void {
    this.url.set(value);
    if (this.inlineError() !== null) {
      this.inlineError.set(null);
    }
    if (this.state() === 'FAILED' || this.state() === 'READY') {
      this.state.set('IDLE');
    }
  }

  protected submit(): void {
    if (this.state() === 'SUBMITTING') {
      return;
    }

    const value = this.url().trim();
    const check = checkRepositoryUrl(value);
    if (!check.valid) {
      this.inlineError.set(check.message ?? 'Enter a valid repository URL.');
      this.state.set('FAILED');
      return;
    }

    this.inlineError.set(null);
    this.state.set('SUBMITTING');

    this.repositories.createRepository(value).subscribe({
      next: (repository) => {
        this.state.set('READY');
        this.toasts.success(
          'Repository registered',
          `${repository.owner}/${repository.name} is ready in your workspace.`,
        );
        this.submitted.emit(repository);
        if (this.navigateOnSuccess()) {
          void this.router.navigate(['/documentation', repository.id]);
        }
      },
      error: (error: unknown) => {
        this.state.set('FAILED');
        const apiError = this.describe(error);
        this.inlineError.set(apiError.message);
        this.toasts.error(
          apiError.offline ? 'Backend unavailable' : 'Could not register repository',
          apiError.message,
        );
      },
    });
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
    if (this.uploadState() !== 'SUBMITTING') {
      this.dragActive.set(true);
    }
  }

  protected onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.dragActive.set(false);
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragActive.set(false);
    if (this.uploadState() === 'SUBMITTING') {
      return;
    }
    const file = event.dataTransfer?.files?.[0];
    if (file) {
      this.selectFile(file);
    }
  }

  protected onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) {
      this.selectFile(file);
    }
    input.value = '';
  }

  private selectFile(file: File): void {
    const looksLikeZip =
      file.name.toLowerCase().endsWith('.zip') || ZIP_MIME_TYPES.has(file.type);
    if (!looksLikeZip) {
      this.uploadInlineError.set('Choose a .zip archive.');
      this.uploadState.set('FAILED');
      return;
    }
    this.selectedFile.set(file);
    this.uploadInlineError.set(null);
    this.uploadedBytes.set(null);
    this.uploadState.set('IDLE');
  }

  protected submitUpload(): void {
    const file = this.selectedFile();
    if (!file || this.uploadState() === 'SUBMITTING') {
      return;
    }

    this.uploadInlineError.set(null);
    this.uploadedBytes.set(null);
    this.uploadState.set('SUBMITTING');

    this.repositories.uploadRepository(file).subscribe({
      next: (event) => {
        if (event.type === 'progress') {
          this.uploadedBytes.set({ loaded: event.loaded, total: event.total });
          return;
        }
        const repository = event.body;
        this.uploadState.set('READY');
        this.toasts.success(
          'Repository registered',
          `${repository.name} is ready in your workspace.`,
        );
        this.submitted.emit(repository);
        if (this.navigateOnSuccess()) {
          void this.router.navigate(['/documentation', repository.id]);
        }
      },
      error: (error: unknown) => {
        this.uploadState.set('FAILED');
        const apiError = this.describe(error);
        this.uploadInlineError.set(apiError.message);
        this.toasts.error(
          apiError.offline ? 'Backend unavailable' : 'Could not upload repository',
          apiError.message,
        );
      },
    });
  }

  private describe(error: unknown): ApiError {
    if (isApiError(error)) {
      return error;
    }
    return {
      status: 0,
      code: 'UNEXPECTED_ERROR',
      message: 'Unexpected error. Check the browser console for details.',
      details: {},
      offline: false,
    };
  }
}
