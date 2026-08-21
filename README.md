# CodeOops

> **Your code broke. Your docs shouldn't.**

CodeOops turns any GitHub repository into structured technical documentation
powered by **CodeWiki**.

This repository contains the **application foundation**: an Angular workspace, a
FastAPI orchestration API, and the boundary where the documentation engine will
plug in. It deliberately contains **no documentation-generation engine of any
kind**.

---

## 1. What this build does and does not do

| Does | Does not |
|---|---|
| Accept a GitHub repository URL | Generate documentation |
| Validate and normalise it server-side | Call any LLM (OpenAI, Anthropic, Ollama, …) |
| Create a repository record with a stable UUID | Produce Markdown of its own |
| Report documentation state per repository | Ship sample or placeholder documentation |
| Render an explicit empty state in the reader | Display a fallback document when none exists |

The one rule everything else follows:

> **CodeOops orchestrates. CodeWiki documents.**

Until CodeWiki is connected, every repository reports `NOT_GENERATED` with a
`null` artifact, and the documentation reader stays genuinely empty. Four
executable tests in `backend/tests/test_codewiki_boundary.py` fail the build if
that ever stops being true.

---

## 2. Architecture

```
        Browser
           │
           ▼
  ┌───────────────────┐   HTTP / JSON       ┌────────────────────┐
  │  Angular SPA      │ ──────────────────▶ │  FastAPI           │
  │  :4200            │ ◀────────────────── │  :8000  /api/v1    │
  └───────────────────┘                     └─────────┬──────────┘
     RepositoryService                                │
     ApiClient (only URL builder)                     ▼
                                          ┌────────────────────────┐
                                          │ DocumentationProvider  │  ← port
                                          │ (abstract, unwired)    │
                                          └─────────┬──────────────┘
                                                    ▼
                                          ┌────────────────────────┐
                                          │ CodeWiki               │  ← next phase
                                          └────────────────────────┘
```

**Backend layering** — routes translate HTTP, services hold behaviour, the store
holds data, and the provider port is the only door to an external engine:

```
api/routes  →  services  →  repositories (storage)
                  └──────→  providers (DocumentationProvider port)
```

Routes contain no business logic. Services contain no HTTP. The provider port
has no implementation.

**Frontend layering** — `core/` owns transport and domain contracts, `features/`
owns screens, `shared/` owns chrome and visuals:

```
features/*  →  core/services/*  →  core/api/ApiClient  →  API_BASE_URL
```

`ApiClient` is the only place a backend URL is constructed. No component builds
one.

---

## 3. Project structure

```
codeoops/
├── backend/
│   ├── app/
│   │   ├── main.py                      FastAPI factory, CORS, error handlers
│   │   ├── core/
│   │   │   ├── config.py                pydantic-settings; the only env reader
│   │   │   └── errors.py                AppError hierarchy → HTTP payloads
│   │   ├── api/
│   │   │   ├── router.py                aggregate router
│   │   │   ├── deps.py                  the single wiring point
│   │   │   └── routes/
│   │   │       ├── health.py
│   │   │       └── repositories.py
│   │   ├── schemas/                     request/response models
│   │   │   ├── common.py
│   │   │   ├── repository.py
│   │   │   └── documentation.py
│   │   ├── models/                      domain objects
│   │   │   ├── enums.py
│   │   │   ├── repository.py
│   │   │   └── documentation.py
│   │   ├── services/
│   │   │   ├── repository_url_policy.py validation + normalisation
│   │   │   ├── repository_service.py
│   │   │   └── documentation_service.py
│   │   ├── repositories/
│   │   │   └── repository_repository.py RepositoryStore port + in-memory impl
│   │   └── providers/
│   │       └── documentation_provider.py  ← the CodeWiki boundary (no impl)
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_health.py
│   │   ├── test_repositories.py
│   │   ├── test_documentation.py
│   │   └── test_codewiki_boundary.py    executable architecture rules
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── pytest.ini
│   └── .env.example
│
└── frontend/
    ├── src/
    │   ├── app/
    │   │   ├── core/
    │   │   │   ├── api/                 ApiClient, API_BASE_URL, error interceptor
    │   │   │   ├── models/              wire contracts + WorkflowState
    │   │   │   ├── services/            RepositoryService, HealthService, ToastService
    │   │   │   └── validation/          client-side URL check
    │   │   ├── features/
    │   │   │   ├── home/                landing page
    │   │   │   ├── repositories/        list + submit form
    │   │   │   ├── documentation/       workspace + viewer
    │   │   │   ├── settings/
    │   │   │   └── not-found/
    │   │   ├── shared/
    │   │   │   ├── layout/              app shell, site header
    │   │   │   └── ui/                  logo, status pill, toasts, CSS-3D objects
    │   │   ├── app.component.ts
    │   │   ├── app.config.ts
    │   │   └── app.routes.ts
    │   ├── environments/
    │   ├── styles.scss                  design tokens + primitives
    │   └── index.html
    ├── public/favicon.svg
    ├── angular.json
    └── package.json
```

