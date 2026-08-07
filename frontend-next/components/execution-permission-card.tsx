"use client";

import { useState, type FC } from "react";
import { useAui } from "@assistant-ui/react";
import {
  CheckCircle2,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  Terminal,
  Wifi,
  WifiOff,
  Cpu,
  Timer,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type ExecutionPermissionData = {
  type: "execution_permission";
  execution_id: string;
  artifact_type: string;
  purpose: string;
  command: string[];
  permissions: {
    network: string;
    read_only: string[];
    read_write: string[];
    cpu: string;
    memory: string;
    timeout_seconds: number;
  };
};

type ExecutionPermissionCardProps = {
  data: ExecutionPermissionData;
};

export const ExecutionPermissionCard: FC<ExecutionPermissionCardProps> = ({
  data,
}) => {
  const [resolved, setResolved] = useState<"approved" | "denied" | null>(null);
  const aui = useAui();

  const handleApprove = () => {
    setResolved("approved");
    aui.thread.append({
      content: [{ type: "text", text: "__execution_approve__" }],
    });
  };

  const handleDeny = () => {
    setResolved("denied");
    aui.thread.append({
      content: [{ type: "text", text: "__execution_deny__" }],
    });
  };

  if (resolved === "approved") {
    return (
      <div className="review-card review-card--resolved">
        <div className="flex items-center gap-2 text-sm">
          <ShieldCheck className="size-4 text-emerald-500" />
          <span className="text-muted-foreground">
            Sandbox execution approved — generating graph...
          </span>
        </div>
      </div>
    );
  }

  if (resolved === "denied") {
    return (
      <div className="review-card review-card--resolved">
        <div className="flex items-center gap-2 text-sm">
          <ShieldX className="size-4 text-red-400" />
          <span className="text-muted-foreground">
            Execution denied — report finalized without graph
          </span>
        </div>
      </div>
    );
  }

  const networkDenied = data.permissions.network === "deny";

  return (
    <div className="review-card">
      <div className="flex items-center gap-3">
        <span className="review-card__icon">
          <ShieldAlert className="size-4" />
        </span>
        <div className="flex flex-col">
          <p className="text-[13.5px] font-medium">Execution Permission</p>
          <p className="text-xs text-muted-foreground">{data.purpose}</p>
        </div>
      </div>

      <div className="review-card__suggestions">
        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground mb-2">
          <Terminal className="size-3" />
          Sandbox Details
        </div>
        <div className="space-y-2">
          <div className="flex items-start gap-2 text-xs">
            <Terminal className="size-3 mt-0.5 shrink-0 text-muted-foreground/60" />
            <code className="text-[11px] leading-relaxed break-all text-muted-foreground font-mono">
              {data.command.join(" ")}
            </code>
          </div>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              {networkDenied ? (
                <WifiOff className="size-3 text-emerald-500" />
              ) : (
                <Wifi className="size-3 text-amber-500" />
              )}
              <span className={cn(networkDenied && "text-emerald-600")}>
                {networkDenied ? "Network blocked" : data.permissions.network}
              </span>
            </span>
            <span className="inline-flex items-center gap-1">
              <Cpu className="size-3" />
              {data.permissions.cpu} / {data.permissions.memory}
            </span>
            <span className="inline-flex items-center gap-1">
              <Timer className="size-3" />
              {data.permissions.timeout_seconds}s
            </span>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={handleDeny}
          className="review-card__btn review-card__btn--secondary"
        >
          Deny
        </button>
        <button
          type="button"
          onClick={handleApprove}
          className="review-card__btn review-card__btn--primary"
        >
          <CheckCircle2 className="size-3.5" />
          Approve Once
        </button>
      </div>
    </div>
  );
};
