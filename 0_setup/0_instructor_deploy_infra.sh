#!/usr/bin/env bash
# =============================================================================
# Instructor Setup: Deploy SearXNG to OpenShift
# =============================================================================
# This script deploys SearXNG (web search backend) to an OpenShift cluster
# so that workshop participants only need to set the URL in .env.
#
# Prerequisites:
#   - oc CLI logged in with cluster-admin or project-admin privileges
#   - Target project/namespace already exists (or will be created)
#
# Usage:
#   chmod +x 0_setup/0_instructor_deploy_infra.sh
#   ./0_setup/0_instructor_deploy_infra.sh
#
# After running, share the output URL with participants for their .env files.


# =============================================================================

set -euo pipefail

NAMESPACE="${NAMESPACE:-mcp-servers}"

echo "========================================="
echo " Instructor Infrastructure Deployment"
echo "========================================="
echo ""
echo "  Namespace:  ${NAMESPACE}"
echo ""

# --- 1. Create namespace ---
echo "[1/4] Creating namespace '${NAMESPACE}'..."
oc new-project "${NAMESPACE}" 2>/dev/null || oc project "${NAMESPACE}"
echo ""

# --- 2. Deploy SearXNG ---
echo "[2/4] Deploying SearXNG..."
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

# --- 3. Expose routes ---
echo "[3/4] Exposing routes..."
oc expose svc/mcp-searxng -n "${NAMESPACE}" 2>/dev/null || true
echo ""

# --- 4. Wait and print URLs ---
echo "[4/4] Waiting for rollouts..."
oc rollout status deployment/mcp-searxng -n "${NAMESPACE}" --timeout=180s || \
  echo "  ⚠ SearXNG rollout still in progress — check with: oc rollout status deployment/mcp-searxng -n ${NAMESPACE}"
echo ""

SEARXNG_HOST="$(oc get route mcp-searxng -n "${NAMESPACE}" -o jsonpath='{.spec.host}')"

echo "========================================="
echo " Deployment Complete!"
echo "========================================="
echo ""
echo " Share this value with workshop participants"
echo " -- copy into .env --"
echo ""
echo "   SEARXNG_URL=http://${SEARXNG_HOST}"
echo ""
echo " Participants add this to their .env file."
echo "========================================="
