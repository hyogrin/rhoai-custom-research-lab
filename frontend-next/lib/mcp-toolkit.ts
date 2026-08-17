/**
 * MCP Toolkit registration for assistant-ui.
 *
 * Registers all 4 MCP servers (Streamable HTTP) so their tools
 * are visible in the assistant-ui tool call renderer.
 */

const VECTOR_SEARCH_MCP_URL =
  process.env.NEXT_PUBLIC_VECTOR_SEARCH_MCP_URL ?? "http://127.0.0.1:9002/mcp/";
const WEB_SEARCH_MCP_URL =
  process.env.NEXT_PUBLIC_WEB_SEARCH_MCP_URL ?? "http://127.0.0.1:9003/mcp/";
const VERIFICATION_MCP_URL =
  process.env.NEXT_PUBLIC_VERIFICATION_MCP_URL ?? "http://127.0.0.1:9004/mcp/";
const OBSERVABILITY_MCP_URL =
  process.env.NEXT_PUBLIC_OBSERVABILITY_MCP_URL ?? "http://127.0.0.1:9005/mcp/";

export const mcpServers = {
  vectorSearch: { type: "http" as const, url: VECTOR_SEARCH_MCP_URL },
  webSearch: { type: "http" as const, url: WEB_SEARCH_MCP_URL },
  verification: { type: "http" as const, url: VERIFICATION_MCP_URL },
  observability: { type: "http" as const, url: OBSERVABILITY_MCP_URL },
};

export const mcpServerMetadata = [
  {
    name: "vector-search",
    url: VECTOR_SEARCH_MCP_URL,
    tools: ["semantic_search", "search_by_document", "get_chunk_context"],
    icon: "Search",
  },
  {
    name: "web-search",
    url: WEB_SEARCH_MCP_URL,
    tools: ["web_search"],
    icon: "Globe",
  },
  {
    name: "verification",
    url: VERIFICATION_MCP_URL,
    tools: ["quality_score", "validate_citations", "fact_check", "llm_as_judge", "run_verification"],
    icon: "ShieldCheck",
  },
  {
    name: "observability",
    url: OBSERVABILITY_MCP_URL,
    tools: ["record_trace", "record_failure", "get_metrics", "get_failure_hints", "get_past_failure_patterns"],
    icon: "Activity",
  },
];
