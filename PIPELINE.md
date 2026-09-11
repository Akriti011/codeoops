# Model-Agnostic Documentation Pipeline

`Project → Codebase Analysis → Structured Overview → HLD → LLD`

Every generation stage resolves its own model and decoding parameters from
environment variables. Moving to a stronger machine is **configuration only** —
no application code changes.

---

## 1. The four stages

Two ways to feed a repository in, both producing the full pipeline:

- **Git URL** — `Analyze repository → Git URL`, or `POST /api/v1/documentation/jobs {repository_url}`. Private repos need `GITHUB_TOKEN` in `.env`.
- **ZIP upload** — `Analyze repository → Upload ZIP` (drag a `.zip` of the source tree, no `.git` needed), or `POST /api/v1/repositories/upload` then `POST /api/v1/documentation/jobs {repository_id}`. Works fully offline; the only path that needs no GitHub access.

| Stage | Input | Output | Model config |
|---|---|---|---|
| **1. Codebase Analysis** | repository (Git clone or uploaded ZIP) | dependency graph, call graph, deterministic signal scan | none (no LLM) |
| **2. Overview** | analysis + curated evidence | `overview.md` (narrative) **and** `overview.json` (structured IR) | `OVERVIEW_*` |
| **3. HLD** | `overview.json` + `overview.md` | `hld.md` + `hld.validation.json` | `HLD_*` |
| **4. LLD** | `overview.json` + `hld.md` + source of the most central components | `lld.md` + `lld.validation.json` | `LLD_*` |

Stages 3 and 4 **consume the structured IR** — they do not re-parse the
repository. The IR (`overview.json`, `schema_version: overview-ir/1`) is the
machine-readable source of truth: project metadata, modules, components (with
file:line), dependency edges, entry points, integrations, tech stack, config
env vars, plus the LLM narrative tagged `"source": "llm"`.

Each generated document ends with a `## Verification` block: a deterministic
grounding check of every file / component / env var / datastore reference
against the IR (FACT / INFERRED / UNSUPPORTED). Written by
`codewiki/src/be/doc_validator.py`; a larger model does **not** switch it off.

---

## 2. Configuration reference

All variables are read by `codewiki/src/config.py::task_model()` and passed
into `docker-compose.yml`. Anything unset inherits: `{STAGE}_X` →
`OVERVIEW_X` → (`MAIN_MODEL` / `OLLAMA_NUM_CTX` / `OVERVIEW_MAX_OUTPUT_TOKENS`).

```
MAIN_MODEL                 fallback model for every stage
LLM_BASE_URL               default OpenAI-compatible endpoint (Ollama here)
LLM_API_KEY                default key ("dummy" for local Ollama)

OVERVIEW_MODEL / _NUM_CTX / _MAX_TOKENS / _TEMPERATURE
HLD_MODEL / _NUM_CTX / _MAX_TOKENS / _TEMPERATURE / _LLM_BASE_URL / _LLM_API_KEY
LLD_MODEL / _NUM_CTX / _MAX_TOKENS / _TEMPERATURE / _LLM_BASE_URL / _LLM_API_KEY

HLD_ENABLED=true|false     run stage 3 (default true)
LLD_ENABLED=true|false     run stage 4 (default true)
LLD_CODE_CONTEXT_FILES=12  central components whose source LLD may read
DOC_VALIDATOR_ENABLED=true grounding check (keep on)
```

Per-stage `_LLM_BASE_URL` / `_LLM_API_KEY` let HLD/LLD run on a **different
endpoint** than the overview — e.g. local 7B overview + frontier API HLD/LLD.

---

## 3. Machine profiles (env only)

### This laptop — 7B, CPU/Metal (development / test)

Leave every `*_MODEL` blank; `MAIN_MODEL` is used for all stages.

```
MAIN_MODEL=qwen2.5-coder:7b
FALLBACK_MODEL_1=qwen2.5-coder:7b
CLUSTER_MODEL=qwen2.5-coder:7b
OLLAMA_NUM_CTX=12288
OVERVIEW_MAX_OUTPUT_TOKENS=3500
HLD_ENABLED=true
LLD_ENABLED=true
```

### GPU laptop — 14B for reasoning

```
OVERVIEW_MODEL=qwen2.5-coder:7b
OVERVIEW_NUM_CTX=12288
HLD_MODEL=qwen2.5-coder:14b
HLD_NUM_CTX=24576
HLD_MAX_TOKENS=6000
LLD_MODEL=qwen2.5-coder:14b
LLD_NUM_CTX=32768
LLD_MAX_TOKENS=8000
```

### GPU workstation — 32B

