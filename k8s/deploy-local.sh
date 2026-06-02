#!/usr/bin/env bash
# =============================================================================
# whisperTrans — Local Kubernetes Cluster Setup & Test Script
# Uses: kind (Kubernetes in Docker) + kubectl
#
# Usage:
#   ./k8s/deploy-local.sh             # full setup + deploy
#   ./k8s/deploy-local.sh --teardown  # destroy the cluster
#   ./k8s/deploy-local.sh --status    # print pod/service status
# =============================================================================
set -euo pipefail

CLUSTER_NAME="whispertrans"
IMAGE_NAME="whispertrans:latest"
NAMESPACE="whispertrans"
K8S_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$K8S_DIR")"

# ─── Colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ─── Helpers ──────────────────────────────────────────────────────────────────
check_deps() {
  for cmd in docker kind kubectl; do
    command -v "$cmd" &>/dev/null || error "'$cmd' not found. Please install it first."
  done
  docker info &>/dev/null || error "Docker daemon is not running. Start Docker Desktop and retry."
}

load_env() {
  local env_file="$ROOT_DIR/.env"
  if [[ -f "$env_file" ]]; then
    info "Loading .env from $env_file"
    # Export only GOOGLE_API_KEY (and other relevant vars)
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  else
    warn ".env not found — GOOGLE_API_KEY must be set in environment"
  fi

  if [[ -z "${GOOGLE_API_KEY:-}" ]]; then
    error "GOOGLE_API_KEY is not set. Create a .env file or export the variable."
  fi
}

# ─── Teardown ─────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--teardown" ]]; then
  info "Deleting kind cluster '$CLUSTER_NAME'..."
  kind delete cluster --name "$CLUSTER_NAME" || true
  info "Cluster deleted."
  exit 0
fi

# ─── Status ───────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--status" ]]; then
  echo ""
  echo "=== Pods ==="
  kubectl -n "$NAMESPACE" get pods -o wide
  echo ""
  echo "=== Services ==="
  kubectl -n "$NAMESPACE" get svc
  echo ""
  echo "=== HPA ==="
  kubectl -n "$NAMESPACE" get hpa 2>/dev/null || true
  echo ""
  echo "=== Endpoints ==="
  echo "  API Gateway : http://localhost:8000"
  echo "  API Docs    : http://localhost:8000/docs  (only if DEBUG=true)"
  echo "  Gradio UI   : http://localhost:7860"
  exit 0
fi

# ═════════════════════════════════════════════════════════════════════════════
# FULL DEPLOY
# ═════════════════════════════════════════════════════════════════════════════

check_deps
load_env

# ─── Step 1: Create kind cluster ──────────────────────────────────────────────
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
  info "Cluster '$CLUSTER_NAME' already exists — skipping creation."
else
  info "Creating kind cluster '$CLUSTER_NAME' (this takes ~30s)..."
  kind create cluster \
    --name "$CLUSTER_NAME" \
    --config "$K8S_DIR/kind-cluster.yaml" \
    --wait 120s
  info "Cluster created."
fi

# Set kubectl context
kubectl config use-context "kind-${CLUSTER_NAME}"

# ─── Step 2: Build Docker image ───────────────────────────────────────────────
info "Building Docker image '$IMAGE_NAME' (first build is slow — Torch + Whisper)..."
docker build -t "$IMAGE_NAME" "$ROOT_DIR"
info "Image built."

# ─── Step 3: Load image into kind ─────────────────────────────────────────────
info "Loading image into kind cluster (avoids registry)..."
kind load docker-image "$IMAGE_NAME" --name "$CLUSTER_NAME"
info "Image loaded."

# ─── Step 4: Apply manifests ──────────────────────────────────────────────────
info "Applying Kubernetes manifests..."

kubectl apply -f "$K8S_DIR/namespace.yaml"
kubectl apply -f "$K8S_DIR/configmap.yaml"

# Create secret (idempotent)
kubectl -n "$NAMESPACE" delete secret translation-secrets --ignore-not-found
kubectl -n "$NAMESPACE" create secret generic translation-secrets \
  --from-literal=google-api-key="$GOOGLE_API_KEY"

kubectl apply -f "$K8S_DIR/storage/pvc.yaml"
kubectl apply -f "$K8S_DIR/redis/"
kubectl apply -f "$K8S_DIR/api/"
kubectl apply -f "$K8S_DIR/worker/"
kubectl apply -f "$K8S_DIR/ui/"

info "Manifests applied."

# ─── Step 5: Wait for Redis ───────────────────────────────────────────────────
info "Waiting for Redis to be ready..."
kubectl -n "$NAMESPACE" rollout status statefulset/redis --timeout=120s

# ─── Step 6: Wait for API ─────────────────────────────────────────────────────
info "Waiting for API to be ready..."
kubectl -n "$NAMESPACE" rollout status deployment/translation-api --timeout=180s

# ─── Step 7: Wait for Worker ──────────────────────────────────────────────────
info "Waiting for Worker to be ready..."
kubectl -n "$NAMESPACE" rollout status deployment/translation-worker --timeout=180s

# ─── Step 8: Wait for UI ──────────────────────────────────────────────────────
info "Waiting for UI to be ready..."
kubectl -n "$NAMESPACE" rollout status deployment/translation-ui --timeout=120s

# ─── Step 9: Smoke test ───────────────────────────────────────────────────────
echo ""
info "Running smoke tests..."

# Retry loop for API
MAX_RETRIES=12
for i in $(seq 1 $MAX_RETRIES); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ 2>/dev/null || true)
  if [[ "$STATUS" == "200" ]]; then
    info "Root endpoint OK (HTTP 200) ✓"
    break
  fi
  if [[ $i -eq $MAX_RETRIES ]]; then
    warn "Root endpoint did not respond with 200 after ${MAX_RETRIES} retries"
    warn "Check logs: kubectl -n $NAMESPACE logs -l app=translation-api"
  fi
  warn "Attempt $i/$MAX_RETRIES — API not ready yet (got $STATUS), waiting 5s..."
  sleep 5
done

HEALTH=$(curl -s http://localhost:8000/api/v1/health/ 2>/dev/null || echo '{}')
echo "  Health response: $HEALTH"

REDIS_HEALTH=$(curl -s http://localhost:8000/api/v1/health/redis 2>/dev/null || echo '{}')
echo "  Redis health:    $REDIS_HEALTH"

WORKER_HEALTH=$(curl -s http://localhost:8000/api/v1/health/workers 2>/dev/null || echo '{}')
echo "  Worker health:   $WORKER_HEALTH"

# ─── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  whisperTrans cluster is up and running! 🚀    ${NC}"
echo -e "${GREEN}════════════════════════════════════════════════${NC}"
echo ""
echo "  API Gateway : http://localhost:8000"
echo "  API Docs    : http://localhost:8000/docs  (set DEBUG=true in configmap to enable)"
echo "  Gradio UI   : http://localhost:7860"
echo ""
echo "  Useful commands:"
echo "    kubectl -n $NAMESPACE get pods"
echo "    kubectl -n $NAMESPACE logs -l app=translation-worker -f"
echo "    kubectl -n $NAMESPACE port-forward svc/translation-api 8000:80"
echo "    ./k8s/deploy-local.sh --status"
echo "    ./k8s/deploy-local.sh --teardown"
echo ""
