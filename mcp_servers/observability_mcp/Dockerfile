FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[mcp]"

COPY mcp_servers/observability_mcp/ ./mcp_servers/observability_mcp/
COPY harness/ ./harness/

CMD ["python", "-m", "mcp_servers.observability_mcp.server"]
