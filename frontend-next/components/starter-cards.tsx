"use client";

import { Upload, Search, GitCompare } from "lucide-react";
import { useSettings } from "@/app/providers";

type Starter = {
  label: string;
  message: string;
  icon: React.ReactNode;
};

const starters: Record<string, Starter[]> = {
  "en-US": [
    {
      label: "Upload a document",
      message: "Upload a document for research",
      icon: <Upload className="h-5 w-5" />,
    },
    {
      label: "Summarize with citations",
      message:
        "Analyze the key findings and provide a comprehensive, business and technical value-added summary with citations.",
      icon: <Search className="h-5 w-5" />,
    },
    {
      label: "Compare arguments",
      message:
        "Compare and contrast the main arguments presented, business and technical value-added in the uploaded documents.",
      icon: <GitCompare className="h-5 w-5" />,
    },
  ],
  "ko-KR": [
    {
      label: "문서 업로드",
      message: "리서치를 위한 문서를 업로드합니다",
      icon: <Upload className="h-5 w-5" />,
    },
    {
      label: "인용 포함 요약",
      message:
        "핵심 내용을 분석하고 사업적, 기술적 가치 두 측면에 대해 인용을 포함한 종합적인 요약을 제공해주세요.",
      icon: <Search className="h-5 w-5" />,
    },
    {
      label: "논점 비교",
      message:
        "업로드된 문서에 제시된 주요 논점들을 사업적, 기술적 가치 두 측면에 대해 비교 분석해주세요.",
      icon: <GitCompare className="h-5 w-5" />,
    },
  ],
};

type StarterCardsProps = {
  onSelect: (message: string) => void;
};

export function StarterCards({ onSelect }: StarterCardsProps) {
  const { settings } = useSettings();
  const cards = starters[settings.language] || starters["en-US"];

  return (
    <div className="mx-auto grid w-full max-w-2xl grid-cols-1 gap-3 px-4 sm:grid-cols-3">
      {cards.map((starter) => (
        <button
          key={starter.label}
          onClick={() => onSelect(starter.message)}
          className="flex flex-col items-center gap-2 rounded-lg border border-border bg-card p-4 text-center shadow-sm transition-all hover:border-primary/50 hover:shadow-md"
        >
          <span className="text-primary">{starter.icon}</span>
          <span className="text-sm font-medium text-foreground">
            {starter.label}
          </span>
        </button>
      ))}
    </div>
  );
}
