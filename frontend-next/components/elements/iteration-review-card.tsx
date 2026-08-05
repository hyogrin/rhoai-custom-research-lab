"use client";

import { useState, useEffect, type FC } from "react";
import { useAui } from "@assistant-ui/react";
import {
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type ReviewData = {
  quality_score: number;
  quality_threshold: number;
  iteration: number;
  max_iterations: number;
  improvements: string[];
  can_iterate: boolean;
  quality_met?: boolean;
};

interface IterationReviewCardProps {
  review: ReviewData;
  isKorean?: boolean;
  onDismiss?: () => void;
}

export const IterationReviewCard: FC<IterationReviewCardProps> = ({
  review,
  isKorean = false,
  onDismiss,
}) => {
  const aui = useAui();
  const [direction, setDirection] = useState("");
  const [state, setState] = useState<"idle" | "accepted" | "continuing" | "completing">("idle");

  const qualityMet = review.quality_met ?? review.quality_score >= review.quality_threshold;
  const scorePercent = Math.min(
    (review.quality_score / review.quality_threshold) * 100,
    100,
  );

  // Auto-complete when quality is met: send accept after a short delay
  useEffect(() => {
    if (qualityMet && state === "idle") {
      const timer = setTimeout(() => {
        setState("completing");
        aui.thread.append({
          content: [{ type: "text", text: "accept" }],
        });
        setTimeout(() => onDismiss?.(), 3000);
      }, 2500);
      return () => clearTimeout(timer);
    }
  }, [qualityMet, state, aui, onDismiss]);

  const handleAccept = () => {
    setState("accepted");
    aui.thread.append({
      content: [{ type: "text", text: "accept" }],
    });
    setTimeout(() => onDismiss?.(), 2000);
  };

  const handleContinue = () => {
    const text = direction.trim() || "Continue improving";
    setState("continuing");
    aui.thread.append({
      content: [{ type: "text", text }],
    });
    setTimeout(() => onDismiss?.(), 2000);
  };

  const handleComplete = () => {
    setState("completing");
    aui.thread.append({
      content: [{ type: "text", text: "accept" }],
    });
    setTimeout(() => onDismiss?.(), 2000);
  };

  // --- Resolved states ---

  if (state === "accepted") {
    return (
      <div className="review-card review-card--resolved">
        <div className="flex items-center gap-2 text-sm">
          <CheckCircle2 className="size-4 text-emerald-500" />
          <span className="text-muted-foreground">
            {isKorean ? "현재 결과를 확정합니다" : "Result accepted"}
          </span>
        </div>
      </div>
    );
  }

  if (state === "continuing") {
    return (
      <div className="review-card review-card--resolved">
        <div className="flex items-center gap-2 text-sm">
          <RefreshCw className="size-4 animate-spin text-primary" />
          <span className="text-muted-foreground">
            {isKorean ? "다음 iteration을 진행합니다..." : "Continuing to next iteration..."}
          </span>
        </div>
      </div>
    );
  }

  if (state === "completing") {
    return (
      <div className="review-card review-card--resolved">
        <div className="flex items-center gap-2 text-sm">
          <CheckCircle2 className="size-4 text-emerald-500" />
          <span className="text-muted-foreground">
            {isKorean ? "연구를 완료합니다..." : "Completing research..."}
          </span>
        </div>
      </div>
    );
  }

  // --- Quality met: minimal card with single "Complete" button ---

  if (qualityMet) {
    return (
      <div className="review-card">
        <div className="flex items-center gap-3">
          <span className="review-card__icon review-card__icon--success">
            <CheckCircle2 className="size-4" />
          </span>
          <div className="flex flex-col">
            <p className="text-[13.5px] font-medium">
              {isKorean ? "품질 목표 달성" : "Quality Target Met"}
            </p>
            <p className="text-xs text-muted-foreground">
              {review.quality_score.toFixed(1)} / {review.quality_threshold.toFixed(1)}
              {" — "}Iteration {review.iteration}
            </p>
          </div>
        </div>

        <div className="review-card__score-section">
          <div className="review-card__score-bar">
            <div
              className="review-card__score-fill bg-emerald-500"
              style={{ width: "100%" }}
            />
          </div>
        </div>

        <div className="flex items-center justify-end">
          <button
            type="button"
            onClick={handleComplete}
            className="review-card__btn review-card__btn--primary"
          >
            <CheckCircle2 className="size-3.5" />
            {isKorean ? "완료" : "Complete"}
          </button>
        </div>
      </div>
    );
  }

  // --- Quality not met: full review card ---

  const isClose = review.quality_score >= review.quality_threshold * 0.85;

  return (
    <div className="review-card">
      <div className="flex items-center gap-3">
        <span className="review-card__icon">
          <Sparkles className="size-4" />
        </span>
        <div className="flex flex-col">
          <p className="text-[13.5px] font-medium">
            {isKorean ? "Iteration 리뷰" : "Iteration Review"}
          </p>
          <p className="text-xs text-muted-foreground">
            Iteration {review.iteration} / {review.max_iterations}
          </p>
        </div>
      </div>

      <div className="review-card__score-section">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium">
            {isKorean ? "품질 점수" : "Quality Score"}
          </span>
          <span
            className={cn(
              "font-mono font-semibold tabular-nums",
              isClose ? "text-amber-600" : "text-red-500",
            )}
          >
            {review.quality_score.toFixed(1)} / {review.quality_threshold.toFixed(1)}
          </span>
        </div>
        <div className="review-card__score-bar">
          <div
            className={cn(
              "review-card__score-fill",
              isClose ? "bg-amber-500" : "bg-red-400",
            )}
            style={{ width: `${scorePercent}%` }}
          />
          <div className="review-card__score-threshold" style={{ left: "100%" }} />
        </div>
      </div>

      {review.improvements.length > 0 && (
        <div className="review-card__suggestions">
          <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground mb-2">
            <AlertTriangle className="size-3" />
            {isKorean ? "개선 제안" : "Improvement Suggestions"}
          </div>
          <ul className="space-y-1.5">
            {review.improvements.map((imp, i) => (
              <li key={i} className="review-card__suggestion-item">
                {imp}
              </li>
            ))}
          </ul>
        </div>
      )}

      {review.can_iterate && (
        <div className="review-card__input-section">
          <input
            type="text"
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleContinue();
              }
            }}
            placeholder={
              isKorean
                ? "다음 iteration에 대한 방향을 입력하세요..."
                : "Add direction for next iteration..."
            }
            className="review-card__input"
          />
        </div>
      )}

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={handleAccept}
          className="review-card__btn review-card__btn--secondary"
        >
          {isKorean ? "현재 결과 확정" : "Accept as-is"}
        </button>
        {review.can_iterate && (
          <button
            type="button"
            onClick={handleContinue}
            className="review-card__btn review-card__btn--primary"
          >
            {isKorean ? "계속" : "Continue"}
            <ArrowRight className="size-3.5" />
          </button>
        )}
      </div>
    </div>
  );
};
