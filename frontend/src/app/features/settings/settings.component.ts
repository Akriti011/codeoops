import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';

import { environment } from '../../../environments/environment';
import { isApiError } from '../../core/models/api-error.model';
import { EngineStatus } from '../../core/models/job.model';
import { DocumentationJobService } from '../../core/services/documentation-job.service';
import { HealthResponse, HealthService } from '../../core/services/health.service';
import { AppShellComponent } from '../../shared/layout/app-shell.component';

type ProbeState = 'IDLE' | 'SUBMITTING' | 'READY' | 'FAILED';

@Component({
  selector: 'co-settings',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [AppShellComponent],
  template: `
    <co-app-shell>
      <section class="page">
        <header>
          <p class="co-eyebrow">Settings</p>
          <h1 class="co-h1">Environment</h1>
          <p class="co-lede head__lede">
            Read-only view of how this build is wired. Everything here comes from
            configuration — nothing is editable in the browser.
          </p>
        </header>

        <div class="cards">
          <article class="co-panel card">
            <h2 class="co-h3">API</h2>
            <dl class="facts">
              <div>
                <dt>Base URL</dt>
                <dd class="co-mono">{{ apiBaseUrl }}</dd>
              </div>
              <div>
                <dt>Build</dt>
                <dd>{{ production ? 'production' : 'development' }}</dd>
              </div>
              <div>
                <dt>Frontend version</dt>
                <dd>{{ appVersion }}</dd>
              </div>
            </dl>

            <div class="probe">
              <button
                type="button"
                class="co-btn co-btn--ghost"
                (click)="probe()"
                [disabled]="state() === 'SUBMITTING'"
              >
                {{ state() === 'SUBMITTING' ? 'Checking…' : 'Check API health' }}
              </button>

              <p class="probe__result" role="status">
                @switch (state()) {
                  @case ('READY') {
                    <span class="ok">
                      {{ health()?.service }} {{ health()?.version }} —
                      {{ health()?.status }}
                    </span>
                  }
                  @case ('FAILED') {
                    <span class="bad">{{ probeError() }}</span>
                  }
                  @default {
                    <span class="co-muted">Not checked yet.</span>
                  }
                }
              </p>
            </div>
          </article>

          <article class="co-panel card">
            <h2 class="co-h3">Documentation engine</h2>
            <p class="engine" [class.engine--live]="engine()?.reachable === true">
              <span class="engine__dot" aria-hidden="true"></span>
              @if (engine(); as status) {
                <span>{{ status.engine }} — {{ status.reachable ? 'connected' : 'not reachable' }}</span>
              } @else {
                <span>Checking…</span>
              }
            </p>
            <dl class="facts">
              <div>
                <dt>Base URL</dt>
                <dd class="co-mono">{{ engine()?.base_url ?? '—' }}</dd>
              </div>
            </dl>
            <p class="card__copy">
              CodeOops calls a documentation provider; CodeWiki is the one it
              runs. When the engine is not reachable, every repository
              reports <code class="co-code">NOT_GENERATED</code>.
            </p>
            <p class="card__copy card__copy--rule">
              There is no language model, no Markdown generator and no fallback
              document anywhere in this application. If the engine has not
              produced an artifact, nothing is shown.
            </p>
          </article>

          <article class="co-panel card">
            <h2 class="co-h3">Repository policy</h2>
            <dl class="facts">
              <div>
                <dt>Allowed host</dt>
                <dd class="co-mono">github.com</dd>
              </div>
              <div>
                <dt>Scheme</dt>
                <dd class="co-mono">https</dd>
              </div>
              <div>
                <dt>Accepted form</dt>
                <dd class="co-mono">https://github.com/owner/repository</dd>
              </div>
            </dl>
            <p class="card__copy">
              The backend is the authority: it re-validates every submission and
              rejects credentials, ports and non-repository paths.
            </p>
          </article>
        </div>
      </section>
    </co-app-shell>
  `,
  styles: `
    .page {
      display: grid;
      gap: clamp(1.25rem, 2.4vw, 2rem);
      padding-block: 0.5rem 2rem;
    }

    .head__lede {
      margin-top: 0.5rem;
      max-width: 56ch;
    }

    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(19rem, 1fr));
      gap: 1rem;
      align-items: start;
    }

    .card {
      padding: clamp(1.15rem, 2vw, 1.6rem);
      display: grid;
      gap: 0.9rem;
      align-content: start;
    }

    .facts {
      display: grid;
      gap: 0.75rem;

      dt {
        font-size: 0.66rem;
        letter-spacing: 0.13em;
        text-transform: uppercase;
        color: var(--co-text-tertiary);
      }

      dd {
        margin: 0.2rem 0 0;
        font-size: 0.88rem;
        color: var(--co-text-secondary);
        overflow-wrap: anywhere;
      }
    }

    .probe {
      display: grid;
      gap: 0.6rem;
      justify-items: start;
      padding-top: 0.9rem;
      border-top: 1px solid var(--co-border);
    }

    .probe__result {
      font-size: 0.86rem;
    }

    .ok {
      color: var(--co-success);
    }

    .bad {
      color: var(--co-danger);
    }

    .engine {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-weight: 620;
      font-size: 0.94rem;
      color: var(--co-text-secondary);
    }

    .engine__dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--co-neutral);
      flex: none;
    }

    .engine--live .engine__dot {
      background: var(--co-success);
    }

    .card__copy {
      font-size: 0.88rem;
      line-height: 1.6;
      color: var(--co-text-secondary);
    }

    .card__copy--rule {
      padding: 0.7rem 0.9rem;
      border-radius: var(--co-radius-sm);
      border: 1px solid var(--co-border);
      background: var(--co-bg-subtle);
      font-size: 0.82rem;
    }
  `,
})
export class SettingsComponent {
  private readonly healthService = inject(HealthService);
  private readonly jobService = inject(DocumentationJobService);

  protected readonly apiBaseUrl = environment.apiBaseUrl;
  protected readonly production = environment.production;
  protected readonly appVersion = environment.appVersion;

  protected readonly state = signal<ProbeState>('IDLE');
  protected readonly health = signal<HealthResponse | null>(null);
  protected readonly probeError = signal<string>('');
  protected readonly engine = signal<EngineStatus | null>(null);

  constructor() {
    this.jobService.probeEngine().subscribe({
      next: (status) => this.engine.set(status),
      error: () => this.engine.set(null),
    });
  }

  protected probe(): void {
    this.state.set('SUBMITTING');
    this.healthService.check().subscribe({
      next: (response) => {
        this.health.set(response);
        this.state.set('READY');
      },
      error: (error: unknown) => {
        this.probeError.set(
          isApiError(error) ? error.message : 'Health check failed.',
        );
        this.state.set('FAILED');
      },
    });
  }
}