---

## 4. Running it

### Backend

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

uvicorn app.main:app --reload --port 8000
```

Verify:

```bash
curl http://127.0.0.1:8000/api/v1/health
# {"status":"ok","service":"CodeOops API","version":"0.1.0"}
```

Interactive API docs: <http://127.0.0.1:8000/docs>

Tests:

```bash
cd backend
pytest
```

### Frontend

```bash
cd frontend
npm install
npm start
```

Open <http://localhost:4200>.

Tests:

```bash
cd frontend
npm test              # interactive
npm run test:ci       # headless Chrome, single run
```

Production build:

```bash
npm run build         # → dist/codeoops
```

> The dev server talks to `http://127.0.0.1:8000/api/v1`
> (`src/environments/environment.development.ts`). The backend allows the
> `http://localhost:4200` origin by default.

---

## Running with Docker

The full stack — Angular, FastAPI, and a vendored, pre-patched CodeWiki — runs
via Docker Compose. Ollama is deliberately **not** containerized; it stays
native on the host, which is what this stack's resource tuning (context size,
token budgets, timeout) was actually measured against.

### Prerequisites

- Docker Desktop (or another Docker Engine + Compose v2)
- [Ollama](https://ollama.com) installed and running natively on the host
  (`ollama serve`, or the Ollama.app menu-bar app), with the model pulled:
  ```bash
  ollama pull codewiki-qwen2.5-16k:latest
  ```
  (If you only have a base model, e.g. `qwen2.5:7b`, either re-tag it as
  `codewiki-qwen2.5-16k:latest` or set `MAIN_MODEL`/`FALLBACK_MODEL_1`/
  `CLUSTER_MODEL` in `.env` to your model's actual name.)

### Start

```bash
cp .env.example .env       # defaults already match the tuned desktop config
docker compose up --build
```

| Service | URL | Purpose |
|---|---|---|
| `frontend` | <http://localhost:4200> | Angular SPA (nginx), proxies `/api/v1/*` to `backend` |
| `backend` | <http://localhost:8000> | FastAPI orchestration API |
| `codewiki` | <http://localhost:8001> | Documentation engine (single-overview mode) |

Ollama stays wherever it already runs: <http://localhost:11434> on the host,
reached from `codewiki` via `host.docker.internal`.

### Stop / restart

```bash
docker compose down        # containers stop; codewiki-output and
                            # codeoops-artifacts volumes are NOT deleted
docker compose up -d        # restarts with the same volumes — uploaded
                            # repositories and generated overview.md files
                            # already on disk are still there
```

Repository/job *tracking* state (the in-memory list in the backend process)
does not survive a backend restart — that's the current desktop behavior too,
not a Docker regression: CodeOops has no database.

### Docker resource notes

`OLLAMA_NUM_CTX`, `EVIDENCE_TOKEN_BUDGET`, and `OVERVIEW_MAX_OUTPUT_TOKENS` in
`.env.example` are not arbitrary — they were measured against a real 8GB
Apple Silicon Mac. Past roughly 4096 tokens of Ollama context on that
hardware, `ollama ps` showed the model spilling from 100% GPU/Metal to a
CPU/GPU split, and the whole machine started swapping — generation went from
single digits of seconds to not finishing in 20+ minutes. If you're on a
machine with more headroom, raise these; if you hit the same cliff, lower
`OLLAMA_NUM_CTX` and `EVIDENCE_TOKEN_BUDGET` together first before assuming
the model itself is the problem.

### Troubleshooting

```bash
docker compose logs codewiki     # generation progress, evidence-budget
                                  # logging, the exact OVERVIEW_ONLY_MODE /
                                  # OLLAMA_NUM_CTX values actually in effect
docker compose logs backend
docker compose ps                # health status of all three services
ollama ps                        # confirm the model is loaded / check its
                                  # actual CPU/GPU split (run on the host)
```

If `codewiki` reports unhealthy on first boot, give it the `start_period`
(20s) to finish loading before assuming something's wrong — the first
request into a cold model always costs a load-time hit on top of generation.

---

## 5. Environment variables

All backend configuration lives in `backend/app/core/config.py`; nothing else
reads the environment. Copy `backend/.env.example` to `backend/.env` to override.
Every value has a working default — no configuration is required to run locally.

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `CodeOops API` | Shown by `/health` |
| `APP_VERSION` | `0.1.0` | Shown by `/health` |
| `API_PREFIX` | `/api/v1` | Route prefix |
| `ENVIRONMENT` | `development` | Free-form environment label |
| `DEBUG` | `true` | Debug flag |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address |
| `ALLOWED_ORIGINS` | `http://localhost:4200` | CORS allow-list (comma-separated) |
| `ALLOWED_REPOSITORY_HOSTS` | `github.com` | Accepted Git hosts (comma-separated) |
| `DEFAULT_BRANCH_FALLBACK` | `main` | Recorded branch until the host is queried |
| `DOCUMENTATION_PROVIDER` | *(empty)* | Engine to use. Empty = none connected |

Frontend configuration is in `frontend/src/environments/`:

| Key | Development | Production |
|---|---|---|
| `apiBaseUrl` | `http://127.0.0.1:8000/api/v1` | `/api/v1` (same-origin) |

---

## 6. API

Base path: `/api/v1`

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness. `{"status":"ok",...}` |
| `POST` | `/repositories` | Submit a repository URL → repository record |
| `GET` | `/repositories` | List submitted repositories, newest first |
| `GET` | `/repositories/{repository_id}` | One repository |
| `GET` | `/repositories/{repository_id}/documentation` | Documentation state for that repository |

### `POST /api/v1/repositories`

```json
{ "repository_url": "https://github.com/owner/repository" }
```

`201 Created` (or `200 OK` when the repository was already submitted — the id is
stable):

```json
{
  "id": "c0284f2c-0951-4d0e-aa9e-e890b2bcc61b",
  "owner": "owner",
  "name": "repository",
  "repository_url": "https://github.com/owner/repository",
  "default_branch": "main",
  "status": "READY",
  "created_at": "2026-08-14T11:41:33.816605Z",
  "updated_at": "2026-08-14T11:41:33.816611Z"
}
```

### `GET /api/v1/repositories/{id}/documentation`

```json
{
  "repository_id": "c0284f2c-0951-4d0e-aa9e-e890b2bcc61b",
  "status": "NOT_GENERATED",
  "artifact": null,
  "detail": "No documentation provider is connected. CodeWiki integration is not enabled in this build."
}
```

### Errors

Every failure uses one envelope:

```json
{
  "error": {
    "code": "INVALID_REPOSITORY_URL",
    "message": "Only repositories hosted on github.com are supported.",
    "details": { "host": "gitlab.com" }
  }
}
```

| Code | Status | When |
|---|---|---|
| `INVALID_REPOSITORY_URL` | 422 | URL fails the repository policy |
| `REQUEST_VALIDATION_ERROR` | 422 | Request body does not match the schema |
| `REPOSITORY_NOT_FOUND` | 404 | Unknown repository id |
| `DOCUMENTATION_PROVIDER_NOT_CONFIGURED` | 501 | Generation requested with no engine wired |

---

## 7. Data model

```
Repository ──▶ DocumentationJob ──▶ DocumentationArtifact
 (built)          (next phase)          (next phase)
```

Implemented now:

| Field | Type | Note |
|---|---|---|
| `id` | UUID | Application-level identity |
| `owner` / `name` | str | Parsed from the URL |
| `repository_url` | str | Canonical `https://github.com/owner/name` |
| `default_branch` | str | Configured fallback until the host is queried |
| `status` | enum | `READY` today; `GENERATING` / `COMPLETED` / `FAILED` reserved |
| `created_at` / `updated_at` | datetime | UTC |

Storage is a thread-safe in-memory store behind a `RepositoryStore` port.
Introducing a database later means adding one adapter and changing one line in
`app/api/deps.py` — no service or route touches persistence directly.

---

## 8. UI states

Every repository and documentation operation is in exactly one explicit state:

```
IDLE · SUBMITTING · READY · GENERATING · COMPLETED · FAILED · NOT_GENERATED
```

Errors are never hidden. Invalid URLs surface inline on the field, backend
failures surface as a typed `ApiError` in a toast and in a panel, and an
unreachable API is reported distinctly (`BACKEND_UNAVAILABLE`) with the command
to start it. The application uses no browser `alert()`.

---

## 9. Design system

Airtel-inspired, dark-first, red used sparingly — primary action, active nav,
accent glow, and nothing else.

- **Tokens** live in `src/styles.scss` (`--co-*`): brand red ramp, charcoal ink
  ramp, semantic status hues, glass surfaces, elevation, motion easings.
- **Glassmorphism** via `.co-glass` (blur + saturate, hairline border, inner
  highlight) and `.co-panel` for opaque layered cards.
- **3D is CSS-only** — `perspective` + `transform-style: preserve-3d`. The hero
  repository cube, its orbital rings and the documentation prism are DOM
  elements, not WebGL. No Three.js, no canvas, no animation library.
- **Performance**: every animation drives `transform` or `opacity` only, so it
  stays on the compositor.
- **Motion** is wrapped in `@media (prefers-reduced-motion: no-preference)`, and
  a global reduce rule neutralises anything left.
- **Accessibility**: skip link, semantic landmarks, visible focus rings,
  labelled inputs, `aria-current` on active nav, `aria-live` toasts,
  `aria-invalid` + `aria-describedby` on the URL field.

---

## 10. Tests

**Backend — 37 tests, all passing.**

| File | Covers |
|---|---|
| `test_health.py` | Health endpoint |
| `test_repositories.py` | Valid submission, `.git`/slash normalisation, stable id on resubmission, 17 rejected URL forms, retrieval, 404, malformed id, listing and ordering |
| `test_documentation.py` | `NOT_GENERATED` with `null` artifact, no document content in the payload, 404 for unknown repository, no provider registered, generation fails loudly without an engine |
| `test_codewiki_boundary.py` | No LLM SDK imported anywhere; no documentation-generation symbols defined; no embedded Markdown documents; the provider port has no implementation |

**Frontend**

| File | Covers |
|---|---|
| `repository-url.spec.ts` | 14 accepted/rejected URL forms |
| `repository.service.spec.ts` | Create, cache, list, get, documentation read, typed validation error, offline detection, and that raw `HttpErrorResponse` never escapes |
| `api-error.interceptor.spec.ts` | Envelope unwrapping, status-0 handling, fallbacks |
| `documentation-viewer.component.spec.ts` | Empty state text, no document surface, no Markdown elements, engine reported as not connected |

---

## 11. Next phase — CodeWiki integration

Everything below is deliberately left undone. The seams are already in place.

1. **Implement one adapter.** Create `app/providers/codewiki_provider.py` with
   `class CodeWikiProvider(DocumentationProvider)` and return it from
   `get_documentation_provider()` when `DOCUMENTATION_PROVIDER=codewiki`. That
   function is the only wiring change the application needs.
2. **Add the job entity.** `DocumentationJob` sits between `Repository` and
   `DocumentationArtifact` so two generations of one repository stay distinct.
   The repository record must not become the documentation identity.
3. **Add persistence.** Swap `InMemoryRepositoryStore` for a database adapter
   behind the existing `RepositoryStore` port so job ↔ artifact relationships
   survive a restart.
4. **Add async processing.** Submission must return immediately; generation runs
   out of band. `POST /repositories` stays fast.
5. **Add artifact endpoints.** `GET /jobs/{job_id}/artifact` and
   `…/artifact/files/{path}` returning the engine's bytes verbatim — keyed on
   the job, never on a repository name and never "latest".
6. **Render real Markdown.** The reader's `.doc-prose` typography, code blocks
   and Mermaid area already exist in
   `documentation-viewer.component.scss`; wire a sanitising Markdown renderer
   into the branch that currently never executes.
7. **Keep the guardrails.** `test_codewiki_boundary.py` must stay green. If
   integrating the engine ever requires importing an LLM SDK into this codebase,
   the integration is being done in the wrong place.

Not to be done, in this phase or any other: a second documentation engine, a
fallback document, or content presented as CodeWiki output that CodeWiki did not
produce.
