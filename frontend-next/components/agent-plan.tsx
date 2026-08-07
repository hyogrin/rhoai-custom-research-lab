"use client";

import {
  Search,
  Globe,
  ShieldCheck,
  Brain,
  Layers,
  FileText,
  BarChart3,
  RefreshCw,
  MessageSquare,
  Zap,
  CheckCircle2,
  Loader2,
} from "lucide-react";
import { useState } from "react";
import { useAuiState } from "@assistant-ui/react";
import { cn } from "@/lib/utils";
import type { StepEntry } from "@/hooks/use-research-events";

type AgentPlanProps = {
  steps: StepEntry[];
  visible: boolean;
};

const phaseIcons: Record<string, React.ReactNode> = {
  normalize: <RefreshCw className="size-3.5" />,
  classify_intent: <MessageSquare className="size-3.5" />,
  direct_response: <MessageSquare className="size-3.5" />,
  plan: <Brain className="size-3.5" />,
  execute: <Search className="size-3.5" />,
  verify: <ShieldCheck className="size-3.5" />,
  observe: <BarChart3 className="size-3.5" />,
  iterate: <Layers className="size-3.5" />,
  finalize: <CheckCircle2 className="size-3.5" />,
  web_search: <Globe className="size-3.5" />,
  parallel: <Zap className="size-3.5" />,
  section: <FileText className="size-3.5" />,
};

function getPhaseIcon(phase: string) {
  return phaseIcons[phase] || <RefreshCw className="size-3.5" />;
}

function getPhaseColor(phase: string) {
  const colors: Record<string, string> = {
    plan: "text-violet-500",
    execute: "text-blue-500",
    verify: "text-emerald-500",
    observe: "text-amber-500",
    iterate: "text-orange-500",
    finalize: "text-emerald-600",
    web_search: "text-sky-500",
    parallel: "text-yellow-500",
  };
  return colors[phase] || "text-muted-foreground";
}

export function AgentPlan({ steps, visible }: AgentPlanProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const isThreadRunning = useAuiState((s) => s.thread.isRunning);

  if (!visible || steps.length === 0) return null;

  return (
    <div className="mx-auto w-full max-w-[var(--thread-max-width,42rem)] px-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div className="rounded-xl border border-border/50 bg-card/50 backdrop-blur-sm overflow-hidden shadow-sm">
        <div className="flex items-center gap-2 border-b border-border/30 px-4 py-2.5">
          <div className="flex size-5 items-center justify-center rounded-md bg-primary/10">
            <Brain className="size-3 text-primary" />
          </div>
          <span className="text-xs font-semibold text-foreground tracking-wide">
            Agent Harness
          </span>
          <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground tabular-nums">
            {steps.length} steps
          </span>
        </div>

        <div className="relative px-4 py-2">
          <div className="absolute left-[1.78rem] top-2 bottom-2 w-px bg-border/40" />

          <div className="space-y-0.5">
            {steps.map((step, index) => {
              const isLast = index === steps.length - 1;
              const isInProgress = isLast && isThreadRunning;
              const isExpanded = expandedId === step.id;
              const phaseColor = getPhaseColor(step.phase);

              return (
                <button
                  key={step.id}
                  onClick={() =>
                    setExpandedId(isExpanded ? null : step.id)
                  }
                  className={cn(
                    "group relative flex w-full items-start gap-3 rounded-lg px-1 py-1.5 text-left text-xs transition-all duration-150",
                    "hover:bg-muted/40",
                    isExpanded && "bg-muted/30",
                  )}
                >
                  <div
                    className={cn(
                      "relative z-10 flex size-5 shrink-0 items-center justify-center rounded-full border bg-background transition-all duration-200",
                      isInProgress
                        ? "border-primary/50 shadow-[0_0_0_2px_rgba(var(--color-primary),0.1)]"
                        : "border-border/60",
                    )}
                  >
                    {isInProgress ? (
                      <Loader2 className={cn("size-3 animate-spin", phaseColor)} />
                    ) : (
                      <CheckCircle2 className="size-3 text-emerald-500" />
                    )}
                  </div>

                  <div className="flex-1 min-w-0 pt-0.5">
                    <div className="flex items-center gap-2">
                      <span className={cn("shrink-0", phaseColor)}>
                        {getPhaseIcon(step.phase)}
                      </span>
                      <span className="font-medium text-foreground truncate">
                        {step.title}
                      </span>
                      <span className="ml-auto shrink-0 text-[10px] text-muted-foreground/60 tabular-nums">
                        {new Date(step.timestamp).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                        })}
                      </span>
                    </div>

                    {isExpanded && step.detail && (
                      <p className="mt-1.5 whitespace-pre-wrap text-muted-foreground leading-relaxed animate-in fade-in slide-in-from-top-1 duration-150">
                        {step.detail}
                      </p>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
