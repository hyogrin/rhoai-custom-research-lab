#!/bin/bash
# =============================================================================
# Lab Setup — Python Dependencies + PostgreSQL
# =============================================================================
# Usage:
#   ./scripts/setup.sh                # Auto-detect environment, provision PostgreSQL
#   ./scripts/setup.sh --local        # Force local Docker mode
#   ./scripts/setup.sh --cluster      # Force cluster (OpenShift) mode
#   ./scripts/setup.sh --connect-only # Port-forward to existing cluster PostgreSQL
#
# What this script does:
#   1. Detects environment (cluster if `oc whoami` succeeds, local otherwise)
#   2. Provisions PostgreSQL + pgvector + DDL initialization
#   3. Auto-updates .env with POSTGRES_URL
#   4. Checks for OpenShell availability (no install — admin prerequisite)
#   5. Validates connectivity
#
# Prerequisites:
#   - Docker Desktop (local mode)
#   - oc CLI logged in (cluster mode)
#   - OpenShell: must be pre-installed by cluster admin (optional, for Claim-Evidence Graph)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${PROJECT_ROOT}/.env"

# Load existing .env if present
if [ -f "$ENV_FILE" ]; then
    set +e
    source <(grep -v '^\s*#' "$ENV_FILE" | grep -v '^\s*$' | sed 's/^/export /')
    set -e
fi

NAMESPACE="${NAMESPACE:-doc-research-lab}"
PG_USER="${PG_USER:-research}"
PG_PASSWORD="${PG_PASSWORD:-research}"
PG_DB="${PG_DB:-research_db}"
PG_PORT="${PG_PORT:-5432}"
OPENSHELL_GATEWAY_PORT="${OPENSHELL_GATEWAY_PORT:-8080}"

# Flags
MODE=""
CONNECT_ONLY=false

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${CYAN}[INFO] ─── $* ───${NC}"; }

# =============================================================================
# .env auto-update helper (idempotent)
# =============================================================================
set_env_var() {
    local key="$1" value="$2"
    if [ ! -f "$ENV_FILE" ]; then
        cp "${PROJECT_ROOT}/sample.env" "$ENV_FILE" 2>/dev/null || touch "$ENV_FILE"
    fi
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        sed -i.bak "s|^${key}=.*|${key}=${value}|" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
    else
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
    info "  .env updated: ${key}=${value}"
}

# =============================================================================
# Environment detection
# =============================================================================
detect_environment() {
    if [ -n "$MODE" ]; then
        return
    fi
    if oc whoami &>/dev/null; then
        MODE="cluster"
        local cluster_url
        cluster_url=$(oc whoami --show-server 2>/dev/null || echo "unknown")
        info "Environment: cluster (${cluster_url})"
    else
        MODE="local"
        info "Environment: local (oc not logged in — using Docker)"
    fi
}

# =============================================================================
# PostgreSQL — Local
# =============================================================================
setup_postgres_local() {
    section "PostgreSQL (local Docker)"
    cd "$PROJECT_ROOT"
    docker compose up -d postgres

    info "Waiting for PostgreSQL..."
    for i in $(seq 1 30); do
        if docker compose exec postgres pg_isready -U "$PG_USER" -d "$PG_DB" &>/dev/null; then
            break
        fi
        sleep 1
    done

    if ! docker compose exec postgres pg_isready -U "$PG_USER" -d "$PG_DB" &>/dev/null; then
        error "PostgreSQL not ready after 30s"
        exit 1
    fi

    info "Running DDL initialization (pgvector + lab tables)..."
    docker compose exec -T postgres psql -U "$PG_USER" -d "$PG_DB" < "$SCRIPT_DIR/init-postgres.sql"

    local pg_url="postgresql://${PG_USER}:${PG_PASSWORD}@localhost:${PG_PORT}/${PG_DB}"
    set_env_var "POSTGRES_URL" "$pg_url"
    info "PostgreSQL ready (local)"
}

