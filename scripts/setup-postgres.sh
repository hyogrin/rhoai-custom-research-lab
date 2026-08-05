#!/bin/bash
# =============================================================================
# Deploy PostgreSQL + pgvector on OpenShift and initialize the research DB
# =============================================================================
# Usage:
#   ./scripts/setup-postgres.sh                  # Deploy on cluster
#   ./scripts/setup-postgres.sh --local          # Local docker only
#   ./scripts/setup-postgres.sh --connect-only   # Just port-forward (already deployed)
#
# Prerequisites:
#   - oc CLI logged in to your cluster
#   - or Docker/Podman for local mode
# =============================================================================

set -euo pipefail

NAMESPACE="${NAMESPACE:-doc-research-lab}"
PG_USER="${PG_USER:-research}"
PG_PASSWORD="${PG_PASSWORD:-research}"
PG_DB="${PG_DB:-research_db}"
PG_PORT="${PG_PORT:-5432}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ---------------------------------------------------------------------------
# Local mode (Docker/Podman)
# ---------------------------------------------------------------------------
setup_local() {
    info "Starting PostgreSQL + pgvector locally via docker compose..."
    cd "$PROJECT_ROOT"
    docker compose up -d
    info "Waiting for PostgreSQL to be ready..."
    for i in $(seq 1 30); do
        if docker compose exec postgres pg_isready -U "$PG_USER" -d "$PG_DB" &>/dev/null; then
            break
        fi
        sleep 1
    done
    info "Running DDL initialization..."
    docker compose exec -T postgres psql -U "$PG_USER" -d "$PG_DB" < "$SCRIPT_DIR/init-postgres.sql"
    info "Local PostgreSQL ready!"
    echo ""
    echo "  POSTGRES_URL=postgresql://${PG_USER}:${PG_PASSWORD}@localhost:${PG_PORT}/${PG_DB}"
    echo ""
    info "Add this to your .env file."
}

# ---------------------------------------------------------------------------
# Cluster mode (OpenShift)
# ---------------------------------------------------------------------------
setup_cluster() {
    info "Deploying PostgreSQL + pgvector on OpenShift namespace: $NAMESPACE"

    # Ensure namespace exists
    oc get namespace "$NAMESPACE" &>/dev/null || oc new-project "$NAMESPACE"

    # Create secret for credentials
    oc create secret generic postgres-credentials \
        --from-literal=POSTGRES_USER="$PG_USER" \
        --from-literal=POSTGRES_PASSWORD="$PG_PASSWORD" \
        --from-literal=POSTGRES_DB="$PG_DB" \
        -n "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -

    # Deploy PostgreSQL with pgvector
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
            command: ["pg_isready", "-U", "research", "-d", "research_db"]
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

    info "Waiting for PostgreSQL pod to be ready..."
    oc wait --for=condition=ready pod -l app=postgres -n "$NAMESPACE" --timeout=120s

    info "Running DDL initialization..."
    PG_POD=$(oc get pod -l app=postgres -n "$NAMESPACE" -o jsonpath='{.items[0].metadata.name}')
    oc exec -n "$NAMESPACE" "$PG_POD" -i -- psql -U "$PG_USER" -d "$PG_DB" < "$SCRIPT_DIR/init-postgres.sql"

    info "PostgreSQL deployed and initialized on cluster!"
    echo ""
    echo "  In-cluster URL (for backend pods):"
    echo "    POSTGRES_URL=postgresql://${PG_USER}:${PG_PASSWORD}@postgres.${NAMESPACE}.svc.cluster.local:5432/${PG_DB}"
    echo ""
    echo "  For local development (port-forward):"
    echo "    oc port-forward svc/postgres ${PG_PORT}:5432 -n ${NAMESPACE}"
    echo "    POSTGRES_URL=postgresql://${PG_USER}:${PG_PASSWORD}@localhost:${PG_PORT}/${PG_DB}"
    echo ""
}

# ---------------------------------------------------------------------------
# Connect-only mode (port-forward to existing deployment)
# ---------------------------------------------------------------------------
connect_only() {
    info "Port-forwarding to existing PostgreSQL in namespace: $NAMESPACE"
    echo ""
    echo "  POSTGRES_URL=postgresql://${PG_USER}:${PG_PASSWORD}@localhost:${PG_PORT}/${PG_DB}"
    echo ""
    info "Press Ctrl+C to stop port-forward."
    oc port-forward svc/postgres "${PG_PORT}:5432" -n "$NAMESPACE"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
case "${1:-cluster}" in
    --local)
        setup_local
        ;;
    --connect-only)
        connect_only
        ;;
    *)
        setup_cluster
        ;;
esac
