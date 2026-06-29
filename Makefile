.PHONY: help setup dev-up dev-down agents-start agents-stop test lint clean \
	backend-start frontend-start ui-start ui-stop

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

agents-start: ## Start all agents locally
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

agents-stop: ## Stop all locally running agents
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

backend-start: ## Start the FastAPI backend API server
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

ui-stop: ## Stop UI processes
	@pkill -f "uvicorn backend.api" || true
	@pkill -f "chainlit run" || true
	@echo "UI stopped."

sse-test: ## Run SSE smoke test
	uv run python backend/test_sse.py

build-images: ## Build container images for all agents
	@for agent in orchestrator doc_processor researcher writer reviewer; do \
		echo "Building $$agent..."; \
		podman build -t rhoai-custom-research-lab/$$agent:latest agents/$$agent/; \
	done

push-images: ## Push container images to registry (set REGISTRY env var)
	@if [ -z "$(REGISTRY)" ]; then echo "Set REGISTRY env var"; exit 1; fi
	@for agent in orchestrator doc_processor researcher writer reviewer; do \
		podman push rhoai-custom-research-lab/$$agent:latest $(REGISTRY)/rhoai-custom-research-lab/$$agent:latest; \
	done
