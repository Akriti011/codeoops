import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

import { IconComponent, IconName } from '../../shared/ui/icon.component';
import { IconTileComponent, TileTone } from '../../shared/ui/icon-tile.component';
import { LogoComponent } from '../../shared/ui/logo.component';

interface Capability {
  icon: IconName;
  tone: TileTone;
  title: string;
  text: string;
}

/**
 * Public entry page, outside the application shell.
 *
 * It describes what the platform does. It shows no counters, no repository
 * names and no sample documents — nothing on this page pretends to be data.
 */
@Component({
  selector: 'co-landing',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LogoComponent, IconComponent, IconTileComponent],
  template: `
    <div class="landing">
      <header class="nav">
        <div class="nav__inner">
          <co-logo size="md" tagline="Developer platform" />
          <nav class="nav__links" aria-label="Primary">
            <a href="#capabilities">Capabilities</a>
            <a href="#pipeline">How it works</a>
          </nav>
          <a class="btn btn--primary btn--sm" routerLink="/dashboard">
            <span>Open console</span>
            <co-icon name="arrow-right" />
          </a>
        </div>
      </header>

      <!-- ---------------- hero ---------------- -->
      <section class="hero">
        <div class="hero__inner">
          <p class="eyebrow">
            <span class="eyebrow__dot" aria-hidden="true"></span>
            Powered by the CodeWiki engine
          </p>

          <h1 class="t-display hero__title">
            Repository documentation,<br />
            <span class="hero__accent">generated from the code itself.</span>
          </h1>

          <p class="hero__lede">
            Point CodeOops at a repository. It parses the source, resolves dependencies,
            clusters modules and returns a written overview — produced by the engine,
            never guessed at.
          </p>

          <div class="hero__actions">
            <a class="btn btn--primary btn--lg" routerLink="/analyze">
              <co-icon name="play" />
              <span>Analyze a repository</span>
            </a>
            <a class="btn btn--ghost btn--lg" routerLink="/dashboard">
              <co-icon name="dashboard" />
              <span>Go to dashboard</span>
            </a>
          </div>

          <ul class="hero__notes">
            <li><co-icon name="lock" /> <span>Runs entirely inside your network</span></li>
            <li><co-icon name="cpu" /> <span>Open-weight models on your own runtime</span></li>
            <li><co-icon name="shield" /> <span>Artifacts verified against the source repository</span></li>
          </ul>
        </div>
      </section>

      <!-- ---------------- capabilities ---------------- -->
      <section class="section" id="capabilities">
        <div class="section__inner">
          <h2 class="t-h2 section__title">What CodeOops does</h2>
          <p class="section__lede">
            One job, one repository, one document that reflects what is actually in the code.
          </p>

          <div class="cards">
            @for (item of capabilities; track item.title) {
              <article class="card">
                <co-icon-tile [name]="item.icon" [tone]="item.tone" size="lg" />
                <h3 class="card__title">{{ item.title }}</h3>
                <p class="card__text">{{ item.text }}</p>
              </article>
            }
          </div>
        </div>
      </section>

      <!-- ---------------- pipeline ---------------- -->
      <section class="section section--alt" id="pipeline">
        <div class="section__inner">
          <h2 class="t-h2 section__title">How a job runs</h2>
          <p class="section__lede">Four stages, each observable while it happens.</p>

          <ol class="flow">
            @for (step of pipeline; track step.title; let i = $index) {
              <li class="flow__item">
                <span class="flow__index">{{ i + 1 }}</span>
                <h3 class="flow__title">{{ step.title }}</h3>
                <p class="flow__text">{{ step.text }}</p>
              </li>
            }
          </ol>
        </div>
      </section>

      <!-- ---------------- cta ---------------- -->
      <section class="cta">
        <div class="cta__inner">
          <h2 class="t-h2 cta__title">Ready to document a repository?</h2>
          <p class="cta__text">Submit a Git URL and watch the pipeline run.</p>
          <a class="btn btn--primary btn--lg" routerLink="/analyze">
            <co-icon name="plus" />
            <span>Analyze a repository</span>
          </a>
        </div>
      </section>

      <footer class="foot">
        <div class="foot__inner">
          <co-logo variant="dark" size="sm" />
          <p class="foot__text">Internal developer platform · CodeWiki documentation engine</p>
        </div>
      </footer>
    </div>
  `,
  styles: `
    :host { display: block; background: var(--white); }

    .nav {
      position: sticky; top: 0; z-index: 50;
      background: rgba(255, 255, 255, 0.9);
      backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--border);
    }

    .nav__inner {
      max-width: var(--content-max);
      margin: 0 auto;
      padding: var(--s-3) var(--s-6);
      display: flex; align-items: center; gap: var(--s-6);
    }

    .nav__links { display: flex; gap: var(--s-6); margin-left: auto; font-size: var(--t-base); }
    .nav__links a { color: var(--text-secondary); font-weight: 550; }
    .nav__links a:hover { color: var(--red-500); }

    @media (max-width: 780px) { .nav__links { display: none; } }
    @media (max-width: 780px) { .nav__inner > .btn { margin-left: auto; } }

    /* ---------------- hero ---------------- */

    .hero {
      position: relative;
      overflow: hidden;
      padding: var(--s-20) var(--s-6) var(--s-16);
      background:
        radial-gradient(60rem 30rem at 78% -12%, var(--red-50), transparent 62%),
        radial-gradient(40rem 24rem at 8% 8%, #F5F7FF, transparent 60%),
        var(--white);
    }

    .hero__inner { max-width: 58rem; margin: 0 auto; text-align: center; }

    .eyebrow {
      display: inline-flex; align-items: center; gap: var(--s-2);
      padding: 0.3rem 0.75rem;
      border-radius: var(--r-pill);
      background: var(--white);
      border: 1px solid var(--red-100);
      color: var(--red-600);
      font-size: var(--t-sm); font-weight: 600;
      box-shadow: var(--shadow-xs);
    }

    .eyebrow__dot { width: 6px; height: 6px; border-radius: 50%; background: var(--red-500); }

    .hero__title { margin-top: var(--s-6); }
    .hero__accent {
      background: linear-gradient(92deg, var(--red-500), var(--red-700));
      -webkit-background-clip: text;
      background-clip: text;
      color: transparent;
    }

    .hero__lede {
      margin: var(--s-5) auto 0;
      max-width: 44rem;
      font-size: var(--t-lg);
      color: var(--text-secondary);
    }

    .hero__actions {
      margin-top: var(--s-8);
      display: flex; justify-content: center; gap: var(--s-3); flex-wrap: wrap;
    }

    .hero__notes {
      margin-top: var(--s-10);
      display: flex; justify-content: center; gap: var(--s-6); flex-wrap: wrap;
      font-size: var(--t-sm); color: var(--text-secondary);
    }

    .hero__notes li { display: inline-flex; align-items: center; gap: var(--s-2); }
    .hero__notes co-icon { width: 1.05rem; height: 1.05rem; color: var(--red-500); }

    /* ---------------- sections ---------------- */

    .section { padding: var(--s-16) var(--s-6); }
    .section--alt { background: var(--grey-50); border-block: 1px solid var(--border); }
    .section__inner { max-width: var(--content-max); margin: 0 auto; }
    .section__title { text-align: center; }
    .section__lede {
      margin: var(--s-3) auto 0; max-width: 40rem;
      text-align: center; color: var(--text-secondary); font-size: var(--t-md);
    }

    .cards {
      margin-top: var(--s-10);
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(17rem, 1fr));
      gap: var(--s-4);
    }

    .card {
      padding: var(--s-6);
      background: var(--white);
      border: 1px solid var(--border);
      border-radius: var(--r-xl);
      box-shadow: var(--shadow-sm);
      transition: box-shadow var(--base) var(--ease), transform var(--base) var(--ease);
    }

    .card:hover { box-shadow: var(--shadow-md); transform: translateY(-3px); }
    .card__title { margin-top: var(--s-4); font-size: var(--t-md); font-weight: 650; }
    .card__text { margin-top: var(--s-2); font-size: var(--t-base); color: var(--text-secondary); }

    .flow {
      margin-top: var(--s-10);
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
      gap: var(--s-4);
    }

    .flow__item {
      padding: var(--s-6);
      background: var(--white);
      border: 1px solid var(--border);
      border-radius: var(--r-xl);
    }

    .flow__index {
      display: grid; place-items: center;
      width: 2rem; height: 2rem;
      border-radius: var(--r-sm);
      background: var(--ink-950); color: #fff;
      font-weight: 700; font-size: var(--t-sm);
    }

    .flow__title { margin-top: var(--s-4); font-size: var(--t-md); font-weight: 650; }
    .flow__text { margin-top: var(--s-2); font-size: var(--t-base); color: var(--text-secondary); }

    /* ---------------- cta + footer ---------------- */

    .cta { padding: var(--s-16) var(--s-6); }
    .cta__inner {
      max-width: 46rem; margin: 0 auto; text-align: center;
      padding: var(--s-12) var(--s-8);
      border-radius: var(--r-xl);
      background: radial-gradient(30rem 16rem at 50% 0%, var(--red-50), var(--white));
      border: 1px solid var(--border);
      box-shadow: var(--shadow-sm);
    }

    .cta__text { margin: var(--s-3) 0 var(--s-6); color: var(--text-secondary); font-size: var(--t-md); }

    .foot { background: var(--ink-950); color: var(--sidebar-text); }
    .foot__inner {
      max-width: var(--content-max); margin: 0 auto;
      padding: var(--s-8) var(--s-6);
      display: flex; align-items: center; justify-content: space-between;
      gap: var(--s-4); flex-wrap: wrap;
    }
    .foot__text { font-size: var(--t-sm); }
  `,
})
export class LandingComponent {
  protected readonly capabilities: readonly Capability[] = [
    {
      icon: 'sitemap',
      tone: 'red',
      title: 'Deterministic analysis',
      text: 'Files are parsed and dependencies resolved with tree-sitter. Structure is discovered, not inferred.',
    },
    {
      icon: 'documentation',
      tone: 'blue',
      title: 'Module-level summaries',
      text: 'Every module is summarised on its own evidence, then reduced into one coherent overview.',
    },
    {
      icon: 'shield',
      tone: 'green',
      title: 'Verified artifacts',
      text: "Each document is checked against the engine's own metadata before it is shown, so no stale output can appear.",
    },
    {
      icon: 'cpu',
      tone: 'violet',
      title: 'Your own model runtime',
      text: 'Open-weight models served inside your network. No repository content leaves the environment.',
    },
    {
      icon: 'jobs',
      tone: 'cyan',
      title: 'Observable pipeline',
      text: 'Live status for every stage, with module counts and the failure reason when something goes wrong.',
    },
    {
      icon: 'code',
      tone: 'amber',
      title: 'Polyglot repositories',
      text: 'Analysis follows the languages the engine supports across the repository you submit.',
    },
  ];

  protected readonly pipeline = [
    { title: 'Submit', text: 'Provide a Git URL and an optional branch. CodeOops creates a job.' },
    { title: 'Analyse', text: 'CodeWiki parses the repository and clusters it into modules.' },
    { title: 'Generate', text: 'Modules are summarised, then reduced into a single overview.' },
    { title: 'Review', text: 'The overview is bound to the job and rendered in the console.' },
  ];
}
