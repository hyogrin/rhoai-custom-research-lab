"use client";

import { useState } from "react";
import { useAui } from "@assistant-ui/react";

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

export function ExecutionPermissionCard({ data }: ExecutionPermissionCardProps) {
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
      <div className="execution-permission-card resolved">
        <div className="permission-status approved">Execution approved</div>
      </div>
    );
  }

  if (resolved === "denied") {
    return (
      <div className="execution-permission-card resolved">
        <div className="permission-status denied">Execution denied — report finalized without graph</div>
      </div>
    );
  }

  return (
    <div className="execution-permission-card">
      <div className="permission-header">
        <span className="permission-icon">🔒</span>
        <span className="permission-title">Execution Permission Required</span>
      </div>

      <div className="permission-purpose">{data.purpose}</div>

      <div className="permission-details">
        <div className="detail-row">
          <span className="detail-label">Command:</span>
          <code className="detail-value">{data.command.join(" ")}</code>
        </div>
        <div className="detail-row">
          <span className="detail-label">Network:</span>
          <span className="detail-value detail-deny">{data.permissions.network}</span>
        </div>
        <div className="detail-row">
          <span className="detail-label">CPU / Memory:</span>
          <span className="detail-value">{data.permissions.cpu} / {data.permissions.memory}</span>
        </div>
        <div className="detail-row">
          <span className="detail-label">Timeout:</span>
          <span className="detail-value">{data.permissions.timeout_seconds}s</span>
        </div>
      </div>

      <div className="permission-actions">
        <button className="btn-approve" onClick={handleApprove}>
          Approve Once
        </button>
        <button className="btn-deny" onClick={handleDeny}>
          Deny
        </button>
      </div>
    </div>
  );
}