```
OVERVIEW_MODEL=qwen2.5-coder:7b
HLD_MODEL=qwen2.5-coder:32b
HLD_NUM_CTX=32768
HLD_MAX_TOKENS=8000
LLD_MODEL=qwen2.5-coder:32b
LLD_NUM_CTX=49152
LLD_MAX_TOKENS=10000
```

### Frontier API for HLD/LLD, local 7B overview

```
OVERVIEW_MODEL=qwen2.5-coder:7b
HLD_LLM_BASE_URL=https://api.openai.com/v1
HLD_LLM_API_KEY=sk-...
HLD_MODEL=gpt-4o
LLD_LLM_BASE_URL=https://api.openai.com/v1
LLD_LLM_API_KEY=sk-...
LLD_MODEL=gpt-4o
```

Then `docker compose up -d codewiki` (restart only — **no rebuild, no code
change**) and generate.

---

## 4. What model can this machine run?

```
python3 scripts/model_advisor.py          # human report
python3 scripts/model_advisor.py --json    # machine-readable
```

Reports GPU / VRAM / RAM, the feasible parameter sizes at Q4 / Q8 (weights +
HLD-context KV cache + 8% headroom), and a recommended per-stage model with
the exact env lines. It will say "no >7B model fits" rather than pretend.

Rough guidance (confirm with the advisor on the real hardware):

| Model | Q4_K_M weights | + HLD KV | Fits comfortably in |
|---|---|---|---|
| 7B  | ~4.7 GiB | ~5.3 GiB | 8 GiB VRAM (tight) |
| 14B | ~9.0 GiB | ~9.9 GiB | 12–16 GiB VRAM |
| 32B | ~19 GiB  | ~21 GiB  | 24 GiB VRAM |
| 70B | ~40 GiB  | ~43 GiB  | 48 GiB+ VRAM |

`7B` → local dev/test. `14B` → clearly stronger HLD/LLD reasoning.
`32B` → preferred for complex designs when VRAM allows.

---

## 5. Run on another laptop

**Prerequisites**

| Requirement | Version | Notes |
|---|---|---|
| Docker Desktop / Engine | 24+ with Compose v2 | builds all three images |
| Ollama | native install, **not** containerised | `ollama serve` or Ollama.app |
| Python | 3.10+ | only for `scripts/model_advisor.py` |
| Node | not required at runtime | only if rebuilding the frontend outside Docker |
| GPU | optional | 7B runs CPU/Metal; 14B+ wants a CUDA/Metal GPU |

Ollama is reached at `http://host.docker.internal:11434` from the containers —
Docker Desktop resolves this automatically; `extra_hosts: host-gateway` in the
compose file covers Linux hosts. **No machine-specific absolute paths anywhere**
— repository content lives on named Docker volumes.

**Steps**

```bash
git clone <this repo> && cd codeoops
cp .env.example .env

# 1. pick a profile in .env (section 3 above), or run the advisor first:
python3 scripts/model_advisor.py

# 2. pull the models named in .env
ollama pull qwen2.5-coder:7b          # + qwen2.5-coder:14b / :32b if configured

# 3. start Ollama, then bring the stack up
ollama serve &                        # or launch Ollama.app
./start.sh                            # validates prereqs + models in .env, builds, waits for health
#   ./start.sh --backend-only         # skip the Angular frontend

# ports:  frontend 4200 · backend 8000 (/docs) · codewiki 8001
# stop:   docker compose down
```

`start.sh` reads the model names out of `.env` (all `*_MODEL` + `MAIN_MODEL`)
and checks each is present in Ollama — it does not hardcode a model.

**CPU fallback**: with no GPU, Ollama runs on CPU. The stack still works; 7B
generation is slower (minutes per stage). Nothing requires a GPU on the dev
laptop.

**Switching machine after first run**: copy `.env`, change the `*_MODEL`
lines, `ollama pull` the new model, `docker compose up -d codewiki`. The
overview a 7B machine produced can be regenerated — or reused as-is — by the
stronger machine's HLD/LLD stages.

---

## 6. Limits

- The **grounding validator** checks references (files, env vars, datastores),
  not architectural correctness. It flags fabricated files/APIs/datastores; it
  cannot tell you a real component was described wrongly.
- Per-sentence citations (the stricter FACT/INFERRED tagging on every claim)
  are **not** implemented — the pipeline tags at the block level in prompts and
  validates references deterministically.
- The bin and the job list are **in-memory** (no database); a backend restart
  clears them. Generated documents on the shared volume survive.
- `overview.json` caps `components` at 120, `modules` at 60, `dependency_edges`
  at 300 (`IR_MAX_*` env overrides) so HLD/LLD prompts stay bounded on small
  context windows; raise them for large-context models.
