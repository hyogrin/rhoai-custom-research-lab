export type IntroContent = {
  title: string;
  subtitle: string;
  features: { icon: string; title: string; desc: string }[];
  workflow: { step: string; title: string; desc: string }[];
  techs: { name: string; purpose: string }[];
};

export const introContent: Record<string, IntroContent> = {
  "en-US": {
    title: "Deep Research Lab",
    subtitle:
      "AI-powered custom deep research system using harness engineering on Red Hat OpenShift AI",
    features: [
      {
        icon: "upload",
        title: "Document Upload & Analysis",
        desc: "Upload PDF, DOCX, PPTX files. Docling parses tables, figures, and text with OCR. Chunks are embedded into pgvector for semantic search.",
      },
      {
        icon: "iteration",
        title: "Iterative Quality-Driven Research",
        desc: "Plan → Execute → Verify → Reflect loop runs until the quality threshold is met. Each iteration accumulates context and improves the report.",
      },
      {
        icon: "web",
        title: "Web Search Integration",
        desc: "Combines uploaded document analysis with real-time web search (DuckDuckGo / SearXNG) for latest trends and external context.",
      },
      {
        icon: "citation",
        title: "Citations & References",
        desc: "Every claim links back to a source — document chunks or web pages. The final report includes a numbered References section.",
      },
      {
        icon: "verify",
        title: "LLM-as-Judge Verification",
        desc: "Quality scoring, citation validation, and fact-checking run automatically at each iteration via MCP verification tools.",
      },
      {
        icon: "hitl",
        title: "Human-in-the-Loop Review",
        desc: "After each iteration, review the quality score, see improvement suggestions, and decide to accept or continue iterating.",
      },
    ],
    workflow: [
      {
        step: "1",
        title: "Plan",
        desc: "Decompose the query into sub-topics with targeted search queries",
      },
      {
        step: "2",
        title: "Execute",
        desc: "Run semantic search (pgvector) and web search (MCP) in parallel",
      },
      {
        step: "3",
        title: "Verify",
        desc: "LLM-as-Judge scores quality, validates citations, checks facts",
      },
      {
        step: "4",
        title: "Reflect",
        desc: "Analyze failures, adjust strategy, iterate until quality threshold met",
      },
    ],
    techs: [
      { name: "LangGraph", purpose: "Stateful graph-based orchestration" },
      { name: "MCP", purpose: "Standardized tool protocol (FastMCP)" },
      { name: "AG-UI", purpose: "Real-time agent-user streaming" },
      { name: "Docling", purpose: "Document intelligence & parsing" },
      { name: "pgvector", purpose: "Semantic search embeddings" },
      { name: "RHOAI", purpose: "Model serving (vLLM)" },
    ],
  },
  "ko-KR": {
    title: "딥 리서치 랩",
    subtitle:
      "Red Hat OpenShift AI 기반 하네스 엔지니어링을 활용한 AI 맞춤형 심층 연구 시스템",
    features: [
      {
        icon: "upload",
        title: "문서 업로드 & 분석",
        desc: "PDF, DOCX, PPTX 파일을 업로드하면 Docling이 테이블, 그림, 텍스트를 OCR과 함께 파싱합니다. 청크는 pgvector에 임베딩되어 시맨틱 검색에 활용됩니다.",
      },
      {
        icon: "iteration",
        title: "반복적 품질 기반 연구",
        desc: "Plan → Execute → Verify → Reflect 루프가 품질 임계값을 달성할 때까지 실행됩니다. 각 반복마다 컨텍스트가 축적되고 보고서가 개선됩니다.",
      },
      {
        icon: "web",
        title: "웹 검색 통합",
        desc: "업로드된 문서 분석과 실시간 웹 검색(DuckDuckGo / SearXNG)을 결합하여 최신 동향과 외부 컨텍스트를 제공합니다.",
      },
      {
        icon: "citation",
        title: "인용 & 참고문헌",
        desc: "모든 주장은 문서 청크 또는 웹 페이지 출처와 연결됩니다. 최종 보고서에 번호가 매겨진 참고문헌 섹션이 포함됩니다.",
      },
      {
        icon: "verify",
        title: "LLM-as-Judge 검증",
        desc: "MCP 검증 도구를 통해 매 반복마다 품질 점수 산정, 인용 검증, 팩트 체크가 자동으로 수행됩니다.",
      },
      {
        icon: "hitl",
        title: "사람 참여 리뷰",
        desc: "각 반복 후 품질 점수를 확인하고, 개선 제안을 검토하며, 결과를 수락하거나 추가 반복을 결정합니다.",
      },
    ],
    workflow: [
      {
        step: "1",
        title: "계획",
        desc: "쿼리를 하위 주제로 분해하고 대상 검색 쿼리를 생성",
      },
      {
        step: "2",
        title: "실행",
        desc: "시맨틱 검색(pgvector)과 웹 검색(MCP)을 병렬로 수행",
      },
      {
        step: "3",
        title: "검증",
        desc: "LLM-as-Judge가 품질 점수 산정, 인용 검증, 팩트 체크 수행",
      },
      {
        step: "4",
        title: "반영",
        desc: "실패 분석, 전략 조정, 품질 임계값 달성까지 반복",
      },
    ],
    techs: [
      { name: "LangGraph", purpose: "상태 기반 그래프 오케스트레이션" },
      { name: "MCP", purpose: "표준 도구 프로토콜 (FastMCP)" },
      { name: "AG-UI", purpose: "실시간 에이전트-사용자 스트리밍" },
      { name: "Docling", purpose: "문서 인텔리전스 & 파싱" },
      { name: "pgvector", purpose: "시맨틱 검색 임베딩" },
      { name: "RHOAI", purpose: "모델 서빙 (vLLM)" },
    ],
  },
};
