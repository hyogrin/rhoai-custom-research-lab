# Deep Research Lab — Next.js Frontend

React-based frontend for the RHOAI Custom Deep Research Lab, built with
[assistant-ui](https://www.assistant-ui.com/) and the
[AG-UI protocol](https://github.com/ag-ui-protocol/ag-ui) for real-time
agent-user interaction.

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Framework | Next.js 15 | React server components, routing |
| Chat UI | assistant-ui | Thread rendering, message streaming |
| Protocol | AG-UI over SSE | Agent-user interaction events |
| Styling | Tailwind CSS 4 | Utility-first CSS |
| Icons | lucide-react | Consistent icon set |
| i18n | next-intl | English/Korean localization |

## Setup

```bash
# Install dependencies
npm install

# Copy environment config
cp .env.local.example .env.local

# Start development server
npm run dev
```

Open http://localhost:3000.

**Requirements**: The FastAPI backend must be running on port 8000 (with the AG-UI
endpoint at `/agent`). Start it with `make backend-start` from the project root.

## Project Structure

```
frontend-next/
├── app/
│   ├── layout.tsx          # Root layout with metadata
│   ├── page.tsx            # Main page (sidebar + header + chat)
│   ├── providers.tsx       # AG-UI runtime + settings context
│   └── globals.css         # Tailwind + Red Hat theme tokens
├── components/
│   ├── header.tsx          # App header with language toggle
│   ├── sidebar.tsx         # Thread history sidebar
│   ├── chat-area.tsx       # Main chat with verbose/step toggles
│   ├── settings-panel.tsx  # Research settings slide-out
│   ├── human-review.tsx    # HITL interrupt review card
│   ├── starter-cards.tsx   # Localized conversation starters
│   ├── step-history.tsx    # Collapsible step timeline
│   └── verbose-output.tsx  # Expandable event inspector
├── lib/
│   ├── utils.ts            # cn() utility
│   ├── i18n.ts             # Language instructions
│   └── mcp-toolkit.ts     # MCP server registration
├── messages/
│   ├── en-US.json          # English strings
│   └── ko-KR.json          # Korean strings
└── public/                 # Static assets
```

## Features

### AG-UI Integration

The frontend connects to the backend's `/agent` endpoint using `@ag-ui/client`'s
`HttpAgent`. The `useAgUiRuntime` hook handles:

- Streaming text (token-by-token rendering)
- Thinking/reasoning block display
- Tool call visualization (MCP tool invocations)
- State snapshots for thread persistence
- Interrupt handling for human-in-the-loop

### Human-in-the-Loop

When the research harness reaches max iterations without meeting the quality
threshold, the backend emits an interrupt. The `HumanReviewCard` component renders:

- Quality score gauge with threshold marker
- Iteration progress indicator
- Improvement suggestions from the reflection phase
- Accept (finalize) or Continue (iterate more) actions

### Settings

The settings panel controls backend research parameters:

- **Quality Threshold** — Score needed to stop iterating (1-10)
- **Max Iterations** — Hard limit on harness iterations
- **Web Search** — Enable/disable web search tool
- **Research Planning** — Enable/disable structured planning
- **Fact Check** — Enable/disable citation verification
- **Parallel Processing** — Concurrent search execution
- **Sectioned Report** — Sub-topic decomposition mode

### Verbose / Step History Toggles

- **Verbose Output** — Shows all AG-UI events (thinking, tool calls, state deltas) in an expandable inspector
- **Step History** — Accumulates processing steps in a collapsible timeline with phase-specific icons

### i18n (English / Korean)

Language toggle in the header switches between EN and KR:
- All UI strings are localized via `messages/*.json`
- Conversation starters are language-specific
- `language_instruction` is passed to the backend to control LLM output language

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_AGENT_URL` | `http://localhost:8000/agent` | AG-UI endpoint URL |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend REST API URL |
| `NEXT_PUBLIC_VECTOR_SEARCH_MCP_URL` | `http://127.0.0.1:9002/mcp/` | Vector search MCP |
| `NEXT_PUBLIC_WEB_SEARCH_MCP_URL` | `http://127.0.0.1:9003/mcp/` | Web search MCP |
| `NEXT_PUBLIC_VERIFICATION_MCP_URL` | `http://127.0.0.1:9004/mcp/` | Verification MCP |
| `NEXT_PUBLIC_OBSERVABILITY_MCP_URL` | `http://127.0.0.1:9005/mcp/` | Observability MCP |

## Build

```bash
npm run build    # Production build
npm run start    # Start production server
```

For container deployment, use the included `Dockerfile`:

```bash
docker build -t research-frontend .
docker run -p 3000:3000 -e NEXT_PUBLIC_AGENT_URL=http://backend:8000/agent research-frontend
```
