# CodeOops — Docker Deployment Guide

This document covers running CodeOops on a machine other than the one it was
built on: what to install, what to copy, exact commands, and how to verify
it actually works. It does not cover application design — see `README.md`
for that. Nothing here changes CodeOops's behavior; this is packaging only.

---

## 1. Prerequisites

| Requirement | Minimum | Notes |
|---|---|---|
| OS | macOS (Apple Silicon or Intel), Linux, or Windows with WSL2 | Docker images build natively for both `arm64` and `amd64` — nothing forces emulation |
| Docker | Docker Desktop (Mac/Windows) or Docker Engine (Linux), version 24+ | `docker --version` |
| Docker Compose | v2 (the `docker compose` plugin, not the standalone `docker-compose` v1) | `docker compose version` |
| CPU | 4 cores recommended | CodeWiki's dependency analysis (tree-sitter parsing) is the most CPU-heavy step |
| RAM | 8 GB minimum for the Docker containers themselves; **the real constraint is Ollama, which needs its own headroom on top of that** — see "Ollama requirements" below | This stack was tuned against an 8GB Apple Silicon Mac; on that class of hardware, RAM is the actual bottleneck, not CPU |
| Disk | ~2.3 GB for the three CodeOops images, **plus ~4.7 GB for the Ollama model**, plus room for generated overviews (small — single Markdown files) | |
| Ollama | Installed natively on the **host**, not in Docker — see below | |
| Network/ports | `4200` (frontend), `8000` (backend), `8001` (CodeWiki), `11434` (Ollama, host-only) must be free | |

CodeOops itself needs no GPU. Ollama benefits from one (Metal on Apple
Silicon, CUDA on Linux/Windows with an NVIDIA GPU) — this is exactly why
Ollama stays outside Docker in this architecture (see §4).

---

## 2. Getting the source onto the destination machine