# =============================================================================
# PostgreSQL — Cluster
# =============================================================================
setup_postgres_cluster() {
    section "PostgreSQL (OpenShift: ${NAMESPACE})"

    oc get namespace "$NAMESPACE" &>/dev/null || oc new-project "$NAMESPACE"

    oc create secret generic postgres-credentials \
        --from-literal=POSTGRES_USER="$PG_USER" \
        --from-literal=POSTGRES_PASSWORD="$PG_PASSWORD" \
        --from-literal=POSTGRES_DB="$PG_DB" \
        -n "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -

    cat <<EOF | oc apply -n "$NAMESPACE" -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
  labels:
    app: postgres
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: pgvector/pgvector:pg16
        ports:
        - containerPort: 5432
        env:
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        envFrom:
        - secretRef:
            name: postgres-credentials
        volumeMounts:
        - name: pgdata
          mountPath: /var/lib/postgresql/data
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        readinessProbe:
          exec:
            command: ["pg_isready", "-U", "$PG_USER", "-d", "$PG_DB"]
          initialDelaySeconds: 5
          periodSeconds: 5
      volumes:
      - name: pgdata
        persistentVolumeClaim:
          claimName: postgres-pvc
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-pvc
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 10Gi
---
apiVersion: v1
kind: Service
metadata:
  name: postgres
spec:
  selector:
    app: postgres
  ports:
  - port: 5432
    targetPort: 5432
EOF

    info "Waiting for PostgreSQL pod..."
    oc wait --for=condition=ready pod -l app=postgres -n "$NAMESPACE" --timeout=120s

    info "Running DDL initialization (pgvector + lab tables)..."
    PG_POD=$(oc get pod -l app=postgres -n "$NAMESPACE" -o jsonpath='{.items[0].metadata.name}')
    oc exec -n "$NAMESPACE" "$PG_POD" -i -- psql -U "$PG_USER" -d "$PG_DB" < "$SCRIPT_DIR/init-postgres.sql"

    local pg_url="postgresql://${PG_USER}:${PG_PASSWORD}@localhost:${PG_PORT}/${PG_DB}"
    set_env_var "POSTGRES_URL" "$pg_url"

    info "Starting port-forward (background)..."
    oc port-forward svc/postgres "${PG_PORT}:5432" -n "$NAMESPACE" &>/dev/null &
    info "PostgreSQL ready (cluster, port-forwarded to localhost:${PG_PORT})"
}

# =============================================================================
# Connect-only mode (port-forward to existing PostgreSQL)
# =============================================================================
connect_existing() {
    section "Connecting to existing PostgreSQL (${NAMESPACE})"

    local pg_url="postgresql://${PG_USER}:${PG_PASSWORD}@localhost:${PG_PORT}/${PG_DB}"
    set_env_var "POSTGRES_URL" "$pg_url"
    info "Port-forwarding PostgreSQL..."
    oc port-forward svc/postgres "${PG_PORT}:5432" -n "$NAMESPACE" &>/dev/null &
    sleep 2
}

