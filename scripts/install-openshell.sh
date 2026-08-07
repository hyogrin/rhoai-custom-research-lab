#!/bin/bash
################################################################################
# OpenShell Installation Script (Admin Prerequisite)
# Installs NVIDIA OpenShell + Agent Sandbox CRDs on OpenShift
#
# This script is an ADMIN prerequisite for the Claim-Evidence Graph feature.
# The core research workflow does NOT require OpenShell.
#
# What this script installs:
#   1. Agent Sandbox CRDs (kubernetes-sigs/agent-sandbox) — required by OpenShell
#   2. NVIDIA OpenShell Helm chart — gateway + sandbox lifecycle manager
#   3. OpenShift SCC binding — privileged SCC for sandbox pods
#
# Current status: Technology Preview (TP)
#   - TLS is disabled (plaintext HTTP gateway)
#   - Unauthenticated client access is allowed (dev/lab convenience)
#   - NOT suitable for production — use OIDC or mTLS for shared clusters
#
# Prerequisites:
#   - OpenShift 4.x cluster with cluster-admin privileges
#   - helm CLI installed
#   - oc CLI logged into the cluster
#
# Post-install (developer workstation):
#   openshell gateway add http://127.0.0.1:8080 --name cluster-forward --local
#   oc port-forward svc/openshell 8080:8080 -n openshell
#
# References:
#   - https://github.com/NVIDIA/OpenShell
#   - https://github.com/kubernetes-sigs/agent-sandbox
#   - https://docs.nvidia.com/openshell/latest/kubernetes/openshift
################################################################################

set -euo pipefail

NAMESPACE="${OPENSHELL_NAMESPACE:-openshell}"
CHART_REPO="oci://ghcr.io/nvidia/openshell/helm-chart"
CHART_VERSION="${OPENSHELL_VERSION:-}"
SANDBOX_CRD_VERSION="${AGENT_SANDBOX_VERSION:-v0.5.2}"
SANDBOX_SA="openshell-sandbox"

# Colors (self-contained — no external dependency)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${CYAN}${BOLD}─── $* ───${NC}"; }

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install, upgrade, or uninstall NVIDIA OpenShell on OpenShift.

Options:
    -n, --namespace NAME         Namespace to install into (default: openshell)
    -v, --version VERSION        Helm chart version (default: latest)
    --sandbox-version VERSION    Agent Sandbox CRD version (default: v0.5.2)
    --uninstall                  Uninstall OpenShell and CRDs
    --status                     Show installation status
    -h, --help                   Show this help

Environment Variables:
    OPENSHELL_NAMESPACE          Override default namespace
    OPENSHELL_VERSION            Override Helm chart version
    AGENT_SANDBOX_VERSION        Override Agent Sandbox CRD version

Examples:
    $(basename "$0")                            # Install with defaults
    $(basename "$0") -v 0.0.99                  # Install specific chart version
    $(basename "$0") --sandbox-version v0.5.2   # Specific CRD version
    $(basename "$0") --status                   # Check status
    $(basename "$0") --uninstall                # Uninstall everything
EOF
    exit 0
}

# =============================================================================
# Prerequisites
# =============================================================================
check_prerequisites() {
    section "Prerequisites"

    if ! command -v oc &>/dev/null; then
        error "oc CLI not found. Install: https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/"
        exit 1
    fi

    if ! oc whoami &>/dev/null; then
        error "Not logged into OpenShift. Run 'oc login' first."
        exit 1
    fi

    local user
    user=$(oc whoami 2>/dev/null)
    info "Logged in as: $user"

    if ! oc auth can-i create crd &>/dev/null; then
        error "cluster-admin required. Current user '$user' cannot create CRDs."
        exit 1
    fi

    if ! command -v helm &>/dev/null; then
        warn "helm CLI not found. Attempting install via brew..."
        if command -v brew &>/dev/null; then
            brew install helm
        else
            error "helm CLI not found and brew unavailable."
            error "Install manually: https://helm.sh/docs/intro/install/"
            exit 1
        fi
    fi

    info "Prerequisites OK"
}