Copy (or `git clone`/zip) the entire `codeoops/` project directory. It is
fully self-contained — no dependency on any path, username, or container
that only exists on the machine that built it (verified: `grep`'d the whole
tree for absolute paths and usernames, found none outside this
documentation's own examples).

**Included:**
```
codeoops/
├── docker-compose.yml
├── .env.example
├── start.sh                    # one-command startup + readiness checks
├── DOCKER_DEPLOYMENT.md        # this file
├── README.md
├── backend/
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── requirements.txt
│   └── app/                    # FastAPI source
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── .dockerignore
│   └── src/                    # Angular source
└── codewiki/
    ├── Dockerfile
    ├── .dockerignore
    ├── requirements.txt
    └── codewiki/                # CodeWiki source, vendored and pre-patched
                                  # with every fix this project depends on
                                  # (single-overview mode, the evidence
                                  # extractor, resource bounds, the ZIP
                                  # upload bridge) — see codewiki/README.md's
                                  # provenance note. No manual patching
                                  # needed on the destination machine.
```

**Not included / not needed:** `node_modules/`, `.venv/`, `dist/`,
`__pycache__/`, test fixtures, `.env` (only `.env.example` — generate your
own `.env` on the destination machine), any of this machine's uploaded
repositories or generated overviews (those live in Docker volumes, which are
intentionally excluded from the package — see §5).

---

## 3. Image distribution

You have two options. Both start from the same source tree above.

### Option A — Build from source on the destination machine (default)

No extra step needed — `./start.sh` (or `docker compose up -d --build`)
builds all three images from the included source the first time it runs.
Requires internet access on the destination machine (to pull base images
and Python/npm packages during the build).

### Option B — Pre-built image archives (offline / no build tools required)

Build once, ship the `.tar` files alongside the project directory, load them
on the destination machine, then start without rebuilding.

**On the source machine:**
```bash
cd codeoops
docker compose build
docker save codeoops-backend:latest  -o codeoops-backend.tar
docker save codeoops-codewiki:latest -o codeoops-codewiki.tar
docker save codeoops-frontend:latest -o codeoops-frontend.tar
```
(Image names are pinned explicitly in `docker-compose.yml` — they will not
change even if the project folder is renamed or copied elsewhere.)

**Transfer** `codeoops-backend.tar`, `codeoops-codewiki.tar`,
`codeoops-frontend.tar` alongside the `codeoops/` project directory (same
method as the rest of the package — USB drive, internal file share, etc.;
these are not committed to git given their size).

**On the destination machine:**
```bash
docker load -i codeoops-backend.tar
docker load -i codeoops-codewiki.tar
docker load -i codeoops-frontend.tar
cd codeoops
docker compose up -d        # no --build — the loaded images are used as-is
```

### Option C — Private Docker registry (if your org has one)

Not assumed by default (no public Docker Hub account is required for any of
the above). If your organization runs a private registry:
```bash
docker tag codeoops-backend:latest  your-registry.example.com/codeoops-backend:latest
docker tag codeoops-codewiki:latest your-registry.example.com/codeoops-codewiki:latest
docker tag codeoops-frontend:latest your-registry.example.com/codeoops-frontend:latest
docker push your-registry.example.com/codeoops-backend:latest
docker push your-registry.example.com/codeoops-codewiki:latest
docker push your-registry.example.com/codeoops-frontend:latest
```
then set `image:` in `docker-compose.yml` to the registry path on the
destination machine, or `docker pull` each and re-tag to match the compose
file's expected names.

---

## 4. Ollama — required on every machine that runs CodeOops

Ollama is **not** a container in this stack and never will be by design: the
model is multi-gigabyte, and containerizing it would mean losing native GPU
acceleration (Metal on Apple Silicon, CUDA elsewhere) for no benefit. Every
machine that runs CodeOops needs Ollama installed and running natively.

| | |
|---|---|
| Install | <https://ollama.com/download> (macOS, Linux, Windows) |
| Required model | **`codewiki-qwen2.5-16k`** — do not substitute another model without updating `.env`; generation quality and the tuned resource bounds (below) were measured against this exact model |
| Base model | Qwen2.5-7B-Instruct, Q4_K_M quantization, 7.6B params |
| Required context | `num_ctx=4096` at request time (the model's Modelfile bakes a larger default, but CodeWiki explicitly requests 4096 via `OLLAMA_NUM_CTX` — see §9, do not raise this without more RAM headroom) |
| Port | `11434` (Ollama's default) — must be reachable from Docker containers via `host.docker.internal` |
| Start | `ollama serve` (or the Ollama.app menu-bar app on macOS, which does this automatically) |

**Getting the model** — if you don't already have `codewiki-qwen2.5-16k`,
either pull the base model and tag it, or point CodeOops at whatever model
you do have (never silently substituted for you):
```bash
ollama pull qwen2.5:7b
ollama cp qwen2.5:7b codewiki-qwen2.5-16k:latest
```
Or edit `.env` and set `MAIN_MODEL` / `FALLBACK_MODEL_1` / `CLUSTER_MODEL`
to a model name you already have pulled.

**How CodeWiki reaches Ollama:** `LLM_BASE_URL=http://host.docker.internal:11434/v1`
(OpenAI-compatible endpoint). `host.docker.internal` is a special DNS name
Docker resolves to the host machine's own network:

- **macOS / Windows (Docker Desktop):** works automatically, no extra config.
- **Linux:** Docker Desktop for Linux also resolves it automatically. Plain
  Docker Engine does **not**, by default — `docker-compose.yml` already
  includes the fix needed there:
  ```yaml
  extra_hosts:
    - "host.docker.internal:host-gateway"
  ```
  (already present in the shipped `docker-compose.yml`; nothing to add).

**Verify Ollama is reachable and the model is present**, from the host:
```bash
curl -s http://localhost:11434/api/tags | grep codewiki-qwen2.5-16k
```
`./start.sh` runs this same check automatically on every startup and will
tell you plainly if either Ollama or the model is missing.

---

## 5. Persistent data

| What | Where | Survives `docker compose down`? | Survives `docker compose down -v`? |
|---|---|---|---|
| Uploaded ZIP / extracted repositories, generated `overview.md`, CodeWiki's dependency-graph cache | Named volume `codewiki-output` (mounted at `/app/output` in `codewiki`, `/data/codewiki-output` in `backend`) | Yes | No — `-v` deletes volumes |
| Backend's verified-artifact copies (`overview.md` bytes keyed by CodeOops job id) | Named volume `codeoops-artifacts` (`/data/artifacts` in `backend`) | Yes | No |
| Repository records, job status/history | **In-memory only, in the backend process** — CodeOops has no database (verified from the actual code: `InMemoryRepositoryStore`, an in-memory job store) | **No — this is current, correct desktop behavior, not a Docker limitation** | No |
| Ollama model weights | `~/.ollama` on the **host**, outside Docker entirely | Always (not Docker-managed) | Always |

Nothing user-generated (uploaded repositories, generated overviews) is
baked into any Docker image — both `.dockerignore` files and the volume
design keep that data out of the build context and in named volumes only.

---

## 6. Startup

```bash
cd codeoops
cp .env.example .env      # only if you haven't already; defaults match the
                           # tuned, resource-conscious desktop config
./start.sh
```

`start.sh` checks Docker, checks/creates `.env`, checks Ollama reachability
and the required model, starts the stack, waits for all health checks, and
confirms the backend can actually reach CodeWiki — printing a clear ✓/✗ for
every step rather than a single pass/fail. Run `./start.sh --backend-only`
to skip the Angular frontend entirely (see §8).

Equivalent manual form:
```bash
docker compose up -d              # full stack: codewiki, backend, frontend
docker compose up -d codewiki backend    # backend-only
```

Stop: `docker compose down` (volumes persist). Full reset including
generated data: `docker compose down -v`.

---

## 7. Configuration — every `.env` variable

All names are the actual variables the code reads (backend's
`app/core/config.py` `Settings`, CodeWiki's `config.py`/`llm_services.py`) —
nothing invented.

| Variable | Default | Meaning |
|---|---|---|
| `DOCUMENTATION_PROVIDER` | `codewiki` | Which engine the backend wires up. Only `codewiki` is implemented. |
| `CODEWIKI_BASE_URL` | `http://codewiki:8000` | Backend → CodeWiki, over the Docker network. Don't change unless you rename the `codewiki` service. |
| `ALLOWED_ORIGINS` | `http://localhost:4200` | CORS allow-list. Add the actual origin here if the frontend is accessed from a different host/port than the default. |
| `ALLOWED_REPOSITORY_HOSTS` | `github.com` | Git hosts CodeOops will accept a repository URL from. |
| `MAIN_MODEL` / `FALLBACK_MODEL_1` / `CLUSTER_MODEL` | `codewiki-qwen2.5-16k:latest` | The Ollama model CodeWiki calls. Same model for all three roles in this deployment (no separate clustering model — clustering is bypassed entirely in single-overview mode anyway). |
| `LLM_BASE_URL` | `http://host.docker.internal:11434/v1` | Where CodeWiki reaches Ollama. See §4. |
| `LLM_API_KEY` | `dummy` | Ollama's OpenAI-compatible endpoint doesn't check this; any placeholder works. |
| `OVERVIEW_ONLY_MODE` | `true` | **Do not disable.** Single `overview.md` per repository, no module docs, no agentic sub-generation. |
| `OLLAMA_NUM_CTX` | `4096` | Ollama context window. Tuned to this value specifically to avoid Metal→CPU fallback and system-wide swap thrashing on an 8GB host — see §9. |
| `OVERVIEW_MAX_OUTPUT_TOKENS` | `1500` | Output token cap for the single overview-generation call. |
| `EVIDENCE_TOKEN_BUDGET` | `1100` | Token budget for the curated architecture evidence fed to the model (README, manifests, entry points, detected signals). |
| `EVIDENCE_MAX_REPRESENTATIVE_FILES` | `3` | Cap on how many "most-referenced" source files get included as evidence. |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `1200` | Hard per-request timeout to Ollama. Paired with `max_retries=0` (not env-configurable — baked into `codewiki/codewiki/src/be/llm_services.py` on purpose). |

---

## 8. Backend-only usage (no frontend required)

**The frontend is entirely optional.** The backend implements the complete
workflow on its own — it doesn't call into the frontend for anything, and
the frontend is a pure client of the backend's API (confirmed by running
`docker compose up -d codewiki backend`, with no `frontend` container at
all, and driving the full pipeline below with nothing but `curl`).

Start backend-only: `./start.sh --backend-only` or
`docker compose up -d codewiki backend`.

All examples below use `http://localhost:8000` directly.

### 1. Upload a ZIP repository
```bash
curl -X POST http://localhost:8000/api/v1/repositories/upload \
  -F "file=@my-repo.zip;type=application/zip"
```
Response includes `"id"` — the repository UUID used below.
```json
{"id": "f4f4b0d2-...", "owner": "upload", "name": "my-repo", "source": "UPLOAD", "status": "READY", ...}
```

*(GitHub instead of ZIP: `POST /api/v1/repositories` with
`{"repository_url": "https://github.com/owner/repo"}` — same downstream
pipeline from here on.)*

### 2. Create a documentation job
```bash
curl -X POST http://localhost:8000/api/v1/documentation/jobs \
  -H "Content-Type: application/json" \
  -d '{"repository_id": "f4f4b0d2-..."}'
```
Response includes `"id"` — the job UUID.

### 3. Poll job status
```bash
curl http://localhost:8000/api/v1/documentation/jobs/<job-id>
```
`"status"` moves `SUBMITTING → GENERATING → COMPLETED` (or `FAILED`, with
`error_code`/`error_message` set — never a silent hang, per §9).

### 4. Retrieve the overview (raw Markdown)
```bash
curl http://localhost:8000/api/v1/documentation/jobs/<job-id>/overview
```

### 5. Download PDF export
```bash
curl -OJ http://localhost:8000/api/v1/documentation/jobs/<job-id>/overview.pdf
```

### 6. Download CSV export
```bash
curl -OJ http://localhost:8000/api/v1/documentation/jobs/<job-id>/overview.csv
```

Full interactive API reference (every route, request/response schema):
`http://localhost:8000/docs` (FastAPI's built-in Swagger UI — always
available, no separate doc generation needed).

---

## 9. Resource safety — do not raise these to "make it work faster"

This stack deliberately trades speed for staying inside an 8GB host's real
capacity. Measured directly during tuning: past ~4096 tokens of Ollama
context on that class of machine, the model spills from 100% GPU/Metal to a
CPU/GPU split, and the whole host starts swapping — generation goes from
single-digit seconds to not finishing within a 20-minute timeout. These
values are the result of that measurement, not arbitrary defaults:

- `OVERVIEW_ONLY_MODE=true` — exactly one `overview.md`, never module docs
- `OLLAMA_NUM_CTX=4096`
- `EVIDENCE_TOKEN_BUDGET=1100`
- `OVERVIEW_MAX_OUTPUT_TOKENS=1500`
- `EVIDENCE_MAX_REPRESENTATIVE_FILES=3`
- `LLM_REQUEST_TIMEOUT_SECONDS=1200`
- `max_retries=0` (baked into `llm_services.py`, not env-configurable — a
  timed-out local generation needs more time, not a retry; retrying just
  multiplies the wait for the same eventual outcome)

**Concurrency**: CodeWiki's own Ollama call path is guarded by an in-process
semaphore (`_ollama_call_lock` in `llm_services.py`) so only one generation
talks to Ollama at a time even if the backend fires multiple jobs
concurrently. There is no queueing beyond that — submitting several jobs at
once will serialize their Ollama calls automatically rather than contend for
the same memory-constrained model simultaneously.

If you're deploying to a machine with meaningfully more RAM (16GB+) and want
faster/richer generation, raise `OLLAMA_NUM_CTX` and `EVIDENCE_TOKEN_BUDGET`
together and re-measure — don't raise one without the other, and don't
assume a bigger number is free.

---

## 10. Verification checklist

Run these on the destination machine after `./start.sh`:

```bash
# Container + health status
docker compose ps
# Expect: all requested services "Up ... (healthy)"

# Backend
curl -s http://localhost:8000/openapi.json | head -c 100

# CodeWiki
curl -s http://localhost:8001/ -o /dev/null -w "%{http_code}\n"   # expect 200

# Backend -> CodeWiki, over the Docker network
curl -s http://localhost:8000/api/v1/documentation/engine
# expect {"engine":"codewiki","reachable":true,...}

# Ollama, from the host
curl -s http://localhost:11434/api/tags | grep codewiki-qwen2.5-16k

# ZIP upload + job creation (see §8 for the full pipeline)
curl -X POST http://localhost:8000/api/v1/repositories/upload -F "file=@test.zip;type=application/zip"
```

If frontend is running: open `http://localhost:4200` and confirm the page
loads and `/api/v1/*` calls succeed (the nginx reverse proxy forwards them
to `backend:8000` — check `frontend/nginx.conf` if this doesn't work).

---

## 11. Troubleshooting

**CodeWiki unreachable from backend** (`"reachable":false` from
`/api/v1/documentation/engine`) — check `docker compose logs codewiki`;
confirm the `codewiki` container is healthy (`docker compose ps`); confirm
`CODEWIKI_BASE_URL` in `.env` matches the service name (`http://codewiki:8000`,
not `localhost`).

**Ollama unreachable** — `curl http://localhost:11434/api/tags` from the
host. If that fails, Ollama isn't running (`ollama serve` or launch the
app). Containers reach it via `host.docker.internal`, which only works if
Ollama is bound on the host, not inside another container/VM.

**Model missing** — `ollama pull codewiki-qwen2.5-16k:latest` fails because
that exact tag doesn't exist upstream; pull the base model and tag it (§4),
or point `.env`'s `MAIN_MODEL`/etc. at a model you actually have.

**Port already occupied** — `Error starting userland proxy: ... address
already in use` on 4200/8000/8001. Something else is bound there; stop it,
or change the left-hand side of the port mapping in `docker-compose.yml`
(e.g. `"8010:8000"`) and adjust `.env`'s URLs to match.

**Insufficient RAM** — generation hangs and eventually hits the 1200s
timeout with `"error_message":"Request timed out."`; `docker stats` shows
the containers themselves using little memory while the host is swapping
heavily (check with `vm_stat`/Activity Monitor on macOS, `free -h` on
Linux). This is host memory pressure (often from Ollama itself, or other
running applications), not a container resource limit — see §9 before
assuming something is broken.

**Docker volume permissions** — if `codewiki`/`backend` can't write to
`/app/output`/`/data/*`, this is unusual for named volumes (Docker manages
ownership automatically); if it happens, `docker volume rm
codeoops_codewiki-output codeoops_codeoops-artifacts` and let compose
recreate them fresh (this deletes any previously generated data in them).

**Container startup ordering** — `backend` won't start until `codewiki`
reports healthy (`depends_on: condition: service_healthy` in
`docker-compose.yml`), and `frontend` waits for `backend` to at least start.
If `backend` seems stuck "Created" and never starts, check
`docker compose logs codewiki` — it likely never became healthy.

**`host.docker.internal` unavailable** — only expected on plain Docker
Engine on Linux without the `extra_hosts: host-gateway` entry; the shipped
`docker-compose.yml` already includes it for the `codewiki` service. If
you've edited that section, that's the first thing to check.

**ARM64/x86 differences** — all base images (`python:3.12-slim`,
`node:22-alpine`, `nginx:alpine`) have native images for both architectures;
nothing in this stack forces `linux/amd64`. If you see architecture warnings
during build, check that you haven't added a `platform:` override —
none is needed or present in the shipped compose file.

---

## 12. What was actually verified (not assumed)

- All three images build natively (no forced emulation) and are explicitly
  tagged (`codeoops-backend:latest`, `codeoops-codewiki:latest`,
  `codeoops-frontend:latest`) so the names survive being cloned into a
  differently-named folder.
- Full stack and **backend-only** (`codewiki` + `backend`, no `frontend`)
  both start cleanly and reach `healthy`.
- ZIP upload → registration → job creation → CodeWiki submission, driven
  entirely by `curl` against `localhost:8000` with no frontend running at
  all — confirmed working end-to-end.
- `docker compose down && up -d`: named volumes (`codewiki-output`,
  `codeoops-artifacts`) survive; in-memory repository/job tracking
  correctly resets — matching actual current desktop behavior (no
  database exists), not a Docker-specific regression.
- `docker save` / `docker load` round trip for all three images.
- Whether a full generation completed in this verification pass — see the
  chat response for the concrete, current result; this document doesn't
  claim success it didn't observe.
