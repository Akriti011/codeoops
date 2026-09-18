#!/usr/bin/env bash
# CodeOops — one-command startup and readiness check.
#
# Validates prerequisites, starts the stack (building only what isn't
# already present as an image — so this works identically whether the
# images came from `docker compose build` or a `docker load` of the
# distributed .tar archives), and reports health clearly. Never hides a
# failure behind a generic "done" — every check prints its own pass/fail.
#
# See DOCKER_DEPLOYMENT.md for what each step means and how to fix failures.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# Every model name any stage might use, pulled from .env (per-stage overrides
# + the MAIN_MODEL fallback). Whatever is set there is what must be present in
# Ollama — this check follows the config, it does not hardcode a model.
_env_val() { grep -E "^${1}=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"'" ; }
REQUIRED_MODELS="$(
  for k in MAIN_MODEL OVERVIEW_MODEL HLD_MODEL LLD_MODEL CLUSTER_MODEL FALLBACK_MODEL_1; do
    v="$(_env_val "$k")"; [ -n "$v" ] && echo "$v"
  done | sort -u
)"
[ -z "$REQUIRED_MODELS" ] && REQUIRED_MODELS="qwen2.5-coder:7b"
IMAGES=(codeoops-engine codeoops-backend codeoops-frontend)
FAIL=0
FRONTEND=1

for arg in "$@"; do
  case "$arg" in
    --backend-only) FRONTEND=0 ;;
    -h|--help)
      echo "Usage: ./start.sh [--backend-only]"
      echo "  --backend-only   Start codewiki + backend only, skip the Angular frontend."
      exit 0
      ;;
  esac
done

ok()   { printf '  \033[32m\xe2\x9c\x93\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
err()  { printf '  \033[31m\xe2\x9c\x97\033[0m %s\n' "$1"; FAIL=1; }
step() { printf '\n== %s ==\n' "$1"; }

step "1. Docker"
if ! command -v docker >/dev/null 2>&1; then
  err "docker CLI not found. Install Docker Desktop (Mac/Windows) or Docker Engine (Linux)."
else
  ok "docker CLI found ($(docker --version))"
fi

if ! docker info >/dev/null 2>&1; then
  err "Docker daemon not reachable — is Docker Desktop / dockerd running?"
else
  ok "Docker daemon reachable"
fi

if ! docker compose version >/dev/null 2>&1; then
  err "docker compose (v2 plugin) not found."
else
  ok "docker compose found ($(docker compose version --short 2>/dev/null))"
fi

if [ "$FAIL" -eq 1 ]; then
  echo ""
  echo "Fix the above before continuing."
  exit 1
fi

step "2. Environment"
if [ ! -f .env ]; then
  warn ".env not found — creating from .env.example (defaults match the tuned, resource-conscious config)"
  cp .env.example .env
else
  ok ".env present"
fi

step "3. Ollama (native on the host — not a container in this stack)"
if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  ok "Ollama reachable at localhost:11434"
  _tags="$(curl -s http://localhost:11434/api/tags)"
  while IFS= read -r m; do
    [ -z "$m" ] && continue
    if echo "$_tags" | grep -q "\"${m}\""; then
      ok "Model ${m} present"
    else
      err "Model ${m} (from .env) not found in Ollama."
      echo "      Run: ollama pull ${m}"
      echo "      (or edit the matching *_MODEL / MAIN_MODEL line in .env to a model you have —"
      echo "       run 'python3 scripts/model_advisor.py' for a hardware-based recommendation.)"
    fi
  done <<< "$REQUIRED_MODELS"
else
  err "Ollama not reachable at localhost:11434."
  echo "      Start it: 'ollama serve', or launch the Ollama.app menu-bar app on macOS."
  echo "      The stack will still start, but every documentation generation will fail until Ollama is up."
fi

step "4. Images"
for img in "${IMAGES[@]}"; do
  if docker image inspect "${img}:latest" >/dev/null 2>&1; then
    ok "${img}:latest present"
  else
    warn "${img}:latest not built/loaded yet — 'docker compose up' will build it from source now"
  fi
done

step "5. Starting the stack"
SERVICES="codewiki backend"
[ "$FRONTEND" -eq 1 ] && SERVICES="codewiki backend frontend"
if ! docker compose up -d $SERVICES; then
  err "docker compose up failed — see the output above."
  exit 1
fi

step "6. Waiting for health"
# Compose service keys stay the internal DNS names (codewiki/backend/frontend
# — see docker-compose.yml); container_name is what's actually visible in
# `docker ps` and is not always a plain "codeoops-<service>" derivation, so
# this maps the one exception explicitly instead of assuming the pattern.
_container_name() { [ "$1" = "codewiki" ] && echo "codeoops-engine" || echo "codeoops-$1"; }
for service in $SERVICES; do
  healthy=0
  for _ in $(seq 1 30); do
    status=$(docker inspect --format '{{.State.Health.Status}}' "$(_container_name "$service")" 2>/dev/null || echo "unknown")
    if [ "$status" = "healthy" ]; then
      ok "${service} healthy"
      healthy=1
      break
    fi
    sleep 2
  done
  if [ "$healthy" -eq 0 ]; then
    err "${service} did not become healthy in time — check: docker compose logs ${service}"
  fi
done

step "7. Backend -> documentation engine connectivity"
ENGINE=$(curl -s http://localhost:8000/api/v1/documentation/engine 2>/dev/null || echo "")
if echo "$ENGINE" | grep -q '"reachable":true'; then
  ok "backend confirms the documentation engine is reachable: $ENGINE"
else
  err "backend cannot reach the documentation engine: ${ENGINE:-no response}"
fi

echo ""
if [ "$FAIL" -eq 1 ]; then
  echo "Startup finished with warnings/errors above — see DOCKER_DEPLOYMENT.md > Troubleshooting."
  exit 1
fi

echo "CodeOops is up:"
echo "  Backend:   http://localhost:8000  (docs: http://localhost:8000/docs)"
echo "  Engine:    http://localhost:8001"
[ "$FRONTEND" -eq 1 ] && echo "  Frontend:  http://localhost:4200"
echo ""
echo "Stop with:    docker compose down"
echo "Logs with:    docker compose logs -f [codewiki|backend|frontend]"