# =============================================================================
# Agent Sandbox CRDs (kubernetes-sigs/agent-sandbox)
# =============================================================================
install_sandbox_crds() {
    section "Agent Sandbox CRDs (${SANDBOX_CRD_VERSION})"

    if oc get crd sandboxes.agents.x-k8s.io &>/dev/null; then
        local existing_ver
        existing_ver=$(oc get crd sandboxes.agents.x-k8s.io -o jsonpath='{.metadata.labels.app\.kubernetes\.io/version}' 2>/dev/null || echo "unknown")
        info "Agent Sandbox CRDs already installed (version: ${existing_ver})"
        info "Re-applying to ensure latest..."
    fi

    local manifest_url="https://github.com/kubernetes-sigs/agent-sandbox/releases/download/${SANDBOX_CRD_VERSION}/sandbox-with-extensions.yaml"

    info "Installing from: ${manifest_url}"
    if ! oc apply -f "$manifest_url"; then
        error "Failed to install Agent Sandbox CRDs."
        error "Check the version tag: https://github.com/kubernetes-sigs/agent-sandbox/releases"
        exit 1
    fi

    info "Waiting for controller to be ready..."
    oc wait --for=condition=Available deployment/agent-sandbox-controller \
        -n agent-sandbox-system --timeout=120s 2>/dev/null || \
        warn "Controller not ready yet — it may need a moment."

    local crd_count
    crd_count=$(oc get crd 2>/dev/null | grep -c 'agents.x-k8s.io' || echo "0")
    info "Agent Sandbox CRDs installed: ${crd_count} CRDs"
}

# =============================================================================
# OpenShell Gateway (Helm)
# =============================================================================
install_openshell() {
    section "OpenShell Gateway (Helm)"

    # Create namespace
    if oc get ns "$NAMESPACE" &>/dev/null; then
        info "Namespace '$NAMESPACE' exists"
    else
        info "Creating namespace '$NAMESPACE'..."
        oc create ns "$NAMESPACE"
    fi

    # SCC for sandbox pods
    info "Granting privileged SCC to '${SANDBOX_SA}'..."
    oc adm policy add-scc-to-user privileged -z "$SANDBOX_SA" -n "$NAMESPACE" 2>/dev/null || true

    # Build Helm args
    # TP phase: disableTls + allowUnauthenticatedUsers for dev/lab convenience
    local helm_cmd="install"
    if helm status openshell -n "$NAMESPACE" &>/dev/null; then
        warn "OpenShell already installed — upgrading..."
        helm_cmd="upgrade"
    fi

    local helm_args=(
        "$helm_cmd" openshell "$CHART_REPO"
        -n "$NAMESPACE"
        --set server.disableTls=true
        --set server.auth.allowUnauthenticatedUsers=true
        --set podSecurityContext.fsGroup=null
        --set securityContext.runAsUser=null
    )

    if [[ -n "$CHART_VERSION" ]]; then
        helm_args+=(--version "$CHART_VERSION")
    fi

    info "Running: helm ${helm_args[*]}"
    helm "${helm_args[@]}"

    # Wait for readiness
    info "Waiting for gateway pod..."
    oc rollout status statefulset/openshell -n "$NAMESPACE" --timeout=120s 2>/dev/null || \
    oc rollout status deployment/openshell -n "$NAMESPACE" --timeout=120s 2>/dev/null || true

    # Verify gateway can see CRDs
    local log_check
    log_check=$(oc logs -l app.kubernetes.io/name=openshell -n "$NAMESPACE" --tail=20 2>/dev/null || true)
    if echo "$log_check" | grep -q "Compute driver connected"; then
        info "Gateway connected to Agent Sandbox CRDs"
    elif echo "$log_check" | grep -q "no supported Agent Sandbox API"; then
        error "Gateway cannot find Agent Sandbox CRDs."
        error "Ensure Agent Sandbox controller is running in agent-sandbox-system."
        exit 1
    fi

    echo ""
    show_status
    echo ""
    section "Installation Complete"
    info "Gateway: http://openshell.${NAMESPACE}.svc.cluster.local:8080"
    echo ""
    info "${BOLD}Developer workstation setup:${NC}"
    info "  1. Register gateway:"
    info "     openshell gateway add http://127.0.0.1:8080 --name cluster-forward --local"
    info "  2. Port-forward (run in background or separate terminal):"
    info "     oc port-forward svc/openshell 8080:8080 -n ${NAMESPACE}"
    info "  3. Verify:"
    info "     openshell sandbox list"
    echo ""
    warn "${BOLD}TP Note:${NC} TLS disabled, unauthenticated access enabled."
    warn "For production, configure OIDC or mTLS (see Helm values: server.oidc.*)."
}

