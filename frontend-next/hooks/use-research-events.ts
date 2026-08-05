"use client";

import { useEffect, useRef, useState } from "react";
import { useAgUiState } from "@assistant-ui/react-ag-ui";
import { useCitations, type CitationSource } from "@/contexts/citation-context";
import type { ReviewData } from "@/components/elements/iteration-review-card";

export type StepEntry = {
  id: string;
  phase: string;
  icon: string;
  title: string;
  detail: string;
  timestamp: number;
};

export type VerboseEvent = {
  id: string;
  type: string;
  timestamp: number;
  data: Record<string, unknown>;
};

type ResearchState = {
  steps?: StepEntry[];
  verbose?: VerboseEvent[];
  sources?: { sources: CitationSource[] };
  iteration_review?: ReviewData | null;
};

export function useResearchEvents() {
  const state = useAgUiState<ResearchState>();
  const { setSources } = useCitations();
  const prevSourcesRef = useRef<string>("");
  const [stickyReview, setStickyReview] = useState<ReviewData | null>(null);

  useEffect(() => {
    const incoming = state?.sources?.sources;
    if (!incoming || incoming.length === 0) return;
    const key = JSON.stringify(incoming);
    if (key === prevSourcesRef.current) return;
    prevSourcesRef.current = key;
    setSources(incoming);
  }, [state?.sources, setSources]);

  useEffect(() => {
    const review = state?.iteration_review;
    if (review && review.quality_score != null) {
      setStickyReview(review);
    }
  }, [state?.iteration_review]);

  const clearReview = () => setStickyReview(null);

  return {
    steps: state?.steps ?? [],
    verbose: state?.verbose ?? [],
    iterationReview: stickyReview,
    clearReview,
  };
}
