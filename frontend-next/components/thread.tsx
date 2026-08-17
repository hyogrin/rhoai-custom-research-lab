"use client";

import {
  ActionBarPrimitive,
  AuiIf,
  ChainOfThoughtPrimitive,
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePartPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAui,
  useAuiState,
  useToolCallElapsed,
  type AssistantState,
} from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import remarkGfm from "remark-gfm";
import { useSettings, useDocuments } from "@/app/providers";
import { useResearchEvents } from "@/hooks/use-research-events";
import { AgentPlan } from "@/components/agent-plan";
import { VerboseOutput } from "@/components/verbose-output";
import { CitationBadge } from "@/components/elements/citation-badge";
import { IterationReviewCard } from "@/components/elements/iteration-review-card";
import { ExecutionPermissionCard } from "@/components/execution-permission-card";
import { ClaimEvidenceGraph } from "@/components/claim-evidence-graph";
import { IntroPanel } from "@/components/intro-panel";
import { cn } from "@/lib/utils";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ClipboardCopy,
  Check,
  FileSearch,
  FileText,
  Globe,
  Info,
  Loader2,
  MessageCircle,
  Paperclip,
  RefreshCw,
  SquareIcon,
  Upload,
  Wrench,
  AlertTriangle,
  Clock,
} from "lucide-react";
import { useRef, useState, type FC, type PropsWithChildren } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function simplifyDocName(filename: string): string {
  const name = filename.replace(/\.(pdf|txt|md|docx|pptx)$/i, "");
  const spaced = name.replace(/[_-]+/g, " ");
  const titled = spaced.replace(
    /\b\w+/g,
    (w) => w.charAt(0).toUpperCase() + w.slice(1),
  );
  return titled.length > 40 ? titled.slice(0, 37) + "..." : titled;
}

const isNewChatView = (s: AssistantState) => s.thread.messages.length === 0;

