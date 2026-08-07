.PHONY: help setup mcp-start mcp-stop test lint clean \
	backend-start backend-stop backend-restart frontend-start start stop \
	build-all push-all deploy deploy-infra deploy-apps deploy-mcp undeploy

REGISTRY ?= quay.io/your-org
IMAGE_TAG ?= latest
REPO     := rhoai-custom-research-lab
NAMESPACE ?= doc-research-lab

MCP_SERVERS := vector_search_mcp web_search_mcp verification_mcp observability_mcp
UI_APPS     := backend frontend

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Install Python deps + provision PostgreSQL (auto-detects cluster vs local)
	uv sync
	@./scripts/setup.sh

mcp-start: ## Start all MCP servers locally
	@echo "Starting vector-search-mcp on port 9002..."
	@uv run python -m mcp_servers.vector_search_mcp.server &
	@echo "Starting web-search-mcp on port 9003..."
	@uv run python -m mcp_servers.web_search_mcp.server &
	@echo "Starting verification-mcp on port 9004..."
	@uv run python -m mcp_servers.verification_mcp.server &
	@echo "Starting observability-mcp on port 9005..."
	@uv run python -m mcp_servers.observability_mcp.server &
	@echo "All MCP servers started (ports 9002-9005)."

mcp-stop: ## Stop all locally running MCP servers
	@for port in 9002 9003 9004 9005; do \
		pid=$$(lsof -ti :$$port 2>/dev/null); \
		if [ -n "$$pid" ]; then kill $$pid 2>/dev/null && echo "Killed PID $$pid on port $$port"; fi; \
	done
	@pkill -f "mcp_servers\." 2>/dev/null || true
	@echo "All MCP servers stopped."

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

frontend-start: ## Start the Next.js frontend UI
	cd frontend-next && npm run dev

frontend-start-legacy: ## Start the legacy Chainlit frontend UI
	cd frontend && uv run chainlit run app.py --host 0.0.0.0 --port $${FRONTEND_PORT:-7860}

start: ## Show how to start all services
	@echo "========================================="
	@echo " Start services in separate terminals:"
	@echo "========================================="
	@echo ""
	@echo "  First time setup (Python deps + PostgreSQL):"
	@echo "    make setup"
	@echo ""
	@echo "  Terminal 1 — Backend + MCP servers:"
	@echo "    make backend-start"
	@echo ""
	@echo "  Terminal 2 — Frontend UI:"
	@echo "    make frontend-start"
	@echo ""
	@echo "  Then open: http://localhost:3000"
	@echo "========================================="

backend-stop: ## Stop backend + MCP servers (port-based, reliable)
	@echo "Stopping backend..."
	@pid=$$(lsof -ti :$${BACKEND_PORT:-8000} 2>/dev/null); \
		if [ -n "$$pid" ]; then kill $$pid 2>/dev/null; echo "Killed backend PID $$pid"; \
		else echo "Backend not running"; fi
	@sleep 1
	@$(MAKE) --no-print-directory mcp-stop

backend-restart: ## Clean stop + start backend (use instead of Ctrl+C)
	@$(MAKE) --no-print-directory backend-stop
	@sleep 1
	@$(MAKE) --no-print-directory backend-start

stop: ## Stop all services
	@$(MAKE) --no-print-directory backend-stop
	@pkill -f "next dev" 2>/dev/null || true
	@pkill -f "chainlit run" 2>/dev/null || true
	@echo "All services stopped."

ui-stop: stop ## Alias for stop

dev-up: ## Start infrastructure (PostgreSQL + pgvector)
	docker compose up -d
	@echo "PostgreSQL + pgvector started on port 5432"

sse-test: ## Run SSE smoke test
	uv run python backend/test_sse.py

build-all: ## Build ALL container images (MCP + UI)
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
	@echo "=== All images built ==="

push-all: ## Push ALL images to $(REGISTRY)
	@if [ -z "$(REGISTRY)" ]; then echo "Error: Set REGISTRY env var"; exit 1; fi
	@for img in $(MCP_SERVERS) $(UI_APPS); do \
		echo "Pushing $$img..."; \
		podman tag $(REPO)/$$img:$(IMAGE_TAG) $(REGISTRY)/$(REPO)/$$img:$(IMAGE_TAG); \
		podman push $(REGISTRY)/$(REPO)/$$img:$(IMAGE_TAG); \
	done
	@echo "=== All images pushed to $(REGISTRY) ==="

deploy: deploy-infra deploy-apps deploy-mcp ## Deploy all components to OpenShift
	@echo "=== Deployment complete ==="

deploy-infra: ## Deploy namespace + secrets
	@echo "=== Deploying infrastructure ==="
	oc apply -f deploy/namespace.yaml
	@. ./.env 2>/dev/null; export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
		envsubst < deploy/secret.yaml | oc apply -f -
	oc create configmap init-db-sql --from-file=scripts/init-db.sql \
		-n $(NAMESPACE) --dry-run=client -o yaml | oc apply -f -
	oc apply -f deploy/infra/ -n $(NAMESPACE)
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

deploy-helm: ## Deploy via Helm chart
	@echo "=== Deploying with Helm ==="
	helm upgrade --install doc-research deploy/helm/doc-research/ \
		-n $(NAMESPACE) --create-namespace \
		-f deploy/helm/doc-research/values.yaml

undeploy: ## Remove all deployed resources
	@echo "=== Removing all resources ==="
	-helm uninstall doc-research -n $(NAMESPACE) 2>/dev/null
	-oc delete -f deploy/apps/ -n $(NAMESPACE) 2>/dev/null
	-oc delete -f deploy/infra/ -n $(NAMESPACE) 2>/dev/null
	-oc delete configmap init-db-sql -n $(NAMESPACE) 2>/dev/null
	-oc delete secret doc-research-secret -n $(NAMESPACE) 2>/dev/null
	-oc delete namespace $(NAMESPACE) 2>/dev/null
	@echo "=== All resources removed ==="
