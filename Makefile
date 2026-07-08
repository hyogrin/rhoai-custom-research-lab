.PHONY: help setup dev-up dev-down mcp-start mcp-stop agents-start agents-stop test lint clean \
	backend-start frontend-start ui-start ui-stop \
	build-all push-all deploy deploy-infra deploy-apps deploy-agents deploy-mcp undeploy

REGISTRY ?= quay.io/your-org
IMAGE_TAG ?= latest
REPO     := rhoai-custom-research-lab
NAMESPACE ?= doc-research-lab

AGENTS      := orchestrator doc_processor researcher writer reviewer
MCP_SERVERS := doc_mcp search_mcp analysis_mcp verification_mcp observability_mcp
UI_APPS     := backend frontend

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Install all Python dependencies
	uv sync

dev-up: ## Start local dev services (PostgreSQL+pgvector, MinIO)
	podman-compose -f compose.yml up -d

dev-down: ## Stop local dev services
	podman-compose -f compose.yml down

dev-logs: ## Show logs from local dev services
	podman-compose -f compose.yml logs -f

mcp-start: ## Start all MCP servers locally
	@echo "Starting doc-mcp on port 9001..."
	@uv run python -m mcp_servers.doc_mcp.server &
	@echo "Starting search-mcp on port 9002..."
	@uv run python -m mcp_servers.search_mcp.server &
	@echo "Starting analysis-mcp on port 9003..."
	@uv run python -m mcp_servers.analysis_mcp.server &
	@echo "Starting verification-mcp on port 9004..."
	@uv run python -m mcp_servers.verification_mcp.server &
	@echo "Starting observability-mcp on port 9005..."
	@uv run python -m mcp_servers.observability_mcp.server &
	@echo "All MCP servers started (ports 9001-9005)."

mcp-stop: ## Stop all locally running MCP servers
	@pkill -f "mcp_servers\." || true
	@echo "All MCP servers stopped."

agents-start: mcp-start ## Start MCP servers + all agents locally
	@sleep 3
	@echo "Starting Document Processor on port 8101..."
	@cd agents/doc_processor && uv run python agent.py &
	@echo "Starting Researcher on port 8102..."
	@cd agents/researcher && uv run python agent.py &
	@echo "Starting Writer on port 8103..."
	@cd agents/writer && uv run python agent.py &
	@echo "Starting Reviewer on port 8104..."
	@cd agents/reviewer && uv run python agent.py &
	@sleep 2
	@echo "Starting Orchestrator on port 8100..."
	@cd agents/orchestrator && uv run python agent.py &
	@echo "All agents started."

agents-stop: mcp-stop ## Stop all agents and MCP servers
	@pkill -f "agents/.*/agent.py" || true
	@echo "All agents stopped."

test: ## Run all tests
	uv run pytest -v

lint: ## Lint all Python code
	uv run ruff check .

format: ## Format all Python code
	uv run ruff format .

clean: ## Remove build artifacts
	rm -rf .venv __pycache__ .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

backend-start: ## Start backend (auto-starts MCP servers as subprocesses)
	uv run uvicorn backend.api:app --host 0.0.0.0 --port $${BACKEND_PORT:-8000} --reload

frontend-start: ## Start the Chainlit frontend UI
	cd frontend && uv run chainlit run app.py --host 0.0.0.0 --port $${FRONTEND_PORT:-7860}

ui-start: ## Start backend + frontend together
	@echo "Starting backend on port $${BACKEND_PORT:-8000}..."
	@uv run uvicorn backend.api:app --host 0.0.0.0 --port $${BACKEND_PORT:-8000} &
	@sleep 2
	@echo "Starting frontend on port $${FRONTEND_PORT:-7860}..."
	@cd frontend && uv run chainlit run app.py --host 0.0.0.0 --port $${FRONTEND_PORT:-7860} &
	@echo "UI started: http://localhost:$${FRONTEND_PORT:-7860}"

ui-stop: ## Stop UI processes (MCP subprocesses auto-terminate with backend)
	@pkill -f "uvicorn backend.api" || true
	@pkill -f "chainlit run" || true
	@pkill -f "mcp_servers\." || true
	@echo "UI stopped."

sse-test: ## Run SSE smoke test
	uv run python backend/test_sse.py

build-images: ## Build container images for agents only
	@for agent in $(AGENTS); do \
		echo "Building $$agent..."; \
		podman build -t $(REPO)/$$agent:$(IMAGE_TAG) agents/$$agent/; \
	done

