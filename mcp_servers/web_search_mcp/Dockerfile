FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[mcp]"

COPY mcp_servers/web_search_mcp/ ./mcp_servers/web_search_mcp/

CMD ["python", "-m", "mcp_servers.web_search_mcp.server"]
