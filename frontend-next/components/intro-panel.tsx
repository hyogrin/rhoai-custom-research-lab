"use client";

import {
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  FileUp,
  Globe,
  RefreshCw,
  Search,
  ShieldCheck,
  Users,
} from "lucide-react";
import { introContent, type IntroContent } from "@/lib/intro-content";

const featureIcons: Record<string, React.ReactNode> = {
  upload: <FileUp className="size-5" />,
  iteration: <RefreshCw className="size-5" />,
  web: <Globe className="size-5" />,
  citation: <BookOpen className="size-5" />,
  verify: <ShieldCheck className="size-5" />,
  hitl: <Users className="size-5" />,
};

type IntroPanelProps = {
  language: string;
  onClose: () => void;
};

export function IntroPanel({ language, onClose }: IntroPanelProps) {
  const content: IntroContent =
    introContent[language] || introContent["en-US"];
  const isKorean = language === "ko-KR";

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
      {/* Header */}
      <div className="flex items-start gap-3">
        <button
          onClick={onClose}
          className="mt-1 inline-flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted"
          aria-label="Back"
        >
          <ArrowLeft className="size-4" />
        </button>
        <div>
          <h2 className="text-xl font-semibold">{content.title}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {content.subtitle}
          </p>
        </div>
      </div>

      {/* Features */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {content.features.map((f) => (
          <div
            key={f.icon}
            className="flex gap-3 rounded-lg border border-border/60 bg-card p-3.5 shadow-sm"
          >
            <span className="mt-0.5 shrink-0 text-primary">
              {featureIcons[f.icon] ?? <Search className="size-5" />}
            </span>
            <div className="min-w-0">
              <div className="text-sm font-medium">{f.title}</div>
              <div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                {f.desc}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Workflow */}
      <div>
        <h3 className="mb-3 text-sm font-semibold text-muted-foreground uppercase tracking-wider">
          {isKorean ? "하네스 내부 루프" : "Harness Inner Loop"}
        </h3>
        <div className="flex items-stretch gap-1">
          {content.workflow.map((w, i) => (
            <div key={w.step} className="flex flex-1 items-stretch gap-1">
              <div className="flex flex-1 flex-col items-center rounded-lg border border-border/60 bg-card p-3 text-center shadow-sm">
                <span className="flex size-7 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                  {w.step}
                </span>
                <span className="mt-1.5 text-sm font-medium">{w.title}</span>
                <span className="mt-1 text-[11px] leading-snug text-muted-foreground">
                  {w.desc}
                </span>
              </div>
              {i < content.workflow.length - 1 && (
                <span className="flex items-center text-muted-foreground/40">
                  →
                </span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Tech stack */}
      <div>
        <h3 className="mb-2 text-sm font-semibold text-muted-foreground uppercase tracking-wider">
          {isKorean ? "핵심 기술" : "Key Technologies"}
        </h3>
        <div className="flex flex-wrap gap-2">
          {content.techs.map((t) => (
            <span
              key={t.name}
              className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-muted/40 px-3 py-1 text-xs"
            >
              <CheckCircle2 className="size-3 text-primary/70" />
              <span className="font-medium">{t.name}</span>
              <span className="text-muted-foreground">— {t.purpose}</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