# =============================================================================
# Uninstall
# =============================================================================
uninstall_openshell() {
    section "Uninstalling OpenShell"

    if helm status openshell -n "$NAMESPACE" &>/dev/null; then
        helm uninstall openshell -n "$NAMESPACE"
        info "Helm release removed"
    else
        warn "No Helm release 'openshell' in namespace '$NAMESPACE'"
    fi

    info "Removing SCC binding..."
    oc adm policy remove-scc-from-user privileged -z "$SANDBOX_SA" -n "$NAMESPACE" 2>/dev/null || true

    section "Uninstalling Agent Sandbox CRDs"
    if oc get crd sandboxes.agents.x-k8s.io &>/dev/null; then
        local manifest_url="https://github.com/kubernetes-sigs/agent-sandbox/releases/download/${SANDBOX_CRD_VERSION}/sandbox-with-extensions.yaml"
        oc delete -f "$manifest_url" --ignore-not-found 2>/dev/null || true
        info "Agent Sandbox CRDs removed"
    else
        info "Agent Sandbox CRDs not found — skipping"
    fi

    echo ""
    read -rp "Delete namespace '$NAMESPACE'? (y/N): " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        oc delete ns "$NAMESPACE" --wait=false
        info "Namespace deletion initiated"
    fi

    info "OpenShell uninstalled"
}

# =============================================================================
# Status
# =============================================================================
show_status() {
    section "OpenShell Status"

    # Agent Sandbox CRDs
    echo -e "\n${BOLD}Agent Sandbox CRDs:${NC}"
    local crd_count
    crd_count=$(oc get crd 2>/dev/null | grep -c 'agents.x-k8s.io' || echo "0")
    if [[ "$crd_count" -gt 0 ]]; then
        info "  Installed (${crd_count} CRDs)"
        oc get crd 2>/dev/null | grep 'agents.x-k8s.io' | awk '{printf "    %-55s %s\n", $1, $2}'
    else
        warn "  NOT installed"
    fi

    # Agent Sandbox controller
    echo -e "\n${BOLD}Agent Sandbox Controller:${NC}"
    if oc get deployment agent-sandbox-controller -n agent-sandbox-system &>/dev/null; then
        local ready
        ready=$(oc get deployment agent-sandbox-controller -n agent-sandbox-system -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        info "  Running (${ready:-0} replicas ready)"
    else
        warn "  NOT installed"
    fi

    # OpenShell namespace
    if ! oc get ns "$NAMESPACE" &>/dev/null; then
        echo -e "\n${BOLD}OpenShell Gateway:${NC}"
        warn "  Namespace '$NAMESPACE' does not exist"
        return 1
    fi

    # Helm release
    echo -e "\n${BOLD}Helm Release:${NC}"
    helm list -n "$NAMESPACE" 2>/dev/null || echo "  (no release found)"

    # Pods
    echo -e "\n${BOLD}Gateway Pods:${NC}"
    oc get pods -n "$NAMESPACE" -l app.kubernetes.io/name=openshell 2>/dev/null

    # Auth config
    echo -e "\n${BOLD}Configuration:${NC}"
    local config
    config=$(oc get configmap openshell-config -n "$NAMESPACE" -o jsonpath='{.data.gateway\.toml}' 2>/dev/null || echo "")
    if [[ -n "$config" ]]; then
        local tls_disabled auth_unauth
        tls_disabled=$(echo "$config" | grep 'disable_tls' | awk '{print $NF}' || echo "?")
        auth_unauth=$(echo "$config" | grep 'allow_unauthenticated_users' | awk '{print $NF}' || echo "?")
        info "  TLS disabled: ${tls_disabled}"
        info "  Unauthenticated users: ${auth_unauth}"
    fi

    # Active sandboxes
    echo -e "\n${BOLD}Active Sandboxes:${NC}"
    local sandbox_count
    sandbox_count=$(oc get sandbox -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')
    info "  Count: ${sandbox_count:-0}"
}

# =============================================================================
# Parse arguments
# =============================================================================
ACTION="install"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--namespace)       NAMESPACE="$2"; shift 2 ;;
        -v|--version)         CHART_VERSION="$2"; shift 2 ;;
        --sandbox-version)    SANDBOX_CRD_VERSION="$2"; shift 2 ;;
        --uninstall)          ACTION="uninstall"; shift ;;
        --status)             ACTION="status"; shift ;;
        -h|--help)            usage ;;
        *) error "Unknown option: $1"; usage ;;
    esac
done

# =============================================================================
# Main
# =============================================================================
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  NVIDIA OpenShell — Admin Installation (TP)         ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
warn "Technology Preview: TLS disabled, unauthenticated access enabled."
warn "For production clusters, configure OIDC (see: helm show values ${CHART_REPO})."
echo ""

case "$ACTION" in
    install)
        check_prerequisites
        install_sandbox_crds
        install_openshell
        ;;
    uninstall)
        check_prerequisites
        uninstall_openshell
        ;;
    status)
        show_status
        ;;
esac