# =============================================================================
# OpenShell check (detect only — no installation)
# =============================================================================
check_openshell() {
    section "OpenShell (pre-installed check)"

    local OPENSHELL_NS="${OPENSHELL_SANDBOX_NAMESPACE:-openshell}"

    if [ "$MODE" = "local" ]; then
        if curl -sf "http://127.0.0.1:${OPENSHELL_GATEWAY_PORT}/healthz" >/dev/null 2>&1; then
            set_env_var "OPENSHELL_GATEWAY_URL" "http://127.0.0.1:${OPENSHELL_GATEWAY_PORT}"
            info "OpenShell gateway detected (localhost:${OPENSHELL_GATEWAY_PORT})"
            return 0
        fi
    else
        if oc get svc openshell -n "$OPENSHELL_NS" &>/dev/null; then
            # Verify Agent Sandbox CRDs are present
            if ! oc get crd sandboxes.agents.x-k8s.io &>/dev/null; then
                warn "OpenShell gateway found but Agent Sandbox CRDs are missing."
                warn "  Run: ./scripts/install-openshell.sh  (requires cluster-admin)"
                return 1
            fi

            set_env_var "OPENSHELL_GATEWAY_URL" "http://127.0.0.1:${OPENSHELL_GATEWAY_PORT}"
            info "OpenShell found in namespace '${OPENSHELL_NS}'"

            # Port-forward (kill any stale forward first)
            pkill -f "port-forward svc/openshell" 2>/dev/null || true
            sleep 1
            oc port-forward svc/openshell "${OPENSHELL_GATEWAY_PORT}:8080" -n "$OPENSHELL_NS" &>/dev/null &
            sleep 2

            # Register gateway if CLI is available and not yet registered
            if command -v openshell &>/dev/null; then
                if ! openshell gateway list 2>/dev/null | grep -q "cluster-forward"; then
                    info "Registering local gateway 'cluster-forward'..."
                    openshell gateway add "http://127.0.0.1:${OPENSHELL_GATEWAY_PORT}" \
                        --name cluster-forward --local 2>/dev/null || true
                fi
            fi

            info "OpenShell gateway ready (port-forwarded to localhost:${OPENSHELL_GATEWAY_PORT})"
            return 0
        fi
    fi

    warn "OpenShell gateway not available."
    warn "  The Claim-Evidence Graph feature requires OpenShell (admin prerequisite)."
    warn "  Install: ./scripts/install-openshell.sh  (requires cluster-admin)"
    warn "  This does NOT affect the core research workflow."
}

# =============================================================================
# Validation
# =============================================================================
validate() {
    section "Validation"
    local all_ok=true

    if pg_isready -h localhost -p "$PG_PORT" -U "$PG_USER" &>/dev/null 2>&1 || \
       docker compose exec postgres pg_isready -U "$PG_USER" -d "$PG_DB" &>/dev/null 2>&1; then
        info "PostgreSQL: connected"
    else
        warn "PostgreSQL: not reachable on localhost:${PG_PORT}"
        all_ok=false
    fi

    if $all_ok; then
        section "Done"
        info "Setup complete. Next: ${BOLD}make backend-start${NC}"
    else
        section "Done (with warnings)"
        warn "PostgreSQL not reachable yet. It may need a moment — retry or check logs."
    fi
}

# =============================================================================
# Parse arguments
# =============================================================================
while [[ $# -gt 0 ]]; do
    case "$1" in
        --local)          MODE="local"; shift ;;
        --cluster)        MODE="cluster"; shift ;;
        --connect-only)   CONNECT_ONLY=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--local|--cluster] [--connect-only]"
            echo ""
            echo "  --local            Force local Docker mode"
            echo "  --cluster          Force cluster (OpenShift) mode"
            echo "  --connect-only     Port-forward to existing cluster PostgreSQL"
            echo ""
            echo "Without flags: auto-detects environment (cluster if oc logged in, local otherwise)"
            exit 0
            ;;
        *) error "Unknown option: $1"; exit 1 ;;
    esac
done

# =============================================================================
# Main
# =============================================================================
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  RHOAI Research Lab — Setup              ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
info "This script provisions: Python deps (via uv) + PostgreSQL + pgvector"
info "OpenShell is an admin prerequisite — detected but NOT installed here."
echo ""

# Ensure .env exists
if [ ! -f "$ENV_FILE" ]; then
    info "Creating .env from sample.env..."
    cp "${PROJECT_ROOT}/sample.env" "$ENV_FILE"
fi

detect_environment
info "Namespace: ${NAMESPACE}"

if $CONNECT_ONLY; then
    connect_existing
    validate
    exit 0
fi

# PostgreSQL (this lab provisions and owns this)
if [ "$MODE" = "local" ]; then
    setup_postgres_local
else
    setup_postgres_cluster
fi

# OpenShell (detect only — admin prerequisite)
check_openshell

validate
