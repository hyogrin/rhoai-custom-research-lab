"use client";

import { CheckCircle, XCircle, BarChart3, Repeat, AlertTriangle } from "lucide-react";

type HumanReviewProps = {
  qualityScore: number;
  qualityThreshold: number;
  iteration: number;
  maxIterations: number;
  improvements: string[];
  onAccept: () => void;
  onContinue: () => void;
};

export function HumanReviewCard({
  qualityScore,
  qualityThreshold,
  iteration,
  maxIterations,
  improvements,
  onAccept,
  onContinue,
}: HumanReviewProps) {
  const scorePercent = (qualityScore / 10) * 100;
  const thresholdPercent = (qualityThreshold / 10) * 100;

  return (
    <div className="mx-auto my-4 w-full max-w-lg rounded-lg border border-border bg-card p-5 shadow-md">
      {/* Header */}
      <div className="mb-4 flex items-center gap-2 text-amber-400">
        <AlertTriangle className="h-5 w-5" />
        <h3 className="text-sm font-semibold">Human Review Required</h3>
      </div>

      {/* Quality Score Gauge */}
      <div className="mb-4 space-y-2">
        <div className="flex items-center justify-between text-sm">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <BarChart3 className="h-4 w-4" />
            Quality Score
          </span>
          <span className="font-mono font-semibold">
            {qualityScore.toFixed(1)} / 10
          </span>
        </div>
        <div className="relative h-3 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-gradient-to-r from-red-500 via-amber-400 to-green-500 transition-all"
            style={{ width: `${scorePercent}%` }}
          />
          {/* Threshold marker */}
          <div
            className="absolute top-0 h-full w-0.5 bg-foreground/60"
            style={{ left: `${thresholdPercent}%` }}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Threshold: {qualityThreshold} | Below target by{" "}
          {(qualityThreshold - qualityScore).toFixed(1)} points
        </p>
      </div>

      {/* Iteration Info */}
      <div className="mb-4 flex items-center gap-1.5 text-sm text-muted-foreground">
        <Repeat className="h-4 w-4" />
        <span>
          Completed {iteration} of {maxIterations} iterations
        </span>
      </div>

      {/* Improvement Suggestions */}
      {improvements.length > 0 && (
        <div className="mb-4 rounded-md bg-muted/50 p-3">
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">
            Suggested Improvements
          </p>
          <ul className="space-y-1">
            {improvements.map((imp, i) => (
              <li key={i} className="text-xs text-foreground/80">
                • {imp}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3">
        <button
          onClick={onAccept}
          className="flex flex-1 items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          <CheckCircle className="h-4 w-4" />
          Accept Result
        </button>
        <button
          onClick={onContinue}
          className="flex flex-1 items-center justify-center gap-2 rounded-md border border-border bg-card px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent"
        >
          <Repeat className="h-4 w-4" />
          Continue Iterating
        </button>
      </div>
    </div>
  );
}
