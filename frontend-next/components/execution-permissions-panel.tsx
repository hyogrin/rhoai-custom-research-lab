"use client";

import { useExecutionPermissions } from "@/app/providers";
import type { ExecutionPermissionSettings } from "@/app/providers";

type ExecutionPermissionsPanelProps = {
  visible: boolean;
};

export function ExecutionPermissionsPanel({ visible }: ExecutionPermissionsPanelProps) {
  const { executionPermissions, setExecutionPermissions } = useExecutionPermissions();

  if (!visible) return null;

  const update = (partial: Partial<ExecutionPermissionSettings>) => {
    setExecutionPermissions({ ...executionPermissions, ...partial });
  };

  return (
    <div className="execution-permissions-panel">
      <h4 className="panel-subtitle">Execution Permissions</h4>

      <div className="setting-row">
        <label className="setting-label">Require Approval</label>
        <input
          type="checkbox"
          checked={executionPermissions.requireApproval}
          onChange={(e) => update({ requireApproval: e.target.checked })}
        />
      </div>

      <div className="setting-row">
        <label className="setting-label">Network Access</label>
        <span className="setting-value-fixed">deny</span>
      </div>

      <div className="setting-row">
        <label className="setting-label">CPU</label>
        <input
          type="text"
          className="setting-input"
          value={executionPermissions.cpu}
          onChange={(e) => update({ cpu: e.target.value })}
        />
      </div>

      <div className="setting-row">
        <label className="setting-label">Memory</label>
        <input
          type="text"
          className="setting-input"
          value={executionPermissions.memory}
          onChange={(e) => update({ memory: e.target.value })}
        />
      </div>

      <div className="setting-row">
        <label className="setting-label">Timeout (seconds)</label>
        <input
          type="number"
          className="setting-input"
          value={executionPermissions.timeoutSeconds}
          onChange={(e) => update({ timeoutSeconds: parseInt(e.target.value) || 60 })}
        />
      </div>
    </div>
  );
}
