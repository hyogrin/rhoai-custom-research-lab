# Phase 5: Deploying to OpenShift

## Overview

This phase deploys the custom deep research system to Red Hat OpenShift using
standard Kubernetes primitives — Deployments, Services, Routes, Secrets, and
ConfigMaps. No custom operators or CRDs are required.

## Deployment Architecture

```
OpenShift Cluster — Namespace: doc-research-lab
│
├── Application Layer
│   ├── backend       (FastAPI — port 8000)
│   ├── frontend      (Chainlit — port 7860)
│   └── MCP Servers
│       ├── vector-search-mcp   (port 9002)
│       ├── web-search-mcp      (port 9003)
│       ├── verification-mcp    (port 9004)
│       └── observability-mcp   (port 9005)
│
├── Infrastructure (managed separately)
│   ├── PostgreSQL + pgvector  (StatefulSet — port 5432)
│   └── MinIO                  (Deployment — port 9000)
│
└── Model Serving (RHOAI — external to this namespace)
    ├── granite-3.3-8b-instruct  (LLM)
    └── granite-embedding-278m   (embeddings)
```

## Two Deployment Methods

### Method A — Plain Manifests (`deploy/apps/`)

Individual YAML manifests applied with `oc apply`. Best for iterative
development and when you need fine-grained control over each resource.

```bash
make deploy-infra   # namespace, secret, PostgreSQL, MinIO
make deploy-apps    # backend, frontend, MCP servers
```

### Method B — Helm Chart (`deploy/helm/doc-research/`)

A single Helm release that bundles all application resources. Best for
production deployments with repeatable, versioned releases.

```bash
helm upgrade --install doc-research deploy/helm/doc-research/ \
  -n doc-research-lab --create-namespace
```

## Separation of Concerns

Infrastructure (PostgreSQL, MinIO) is deployed **before** application pods
because the apps depend on database and object storage being available:

1. `make deploy-infra` — creates namespace, secret, PostgreSQL StatefulSet,
   MinIO Deployment, and waits for readiness.
2. `make deploy-apps` — deploys backend, frontend, and all 4 MCP servers
   (env-substituted from `.env`).

## Container Image Build

All images are built with Podman using Dockerfiles in each component directory:

```bash
make build-all   # Build all 6 images (4 MCP + backend + frontend)
make push-all    # Tag and push to REGISTRY
```

Set `REGISTRY` in your environment (e.g., `quay.io/your-org`) before pushing.

## Secret and ConfigMap Management

- **Secret** (`deploy/secret.yaml`): Template with `${VAR}` placeholders,
  substituted from `.env` at deploy time via `envsubst`.
- **ConfigMap** (`init-db-sql`): Created from `scripts/init-db.sql` to
  initialize the pgvector database schema on first boot.
- **App manifests** (`deploy/apps/*.yaml`): Reference the secret for
  `LLM_BASE_URL`, `LLM_API_KEY`, `EMBEDDING_BASE_URL`, DB credentials, etc.

## Security

- **TLS**: OpenShift Routes with edge termination (automatic cert via cluster ingress)
- **Secrets**: Kubernetes Secrets for all credentials (never baked into images)
- **RBAC**: Namespace-scoped; apps use default ServiceAccount
- **Network**: Internal Services for inter-pod communication; Routes only for external access