export const Thread: FC = () => {
  const isEmpty = useAuiState(isNewChatView);
  const { settings } = useSettings();
  const { steps, verbose, iterationReview, clearReview, executionPermission, clearExecutionPermission, claimEvidenceArtifact, artifactStatus } = useResearchEvents();
  const isKorean = settings.language === "ko-KR";
  const [showIntro, setShowIntro] = useState(false);

  return (
    <ThreadPrimitive.Root
      className="flex h-full flex-col"
      style={{
        ["--thread-max-width" as string]: "44rem",
        ["--composer-bg" as string]:
          "color-mix(in oklab, var(--color-muted) 30%, var(--color-background))",
        ["--composer-radius" as string]: "1.5rem",
        ["--composer-padding" as string]: "8px",
      }}
    >
      <ThreadPrimitive.Viewport
        className={cn(
          "relative flex flex-1 flex-col overflow-x-hidden overflow-y-scroll scroll-smooth px-4 pt-4",
          isEmpty && !showIntro && "justify-center",
        )}
      >
        {isEmpty && !showIntro && <ThreadWelcome />}
        {isEmpty && showIntro && (
          <IntroPanel
            language={settings.language}
            onClose={() => setShowIntro(false)}
          />
        )}

        <div className="mb-14 flex flex-col gap-y-4 empty:hidden">
          <ThreadPrimitive.Messages
            components={{
              UserMessage,
              AssistantMessage,
            }}
          />
          {iterationReview && (
            <div className="mx-auto w-full max-w-[var(--thread-max-width)] px-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
              <IterationReviewCard
                review={iterationReview}
                isKorean={isKorean}
                onDismiss={clearReview}
              />
            </div>
          )}
          {executionPermission && (
            <div className="mx-auto w-full max-w-[var(--thread-max-width)] px-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
              <ExecutionPermissionCard data={executionPermission} />
            </div>
          )}
          {claimEvidenceArtifact && artifactStatus === "completed" && (
            <div className="mx-auto w-full max-w-[var(--thread-max-width)] px-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
              <ClaimEvidenceGraph
                artifact={claimEvidenceArtifact}
                status={artifactStatus}
              />
            </div>
          )}
          {artifactStatus === "denied" && (
            <div className="mx-auto w-full max-w-[var(--thread-max-width)] px-2">
              <ClaimEvidenceGraph artifact={null} status="denied" />
            </div>
          )}
          {artifactStatus === "failed" && (
            <div className="mx-auto w-full max-w-[var(--thread-max-width)] px-2">
              <ClaimEvidenceGraph artifact={null} status="failed" />
            </div>
          )}
          <AgentPlan steps={steps} visible={settings.logSse} />
          <VerboseOutput events={verbose} visible={settings.verbose} />
        </div>

        <ThreadPrimitive.ViewportFooter
          className={cn(
            "bg-background mx-auto flex w-full max-w-[var(--thread-max-width)] flex-col gap-4 overflow-visible pb-4 md:pb-6",
            !isEmpty &&
              "sticky bottom-0 mt-auto rounded-t-[var(--composer-radius)]",
          )}
        >
          <ThreadScrollToBottom />
          <Composer />
          {isEmpty && !showIntro && (
            <ThreadSuggestions onShowIntro={() => setShowIntro(true)} />
          )}
        </ThreadPrimitive.ViewportFooter>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
};

const ThreadScrollToBottom: FC = () => {
  return (
    <ThreadPrimitive.ScrollToBottom asChild>
      <button
        className="border-border bg-background hover:bg-accent absolute -top-12 z-10 self-center rounded-full border p-2 shadow-sm disabled:invisible"
        aria-label="Scroll to bottom"
      >
        <ArrowDownIcon className="size-4" />
      </button>
    </ThreadPrimitive.ScrollToBottom>
  );
};

const ThreadWelcome: FC = () => {
  const { settings } = useSettings();
  const isKorean = settings.language === "ko-KR";

  return (
    <div className="mx-auto mb-6 flex w-full max-w-[var(--thread-max-width)] flex-col items-center px-4 text-center">
      <h1 className="text-2xl font-semibold animate-in fade-in slide-in-from-bottom-1 duration-200">
        {isKorean ? "무엇을 연구해 드릴까요?" : "What would you like to research?"}
      </h1>
      <p className="mt-2 text-sm text-muted-foreground">
        {isKorean
          ? "문서를 업로드하고 연구 질문을 해보세요"
          : "Upload documents and ask research questions"}
      </p>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Message Part Components
// ---------------------------------------------------------------------------

function preprocessMarkdown(text: string): string {
  // Fix collapsed table rows: "| val | | val |" → "| val |\n| val |"
  text = text.replace(/ \| \| /g, " |\n| ");
  // Fix separator row collapsed inline
  text = text.replace(/(\| :?-+:? (?:\| :?-+:? )*\|) (\|)/g, "$1\n$2");
  // Fix table end glued to heading: "|## Title" → "|\n\n## Title"
  text = text.replace(/(\|)\s*(#{1,6}\s)/g, "$1\n\n$2");
  // Ensure blank line before any heading (after single newline)
  text = text.replace(/([^\n])\n(#{1,6}\s)/g, "$1\n\n$2");
  // Catch heading glued directly to preceding text without any newline
  text = text.replace(/([^\n#])(#{1,6}\s)/g, "$1\n\n$2");
  return text;
}

function CitationLink({
  href,
  children,
  ...props
}: React.AnchorHTMLAttributes<HTMLAnchorElement>) {
  const match = href?.match(/^#cite-(\d+)$/);
  if (match) {
    return <CitationBadge index={parseInt(match[1], 10)} />;
  }
  return (
    <a href={href} {...props}>
      {children}
    </a>
  );
}

const markdownComponents = {
  a: CitationLink,
};

const remarkPlugins = [remarkGfm];

const TextPart: FC = () => (
  <div className="aui-md-content">
    <MarkdownTextPrimitive
      smooth={{ drainMs: 50 }}
      preprocess={preprocessMarkdown}
      components={markdownComponents}
      remarkPlugins={remarkPlugins}
    />
    <MessagePartPrimitive.InProgress>
      <span className="aui-streaming-dot ml-0.5 inline-block text-primary">
        ●
      </span>
    </MessagePartPrimitive.InProgress>
  </div>
);

const ReasoningPart: FC = () => {
  return (
    <div className="aui-reasoning-part my-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Brain className="size-3.5 animate-pulse text-primary/70" />
        <MessagePartPrimitive.Text
          smooth
          className="italic text-muted-foreground/80"
        />
        <MessagePartPrimitive.InProgress>
          <span className="aui-thinking-dots">
            <span />
            <span />
            <span />
          </span>
        </MessagePartPrimitive.InProgress>
      </div>
    </div>
  );
};

const ReasoningGroupWrapper: FC<
  PropsWithChildren<{ startIndex: number; endIndex: number }>
> = ({ children }) => {
  return (
    <ChainOfThoughtPrimitive.Root className="aui-reasoning-group my-2 rounded-lg border border-border/40 bg-muted/30 overflow-hidden">
      <ChainOfThoughtPrimitive.AccordionTrigger className="flex w-full items-center gap-2 px-3 py-2 text-xs font-medium text-muted-foreground hover:bg-muted/50 transition-colors cursor-pointer">
        <Brain className="size-3.5 text-primary/70" />
        <span>Reasoning</span>
        <MessagePartPrimitive.InProgress>
          <span className="aui-thinking-dots ml-1">
            <span />
            <span />
            <span />
          </span>
        </MessagePartPrimitive.InProgress>
        <ChevronDown className="ml-auto size-3.5 transition-transform aui-accordion-chevron" />
      </ChainOfThoughtPrimitive.AccordionTrigger>
      <div className="px-3 pb-2">{children}</div>
    </ChainOfThoughtPrimitive.Root>
  );
};

const ToolCallFallback: FC = () => {
  const [expanded, setExpanded] = useState(false);
  const elapsed = useToolCallElapsed();

  const part = useAuiState((s) => {
    if (s.part.type !== "tool-call") return null;
    return s.part;
  });

  if (!part) return null;

  const isRunning = part.status.type === "running";
  const isError = part.isError;
  const isComplete = part.status.type === "complete" && !isError;

  return (
    <div
      className={cn(
        "aui-tool-call my-2 rounded-lg border overflow-hidden transition-all duration-200",
        isRunning && "border-primary/30 bg-primary/[0.03]",
        isError && "border-destructive/30 bg-destructive/[0.03]",
        isComplete && "border-border/40 bg-muted/20",
        !isRunning && !isError && !isComplete && "border-border/40 bg-muted/20",
      )}
    >
      <button
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs transition-colors hover:bg-muted/30 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <span
          className={cn(
            "flex size-5 shrink-0 items-center justify-center rounded",
            isRunning && "bg-primary/10 text-primary",
            isError && "bg-destructive/10 text-destructive",
            isComplete && "bg-emerald-500/10 text-emerald-600",
          )}
        >
          {isRunning ? (
            <Loader2 className="size-3 animate-spin" />
          ) : isError ? (
            <AlertTriangle className="size-3" />
          ) : (
            <Wrench className="size-3" />
          )}
        </span>

        <span className="font-mono font-medium text-foreground truncate">
          {part.toolName}
        </span>

        {elapsed !== undefined && (
          <span className="ml-auto flex items-center gap-1 text-muted-foreground tabular-nums">
            <Clock className="size-3" />
            {(elapsed / 1000).toFixed(1)}s
          </span>
        )}

        {expanded ? (
          <ChevronDown className="size-3.5 text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight className="size-3.5 text-muted-foreground shrink-0" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-border/30 px-3 py-2 space-y-2 animate-in fade-in slide-in-from-top-1 duration-150">
          {part.args && Object.keys(part.args).length > 0 && (
            <div>
              <div className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70">
                Arguments
              </div>
              <pre className="overflow-x-auto rounded-md bg-muted/50 p-2 text-[11px] font-mono text-muted-foreground leading-relaxed">
                {JSON.stringify(part.args, null, 2)}
              </pre>
            </div>
          )}
          {part.result !== undefined && (
            <div>
              <div className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70">
                Result
              </div>
              <pre
                className={cn(
                  "overflow-x-auto rounded-md p-2 text-[11px] font-mono leading-relaxed",
                  isError
                    ? "bg-destructive/5 text-destructive"
                    : "bg-muted/50 text-muted-foreground",
                )}
              >
                {typeof part.result === "string"
                  ? part.result
                  : JSON.stringify(part.result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const ToolGroupWrapper: FC<
  PropsWithChildren<{ startIndex: number; endIndex: number }>
> = ({ children, startIndex, endIndex }) => {
  const count = endIndex - startIndex + 1;
  return (
    <div className="aui-tool-group my-3">
      <div className="mb-1.5 flex items-center gap-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/60">
        <div className="h-px flex-1 bg-border/40" />
        <Wrench className="size-3" />
        <span>
          {count} tool {count === 1 ? "call" : "calls"}
        </span>
        <div className="h-px flex-1 bg-border/40" />
      </div>
      <div className="space-y-1">{children}</div>
    </div>
  );
};

const EmptyPart: FC<{ status: { type: string } }> = ({ status }) => {
  if (status.type !== "running") return null;
  return (
    <div className="flex items-center gap-3 py-2">
      <div className="aui-dot-matrix-sm" aria-hidden="true" />
      <span className="text-sm text-muted-foreground animate-pulse">
        Thinking...
      </span>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Error Display
// ---------------------------------------------------------------------------

const ErrorDisplay: FC = () => (
  <ErrorPrimitive.Root className="my-2 flex items-start gap-2.5 rounded-lg border border-destructive/30 bg-destructive/[0.04] px-3.5 py-2.5 animate-in fade-in slide-in-from-bottom-1 duration-200">
    <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
    <div className="min-w-0 flex-1">
      <div className="text-sm font-medium text-destructive">
        Something went wrong
      </div>
      <ErrorPrimitive.Message className="mt-0.5 text-xs text-destructive/80 break-words" />
    </div>
  </ErrorPrimitive.Root>
);

// ---------------------------------------------------------------------------
// Action Bar
// ---------------------------------------------------------------------------

const AssistantActionBar: FC = () => (
  <ActionBarPrimitive.Root className="aui-action-bar mt-1 flex items-center gap-1 opacity-0 transition-opacity group-hover/message:opacity-100">
    <ActionBarPrimitive.Copy asChild>
      <button
        className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        aria-label="Copy message"
      >
        <AuiIf condition={(s) => !s.message.isCopied}>
          <ClipboardCopy className="size-3.5" />
        </AuiIf>
        <AuiIf condition={(s) => !!s.message.isCopied}>
          <Check className="size-3.5 text-emerald-500" />
        </AuiIf>
      </button>
    </ActionBarPrimitive.Copy>
    <ActionBarPrimitive.Reload asChild>
      <button
        className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        aria-label="Regenerate"
      >
        <RefreshCw className="size-3.5" />
      </button>
    </ActionBarPrimitive.Reload>
  </ActionBarPrimitive.Root>
);

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

const UserMessage: FC = () => {
  return (
    <MessagePrimitive.Root className="mx-auto grid w-full max-w-[var(--thread-max-width)] auto-rows-auto grid-cols-[minmax(72px,1fr)_auto] px-2 animate-in fade-in slide-in-from-bottom-1 duration-150">
      <div className="col-start-2 min-w-0">
        <div className="bg-muted text-foreground rounded-xl px-4 py-2 break-words">
          <MessagePrimitive.Content />
        </div>
      </div>
    </MessagePrimitive.Root>
  );
};

const AssistantMessage: FC = () => {
  return (
    <MessagePrimitive.Root className="group/message mx-auto w-full max-w-[var(--thread-max-width)] px-2 animate-in fade-in slide-in-from-bottom-1 duration-150">
      <div className="text-foreground leading-relaxed break-words">
        <MessagePrimitive.Content
          components={{
            Empty: EmptyPart,
            Text: TextPart,
            Reasoning: ReasoningPart,
            ReasoningGroup: ReasoningGroupWrapper,
            ToolGroup: ToolGroupWrapper,
            tools: {
              Fallback: ToolCallFallback,
            },
          }}
        />
        <MessagePrimitive.Error>
          <ErrorDisplay />
        </MessagePrimitive.Error>
        <AssistantActionBar />
      </div>
    </MessagePrimitive.Root>
  );
};

// ---------------------------------------------------------------------------
// Welcome Suggestions (dynamic based on uploaded documents)
// ---------------------------------------------------------------------------

const RESEARCH_ACTIONS = [
  {
    label: "Summary",
    labelKo: "요약",
    icon: <FileSearch className="size-4" />,
    prompt: (doc: string) =>
      `Analyze the document "${doc}" and provide a comprehensive summary with citations for key findings, covering both business and technical value.`,
    promptKo: (doc: string) =>
      `"${doc}" 문서를 분석하고 사업적, 기술적 가치 두 측면에 대해 인용을 포함한 종합적인 요약을 제공해주세요.`,
  },
  {
    label: "Pros & Cons",
    labelKo: "장단점",
    icon: <CheckCircle2 className="size-4" />,
    prompt: (doc: string) =>
      `Analyze the document "${doc}" and create a detailed comparison of pros and cons for each option or approach described.`,
    promptKo: (doc: string) =>
      `"${doc}" 문서를 분석하고 설명된 각 옵션이나 접근 방식의 장단점을 상세하게 비교해주세요.`,
  },
  {
    label: "Latest Trends",
    labelKo: "최신 동향",
    icon: <Globe className="size-4" />,
    prompt: (doc: string) =>
      `Research the latest industry trends related to the topics in "${doc}" using web search, and compare them with the document's findings.`,
    promptKo: (doc: string) =>
      `"${doc}" 문서의 주제와 관련된 최신 산업 동향을 웹 검색을 통해 조사하고, 문서 내용과 비교 분석해주세요.`,
  },
];

const NO_DOCS_STARTERS = [
  {
    label: "Upload a document",
    labelKo: "문서 업로드하기",
    icon: <Upload className="size-4" />,
    action: "prompt" as const,
    prompt:
      "I'd like to upload a document for research. Please guide me on what file types are supported and how to get started.",
    promptKo:
      "연구를 위해 문서를 업로드하고 싶습니다. 지원되는 파일 형식과 시작 방법을 안내해주세요.",
  },
  {
    label: "What can this tool do?",
    labelKo: "이 도구로 무엇을 할 수 있나요?",
    icon: <Info className="size-4" />,
    action: "intro" as const,
    prompt: "",
    promptKo: "",
  },
  {
    label: "Just chat",
    labelKo: "자유 대화",
    icon: <MessageCircle className="size-4" />,
    action: "prompt" as const,
    prompt: "Hello! What topics are you interested in today?",
    promptKo: "안녕하세요! 오늘 어떤 주제에 관심이 있으신가요?",
  },
];

const chipClass =
  "text-foreground hover:bg-muted border-border/60 h-auto gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-normal whitespace-nowrap transition-colors cursor-pointer inline-flex items-center";

const ThreadSuggestions: FC<{ onShowIntro: () => void }> = ({
  onShowIntro,
}) => {
  const { settings } = useSettings();
  const { documents } = useDocuments();
  const aui = useAui();
  const isKorean = settings.language === "ko-KR";
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null);
  const hasDocuments = documents.length > 0;

  const sendPrompt = (prompt: string) => {
    if (aui.thread.getState().isRunning) return;
    aui.thread.append({
      content: [{ type: "text", text: prompt }],
    });
  };

  const handleStarter = (starter: (typeof NO_DOCS_STARTERS)[number]) => {
    if (starter.action === "intro") {
      onShowIntro();
    } else {
      sendPrompt(isKorean ? starter.promptKo : starter.prompt);
    }
  };

  if (!hasDocuments) {
    return (
      <div className="flex w-full flex-col gap-2 px-4 min-h-[4.5rem]">
        <div className="w-full overflow-x-auto scrollbar-none">
          <div className="mx-auto flex w-max items-center gap-2">
            {NO_DOCS_STARTERS.map((starter) => (
              <button
                key={starter.label}
                className={chipClass}
                onClick={() => handleStarter(starter)}
              >
                {starter.icon}
                {isKorean ? starter.labelKo : starter.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex w-full flex-col gap-2 px-4 min-h-[4.5rem]">
      <div className="w-full">
        <div className="mx-auto flex flex-wrap justify-center gap-2">
          {documents.map((doc) => (
            <button
              key={doc.id}
              className={cn(
                chipClass,
                selectedDoc === doc.name && "bg-muted ring-1 ring-primary/30",
              )}
              onClick={() =>
                setSelectedDoc(selectedDoc === doc.name ? null : doc.name)
              }
            >
              <FileText className="size-4 text-primary/70" />
              {simplifyDocName(doc.name)}
            </button>
          ))}
        </div>
      </div>
      {selectedDoc && (
        <div
          key={selectedDoc}
          className="w-full overflow-x-auto scrollbar-none animate-in fade-in slide-in-from-top-1 duration-200"
        >
          <div className="mx-auto flex w-max items-center gap-2">
            {RESEARCH_ACTIONS.map((action) => (
              <button
                key={action.label}
                className={chipClass}
                onClick={() =>
                  sendPrompt(
                    isKorean
                      ? action.promptKo(selectedDoc)
                      : action.prompt(selectedDoc),
                  )
                }
              >
                {action.icon}
                {isKorean ? action.labelKo : action.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Composer
// ---------------------------------------------------------------------------

type PipelinePhase = "uploading" | "docling" | "llama_stack_upload" | "llama_stack_ingest" | "completed" | "error" | null;

const PIPELINE_STEPS: { key: string; label: string; phases: string[] }[] = [
  { key: "upload", label: "Upload", phases: ["uploading"] },
  { key: "docling", label: "Docling", phases: ["docling"] },
  { key: "llama_stack", label: "Llama Stack", phases: ["llama_stack_upload", "llama_stack_ingest"] },
];

function getPipelineStepState(
  stepPhases: string[],
  currentPhase: PipelinePhase,
): "pending" | "active" | "done" | "error" {
  if (currentPhase === "error") return "error";
  if (currentPhase === "completed") return "done";
  if (!currentPhase) return "pending";

  const phaseOrder = [
    "uploading",
    "docling",
    "llama_stack_upload",
    "llama_stack_ingest",
    "completed",
  ];
  const currentIdx = phaseOrder.indexOf(currentPhase);
  const stepFirstIdx = phaseOrder.indexOf(stepPhases[0]);
  const stepLastIdx = phaseOrder.indexOf(stepPhases[stepPhases.length - 1]);

  if (currentIdx > stepLastIdx) return "done";
  if (currentIdx >= stepFirstIdx && currentIdx <= stepLastIdx) return "active";
  return "pending";
}

const PipelineIndicator: FC<{ phase: PipelinePhase }> = ({ phase }) => (
  <div className="flex items-center justify-center gap-0 px-4 py-1.5">
    {PIPELINE_STEPS.map((step, i) => {
      const state = getPipelineStepState(step.phases, phase);
      return (
        <div key={step.key} className="flex items-center">
          {i > 0 && (
            <div
              className={cn(
                "h-px w-6 transition-colors duration-300",
                state === "done" || state === "active"
                  ? "bg-primary/50"
                  : "bg-border/60",
              )}
            />
          )}
          <div className="flex items-center gap-1.5">
            <div
              className={cn(
                "flex size-4 items-center justify-center rounded-full transition-all duration-300",
                state === "active" &&
                  "bg-primary text-primary-foreground ring-2 ring-primary/20",
                state === "done" && "bg-emerald-500 text-white",
                state === "pending" && "bg-muted-foreground/20",
                state === "error" && "bg-destructive text-white",
              )}
            >
              {state === "done" ? (
                <Check className="size-2.5" />
              ) : state === "active" ? (
                <Loader2 className="size-2.5 animate-spin" />
              ) : state === "error" ? (
                <AlertTriangle className="size-2.5" />
              ) : (
                <div className="size-1.5 rounded-full bg-muted-foreground/40" />
              )}
            </div>
            <span
              className={cn(
                "text-[11px] font-medium transition-colors duration-300",
                state === "active" && "text-primary",
                state === "done" && "text-emerald-600 dark:text-emerald-400",
                state === "pending" && "text-muted-foreground/50",
                state === "error" && "text-destructive",
              )}
            >
              {step.label}
            </span>
          </div>
        </div>
      );
    })}
  </div>
);

const Composer: FC = () => {
  const { settings } = useSettings();
  const { refreshDocuments, uploadStatus, setUploadStatus } = useDocuments();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadPhase, setUploadPhase] = useState<PipelinePhase>(null);
  const [chunkProgress, setChunkProgress] = useState<{ current: number; total: number } | null>(null);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    setUploading(true);
    setUploadPhase("uploading");
    setUploadProgress(0);
    setUploadStatus("Uploading...");

    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
      formData.append("files", files[i]);
    }

    try {
      const res = await fetch(`${API_URL}/upload`, {
        method: "POST",
        body: formData,
      });

      if (res.ok) {
        const data = await res.json();
        const uploadId = data.upload_id;
        if (uploadId) {
          setUploadPhase("docling");
          await pollUploadStatus(uploadId);
        } else {
          setUploadPhase("completed");
          setUploadProgress(100);
          setUploadStatus("Upload complete!");
          setTimeout(() => { setUploadStatus(null); setUploadPhase(null); setUploadProgress(0); }, 3000);
        }
      } else {
        setUploadPhase("error");
        setUploadStatus("Upload failed");
        setTimeout(() => { setUploadStatus(null); setUploadPhase(null); setUploadProgress(0); }, 3000);
      }
    } catch {
      setUploadPhase("error");
      setUploadStatus("Connection error");
      setTimeout(() => { setUploadStatus(null); setUploadPhase(null); setUploadProgress(0); }, 3000);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const pollUploadStatus = async (uploadId: string) => {
    for (let i = 0; i < 300; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        const res = await fetch(`${API_URL}/upload_status/${uploadId}`);
        if (!res.ok) continue;
        const info = await res.json();
        const pct = info.progress || 0;
        const serverPhase = info.phase as PipelinePhase | undefined;
        if (info.status === "completed") {
          setUploadProgress(100);
          setUploadPhase("completed");
          setChunkProgress(null);
          setUploadStatus(info.message || "Processing complete!");
          await refreshDocuments();
          setTimeout(() => { setUploadStatus(null); setUploadPhase(null); setUploadProgress(0); }, 4000);
          return;
        } else if (info.status === "error") {
          setUploadPhase("error");
          setChunkProgress(null);
          setUploadStatus(info.message || "Processing failed");
          setTimeout(() => { setUploadStatus(null); setUploadPhase(null); setUploadProgress(0); }, 5000);
          return;
        } else {
          setUploadProgress(pct);
          if (serverPhase) setUploadPhase(serverPhase);
          if (info.chunk_total && info.chunk_total > 0) {
            setChunkProgress({ current: info.chunk_current || 0, total: info.chunk_total });
          } else {
            setChunkProgress(null);
          }
          setUploadStatus(info.message || "Processing...");
        }
      } catch {
        continue;
      }
    }
    setUploadStatus(null);
    setUploadPhase(null);
    setUploadProgress(0);
  };

  return (
    <div className="relative mx-auto w-full max-w-[var(--thread-max-width)]">
      {uploadPhase && (
        <div className="mb-2 overflow-hidden rounded-xl border border-border/60 bg-muted/50">
          <PipelineIndicator phase={uploadPhase} />
          <div className="flex items-center gap-2.5 border-t border-border/30 px-4 py-1.5">
            {uploadPhase === "error" ? (
              <AlertTriangle className="size-3.5 shrink-0 text-destructive" />
            ) : uploadPhase === "completed" ? (
              <CheckCircle2 className="size-3.5 shrink-0 text-emerald-500" />
            ) : (
              <Loader2 className="size-3.5 shrink-0 animate-spin text-primary" />
            )}
            <span className="truncate text-xs text-muted-foreground">
              {uploadStatus}
            </span>
            {uploadPhase !== "completed" && uploadPhase !== "error" && (
              <span className="ml-auto flex shrink-0 items-center gap-2 text-xs font-medium tabular-nums text-primary">
                {chunkProgress && (
                  <span className="text-muted-foreground">
                    {chunkProgress.current}/{chunkProgress.total} chunks
                  </span>
                )}
                {uploadProgress > 0 && <span>{uploadProgress}%</span>}
              </span>
            )}
          </div>
          <div className="h-1 w-full bg-muted">
            <div
              className={cn(
                "h-full transition-all duration-500 ease-out",
                uploadPhase === "error"
                  ? "bg-destructive"
                  : uploadPhase === "completed"
                    ? "bg-emerald-500"
                    : "bg-primary",
              )}
              style={{ width: `${uploadProgress}%` }}
            />
          </div>
        </div>
      )}
      <ComposerPrimitive.Root className="relative flex w-full flex-col">
        <div className="border-border/60 focus-within:border-border flex w-full flex-col gap-2 rounded-[var(--composer-radius)] border bg-[var(--composer-bg)] p-[var(--composer-padding)] shadow-[0_4px_16px_-8px_rgba(0,0,0,0.08),0_1px_2px_rgba(0,0,0,0.04)] transition-[border-color,box-shadow] focus-within:shadow-[0_6px_24px_-8px_rgba(0,0,0,0.12),0_1px_2px_rgba(0,0,0,0.05)]">
          <ComposerPrimitive.Input
            placeholder={
              settings.language === "ko-KR"
                ? "연구 질문을 입력하세요..."
                : "Ask a research question..."
            }
            className="min-h-10 w-full resize-none bg-transparent px-2.5 py-1 text-base outline-none placeholder:text-muted-foreground/80"
          />
          <ComposerActions fileInputRef={fileInputRef} uploading={uploading} />
        </div>
      </ComposerPrimitive.Root>
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".pdf,.txt,.md,.docx,.pptx"
        onChange={handleFileUpload}
        className="hidden"
      />
    </div>
  );
};

function ComposerActions({
  fileInputRef,
  uploading,
}: {
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  uploading: boolean;
}) {
  return (
    <div className="relative flex items-center justify-between">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="inline-flex size-7 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
          aria-label="Upload document"
        >
          <Paperclip className="size-4" />
        </button>
      </div>
      <div className="flex items-center gap-1.5">
        <AuiIf condition={(s) => !s.thread.isRunning}>
          <ComposerPrimitive.Send asChild>
            <button
              type="button"
              className="inline-flex size-7 items-center justify-center rounded-full bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              aria-label="Send message"
            >
              <ArrowUpIcon className="size-4" />
            </button>
          </ComposerPrimitive.Send>
        </AuiIf>
        <AuiIf condition={(s) => s.thread.isRunning}>
          <ComposerPrimitive.Cancel asChild>
            <button
              type="button"
              className="inline-flex size-7 items-center justify-center rounded-full bg-destructive text-white"
              aria-label="Stop generating"
            >
              <SquareIcon className="size-3 fill-current" />
            </button>
          </ComposerPrimitive.Cancel>
        </AuiIf>
      </div>
    </div>
  );
}
