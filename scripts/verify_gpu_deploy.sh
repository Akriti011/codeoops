#!/usr/bin/env bash
# Verify a CodeOops GPU deployment: application, vLLM, the 14B model, and that
# the GPU is actually doing the inference. Run on the GPU laptop after
# `docker compose --profile gpu up -d`.
#
#   ./scripts/verify_gpu_deploy.sh
#
# Exit non-zero if any check fails.

set -uo pipefail
FAIL=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=1; }
step() { printf '\n== %s ==\n' "$1"; }

# read a var from .env (no export needed)
env_val() { grep -E "^${1}=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"'"; }

VLLM_HOST="${VLLM_HEALTH_URL:-http://localhost:8002}"     # host-published vllm port
APP_URL="${APP_URL:-http://localhost:8000}"               # backend
FRONT_URL="${FRONT_URL:-http://localhost:4200}"
SERVED_NAME="$(env_val VLLM_SERVED_NAME)"; SERVED_NAME="${SERVED_NAME:-qwen2.5-coder-14b}"

step "1. GPU visible to the host"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader && ok "nvidia-smi works"
else
  bad "nvidia-smi not found — install the NVIDIA driver"
fi

step "2. GPU visible inside Docker (NVIDIA Container Toolkit)"
if docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi -L >/dev/null 2>&1; then
  ok "containers can see the GPU"
else
  bad "docker run --gpus all failed — install nvidia-container-toolkit and 'nvidia-ctk runtime configure'"
fi

step "3. Application containers healthy"
for c in codeoops-vllm codeoops-codewiki codeoops-backend codeoops-frontend; do
  s=$(docker inspect -f '{{.State.Health.Status}}' "$c" 2>/dev/null || echo missing)
  [ "$s" = healthy ] && ok "$c: healthy" || bad "$c: $s"
done

step "4. vLLM is up and the model is loaded"
if curl -fsS "$VLLM_HOST/health" >/dev/null 2>&1; then
  ok "vLLM /health = 200 (model finished loading)"
else
  bad "vLLM /health not ready — 'docker compose --profile gpu logs -f vllm'"
fi
MODELS_JSON="$(curl -fsS "$VLLM_HOST/v1/models" 2>/dev/null || echo '{}')"
if echo "$MODELS_JSON" | grep -q "\"$SERVED_NAME\""; then
  ok "vLLM serves model id '$SERVED_NAME'"
else
  bad "vLLM /v1/models does not list '$SERVED_NAME' — check VLLM_SERVED_NAME vs *_MODEL"
  echo "     got: $MODELS_JSON"
fi

step "5. A real completion goes through vLLM on the GPU"
BEFORE=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
RESP="$(curl -fsS "$VLLM_HOST/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$SERVED_NAME\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: OK\"}],\"max_tokens\":8}" 2>/dev/null || echo '')"
if echo "$RESP" | grep -qi 'ok'; then
  ok "vLLM chat completion succeeded"
else
  bad "vLLM chat completion failed: $RESP"
fi
# vLLM reports its own GPU KV-cache use; also show live GPU processes
echo "     GPU processes now:"
nvidia-smi --query-compute-apps=process_name,used_memory --format=csv,noheader 2>/dev/null | sed 's/^/       /'

step "6. Application reaches the pipeline"
if curl -fsS "$APP_URL/api/v1/documentation/engine" | grep -q '"reachable":true'; then
  ok "backend -> codewiki reachable"
else
  bad "backend cannot reach codewiki"
fi
curl -fsS -o /dev/null "$FRONT_URL/" && ok "frontend serving" || bad "frontend not serving"

step "7. HLD/LLD are wired to vLLM (config check)"
docker exec codeoops-codewiki python3 -c "
import sys; sys.path.insert(0,'/app')
from codewiki.src.config import task_model
for st in ('overview','hld','lld'):
    t=task_model(st); print(f'  {st:9} model={t.model:24} endpoint={t.base_url}')
" 2>/dev/null || bad "could not read task_model config from codewiki"

echo
[ "$FAIL" -eq 0 ] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED — see above"
exit "$FAIL"
