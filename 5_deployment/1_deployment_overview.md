# Phase 5: Deploying to OpenShift AI with Kagenti

## Overview

This phase deploys the multi-agent research system to Red Hat OpenShift AI using Kagenti's Component CRD for agent lifecycle management.

## Deployment Architecture

```
OpenShift AI Cluster
├── Namespace: doc-research-lab
│   ├── Kagenti Control Plane
│   │   ├── Agent Registry (A2A discovery)
│   │   ├── SPIFFE/SPIRE (identity)
│   │   └── Istio Ambient (mTLS)
│   │
│   ├── Agent Pods (via Component CRD)
│   │   ├── orchestrator (port 8100)
│   │   ├── doc-processor (port 8101)
│   │   ├── researcher (port 8102)
│   │   ├── writer (port 8103)
│   │   └── reviewer (port 8104)
│   │
│   ├── Infrastructure
│   │   ├── PostgreSQL + pgvector (StatefulSet)
│   │   ├── MinIO (object storage)
│   │   └── Phoenix (observability)
│   │
│   └── Model Serving (RHOAI)
│       ├── granite-3.3-8b-instruct (LLM)
│       └── granite-embedding-278m (embeddings)
```

## Deployment Steps

1. **Install Kagenti** on the cluster (operator or Helm)
2. **Deploy infrastructure** — PostgreSQL+pgvector, MinIO
3. **Create secrets** for LLM endpoints and DB credentials
4. **Build and push** agent container images
5. **Apply Component CRDs** to register agents with Kagenti
6. **Verify** via AgentCard discovery and end-to-end test

## Kagenti Component CRD

Each agent is deployed as a Kagenti Component:

```yaml
apiVersion: kagenti.io/v1alpha1
kind: Component
metadata:
  name: researcher
  labels:
    kagenti.io/type: agent
    kagenti.io/framework: LangGraph
    protocol.kagenti.io/a2a: ""
spec:
  image: registry/researcher:latest
  port: 8102
  replicas: 1
  env:
    - name: LLM_BASE_URL
      valueFrom:
        secretKeyRef:
          name: doc-research-secret
          key: LLM_BASE_URL
```

## Security

- **mTLS**: Automatic via Kagenti + Istio Ambient mesh
- **Identity**: SPIFFE workload IDs injected automatically
- **Secrets**: Kubernetes Secrets for credentials
- **RBAC**: Namespace-scoped access control
