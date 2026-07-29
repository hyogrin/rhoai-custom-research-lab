#!/usr/bin/env bash
# =============================================================================
# Instructor Setup: Deploy MinIO and SearXNG to OpenShift
# =============================================================================
# This script deploys shared infrastructure services (MinIO + SearXNG) to an
# OpenShift cluster so that workshop participants only need to set URLs in .env.
#
# Prerequisites:
#   - oc CLI logged in with cluster-admin or project-admin privileges
#   - Target project/namespace already exists (or will be created)
#
# Usage:
#   chmod +x 0_setup/instructor_deploy_infra.sh
#   ./0_setup/instructor_deploy_infra.sh
#
# After running, share the output URLs with participants for their .env files.


# =============================================================================

set -euo pipefail

NAMESPACE="${NAMESPACE:-mcp-servers}"
MINIO_USER="${MINIO_USER:-minioadmin}"
MINIO_PASS="${MINIO_PASS:-minioadmin}"

echo "========================================="
echo " Instructor Infrastructure Deployment"
echo "========================================="
echo ""
echo "  Namespace:  ${NAMESPACE}"
echo "  MinIO User: ${MINIO_USER}"
echo ""

# --- 1. Create namespace ---
echo "[1/6] Creating namespace '${NAMESPACE}'..."
oc new-project "${NAMESPACE}" 2>/dev/null || oc project "${NAMESPACE}"
echo ""

# --- 2. Deploy MinIO ---
echo "[2/6] Deploying MinIO..."
oc apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: minio-data
  namespace: ${NAMESPACE}
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: minio
  namespace: ${NAMESPACE}
  labels:
    app: minio
spec:
  replicas: 1
  selector:
    matchLabels:
      app: minio
  template:
    metadata:
      labels:
        app: minio
    spec:
      containers:
        - name: minio
          image: quay.io/minio/minio:latest
          command: ["minio"]
          args: ["server", "/data", "--console-address", ":9001"]
          ports:
            - containerPort: 9000
            - containerPort: 9001
          env:
            - name: MINIO_ROOT_USER
              value: "${MINIO_USER}"
            - name: MINIO_ROOT_PASSWORD
              value: "${MINIO_PASS}"
          volumeMounts:
            - name: data
              mountPath: /data
          readinessProbe:
            httpGet:
              path: /minio/health/ready
              port: 9000
            initialDelaySeconds: 10
            periodSeconds: 10
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: minio-data
---
apiVersion: v1
kind: Service
metadata:
  name: minio
  namespace: ${NAMESPACE}
  labels:
    app: minio
spec:
  ports:
    - name: api
      port: 9000
      targetPort: 9000
    - name: console
      port: 9001
      targetPort: 9001
  selector:
    app: minio
EOF
echo ""

# --- 3. Create MinIO bucket ---
echo "[3/6] Creating 'documents' bucket..."
oc delete job/minio-init -n "${NAMESPACE}" 2>/dev/null || true
oc apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: minio-init
  namespace: ${NAMESPACE}
spec:
  backoffLimit: 3
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: mc
          image: quay.io/minio/mc:latest
          command:
            - /bin/sh
            - -c
            - |
              until mc alias set local http://minio:9000 "${MINIO_USER}" "${MINIO_PASS}"; do
                sleep 2
              done
              mc mb --ignore-existing local/documents
              echo "Bucket 'documents' ready."
EOF
echo ""

# --- 4. Deploy SearXNG ---
echo "[4/6] Deploying SearXNG..."
oc apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-searxng
  namespace: ${NAMESPACE}
  labels:
    app: mcp-searxng
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mcp-searxng
  template:
    metadata:
      labels:
        app: mcp-searxng
    spec:
      containers:
        - name: searxng
          image: dandehoon/searxng-mcp:latest
          ports:
            - containerPort: 8000
          env:
            - name: SEARXNG_MCP_TRANSPORT
              value: "http"
            - name: SEARXNG_MCP_PATH
              value: "/mcp"
            - name: SEARXNG_MCP_MAX_RESULTS
              value: "10"
            - name: SEARXNG_LANGUAGE
              value: "en"
          readinessProbe:
            httpGet:
              path: /
              port: 8000
            initialDelaySeconds: 15
            periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-searxng
  namespace: ${NAMESPACE}
  labels:
    app: mcp-searxng
spec:
  ports:
    - port: 8888
      targetPort: 8000
  selector:
    app: mcp-searxng
EOF
echo ""

# --- 5. Expose routes ---
echo "[5/6] Exposing routes..."
oc expose svc/minio --port=api --name=minio-api -n "${NAMESPACE}" 2>/dev/null || true
oc expose svc/minio --port=console --name=minio-console -n "${NAMESPACE}" 2>/dev/null || true
oc expose svc/mcp-searxng -n "${NAMESPACE}" 2>/dev/null || true
echo ""

# --- 6. Wait and print URLs ---
echo "[6/6] Waiting for rollouts..."
oc rollout status deployment/minio -n "${NAMESPACE}" --timeout=180s
oc rollout status deployment/mcp-searxng -n "${NAMESPACE}" --timeout=180s || \
  echo "  ⚠ SearXNG rollout still in progress — check with: oc rollout status deployment/mcp-searxng -n ${NAMESPACE}"
echo ""

MINIO_HOST="$(oc get route minio-api -n "${NAMESPACE}" -o jsonpath='{.spec.host}')"
SEARXNG_HOST="$(oc get route mcp-searxng -n "${NAMESPACE}" -o jsonpath='{.spec.host}')"

echo "========================================="
echo " Deployment Complete!"
echo "========================================="
echo ""
echo " Share these values with workshop participants"
echo " -- copy into .env --"
echo ""
echo "   MINIO_ENDPOINT=${MINIO_HOST}"
echo "   MINIO_ACCESS_KEY=${MINIO_USER}"
echo "   MINIO_SECRET_KEY=${MINIO_PASS}"
echo "   MINIO_BUCKET=documents"
echo "   MINIO_SECURE=false"
echo "   SEARXNG_URL=http://${SEARXNG_HOST}"
echo ""
echo " Participants add these to their .env file."
echo "========================================="