push-images: ## Push agent images to registry
	@if [ -z "$(REGISTRY)" ]; then echo "Set REGISTRY env var"; exit 1; fi
	@for agent in $(AGENTS); do \
		podman tag $(REPO)/$$agent:$(IMAGE_TAG) $(REGISTRY)/$(REPO)/$$agent:$(IMAGE_TAG); \
		podman push $(REGISTRY)/$(REPO)/$$agent:$(IMAGE_TAG); \
	done

build-all: ## Build ALL container images (agents + MCP + UI)
	@echo "=== Building agent images ==="
	@for agent in $(AGENTS); do \
		echo "Building agent: $$agent..."; \
		podman build -t $(REPO)/$$agent:$(IMAGE_TAG) agents/$$agent/; \
	done
	@echo "=== Building MCP server images ==="
	@for mcp in $(MCP_SERVERS); do \
		echo "Building MCP: $$mcp..."; \
		podman build -f mcp_servers/$$mcp/Dockerfile -t $(REPO)/$$mcp:$(IMAGE_TAG) .; \
	done
	@echo "=== Building UI images ==="
	@for app in $(UI_APPS); do \
		echo "Building UI: $$app..."; \
		podman build -f $$app/Dockerfile -t $(REPO)/$$app:$(IMAGE_TAG) .; \
	done
	@echo "=== All 12 images built ==="

push-all: ## Push ALL images to $(REGISTRY)
	@if [ -z "$(REGISTRY)" ]; then echo "Error: Set REGISTRY env var"; exit 1; fi
	@for img in $(AGENTS) $(MCP_SERVERS) $(UI_APPS); do \
		echo "Pushing $$img..."; \
		podman tag $(REPO)/$$img:$(IMAGE_TAG) $(REGISTRY)/$(REPO)/$$img:$(IMAGE_TAG); \
		podman push $(REGISTRY)/$(REPO)/$$img:$(IMAGE_TAG); \
	done
	@echo "=== All images pushed to $(REGISTRY) ==="

deploy: deploy-infra deploy-apps deploy-mcp deploy-agents ## Deploy all components to OpenShift
	@echo "=== Deployment complete ==="

deploy-infra: ## Deploy namespace, secret, PostgreSQL, MinIO
	@echo "=== Deploying infrastructure ==="
	oc apply -f deploy/namespace.yaml
	@. ./.env 2>/dev/null; export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
		envsubst < deploy/secret.yaml | oc apply -f -
	oc create configmap init-db-sql --from-file=scripts/init-db.sql \
		-n $(NAMESPACE) --dry-run=client -o yaml | oc apply -f -
	oc apply -f deploy/infra/ -n $(NAMESPACE)
	@echo "Waiting for PostgreSQL to be ready..."
	oc wait --for=condition=ready pod -l app=postgresql -n $(NAMESPACE) --timeout=120s
	@echo "Waiting for MinIO to be ready..."
	oc wait --for=condition=ready pod -l app=minio -n $(NAMESPACE) --timeout=120s

deploy-apps: ## Deploy backend, frontend, MCP servers
	@echo "=== Deploying applications ==="
	@. ./.env 2>/dev/null; export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
		for f in deploy/apps/*.yaml; do \
			envsubst < "$$f" | oc apply -f - -n $(NAMESPACE); \
		done

deploy-mcp: ## Deploy MCPServer CRs (requires MCP lifecycle operator)
	@echo "=== Deploying MCPServer CRs ==="
	@. ./.env 2>/dev/null; export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
		envsubst < deploy/mcp/mcpservers.yaml | oc apply -f - || \
		echo "MCPServer CRD not found — skipping (deploy MCP servers via deploy-apps instead)"

deploy-agents: ## Deploy Kagenti agent Components
	@echo "=== Deploying Kagenti agents ==="
	@. ./.env 2>/dev/null; export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
		envsubst < deploy/kagenti/components.yaml | oc apply -f -

undeploy: ## Remove all deployed resources
	@echo "=== Removing all resources ==="
	-oc delete -f deploy/kagenti/ 2>/dev/null
	-oc delete -f deploy/apps/ -n $(NAMESPACE) 2>/dev/null
	-oc delete -f deploy/infra/ -n $(NAMESPACE) 2>/dev/null
	-oc delete configmap init-db-sql -n $(NAMESPACE) 2>/dev/null
	-oc delete secret doc-research-secret -n $(NAMESPACE) 2>/dev/null
	-oc delete namespace $(NAMESPACE) 2>/dev/null
	@echo "=== All resources removed ==="
