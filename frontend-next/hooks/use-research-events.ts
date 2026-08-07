"use client";

import { useEffect, useRef, useState } from "react";
import { useAgUiState } from "@assistant-ui/react-ag-ui";
import { useCitations, type CitationSource } from "@/contexts/citation-context";
import type { ReviewData } from "@/components/elements/iteration-review-card";
import type { ExecutionPermissionData } from "@/components/execution-permission-card";

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
  execution_permission?: ExecutionPermissionData | null;
  claim_evidence_artifact?: {
    artifact_id: string;
    type: string;
    format: string;
    svg_data: string;
    title: string;
    execution_id: string;
    metadata?: Record<string, unknown>;
  } | null;
  artifact_status?: string;
};

export function useResearchEvents() {
  const state = useAgUiState<ResearchState>();
  const { setSources } = useCitations();
  const prevSourcesRef = useRef<string>("");
  const [stickyReview, setStickyReview] = useState<ReviewData | null>(null);
  const [executionPermission, setExecutionPermission] = useState<ExecutionPermissionData | null>(null);

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

  useEffect(() => {
    const perm = state?.execution_permission;
    if (perm && perm.type === "execution_permission") {
      setExecutionPermission(perm);
    }
  }, [state?.execution_permission]);

  const clearReview = () => setStickyReview(null);
  const clearExecutionPermission = () => setExecutionPermission(null);

  return {
    steps: state?.steps ?? [],
    verbose: state?.verbose ?? [],
    iterationReview: stickyReview,
    clearReview,
    executionPermission,
    clearExecutionPermission,
    claimEvidenceArtifact: state?.claim_evidence_artifact ?? null,
    artifactStatus: state?.artifact_status ?? "disabled",
  };
}
