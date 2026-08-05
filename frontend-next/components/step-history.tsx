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
  CheckCircle,
} from "lucide-react";
import { useState } from "react";

export type StepEntry = {
  id: string;
  phase: string;
  icon: string;
  title: string;
  detail?: string;
  timestamp: number;
};

type StepHistoryProps = {
  steps: StepEntry[];
  visible: boolean;
};

const phaseIcons: Record<string, React.ReactNode> = {
  normalize: <RefreshCw className="h-3.5 w-3.5" />,
  classify_intent: <MessageSquare className="h-3.5 w-3.5" />,
  direct_response: <MessageSquare className="h-3.5 w-3.5" />,
  plan: <Brain className="h-3.5 w-3.5" />,
  execute: <Search className="h-3.5 w-3.5" />,
  verify: <ShieldCheck className="h-3.5 w-3.5" />,
  observe: <BarChart3 className="h-3.5 w-3.5" />,
  iterate: <Layers className="h-3.5 w-3.5" />,
  finalize: <CheckCircle className="h-3.5 w-3.5" />,
  web_search: <Globe className="h-3.5 w-3.5" />,
  parallel: <Zap className="h-3.5 w-3.5" />,
  section: <FileText className="h-3.5 w-3.5" />,
};

function getPhaseIcon(phase: string) {
  return phaseIcons[phase] || <RefreshCw className="h-3.5 w-3.5" />;
}

export function StepHistory({ steps, visible }: StepHistoryProps) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!visible || steps.length === 0) return null;

  return (
    <div className="mx-auto mb-4 w-full max-w-2xl">
      <div className="rounded-lg border border-border bg-card/50 p-3">
        <h4 className="mb-2 text-xs font-medium text-muted-foreground">
          Processing Steps ({steps.length})
        </h4>
        <div className="space-y-1">
          {steps.map((step) => (
            <button
              key={step.id}
              onClick={() =>
                setExpanded(expanded === step.id ? null : step.id)
              }
              className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-accent"
            >
              <span className="mt-0.5 text-muted-foreground">
                {getPhaseIcon(step.phase)}
              </span>
              <div className="flex-1 overflow-hidden">
                <span className="font-medium text-foreground">
                  {step.title}
                </span>
                {expanded === step.id && step.detail && (
                  <p className="mt-1 whitespace-pre-wrap text-muted-foreground">
                    {step.detail}
                  </p>
                )}
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
