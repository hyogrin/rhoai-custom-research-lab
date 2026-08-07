"use client";

type ClaimEvidenceGraphProps = {
  artifact: {
    artifact_id: string;
    type: string;
    format: string;
    svg_data: string;
    title: string;
    execution_id: string;
    metadata?: Record<string, unknown>;
  } | null;
  status: string;
  error?: string;
};

export function ClaimEvidenceGraph({ artifact, status, error }: ClaimEvidenceGraphProps) {
  if (status === "disabled") return null;

  if (status === "denied") {
    return (
      <div className="claim-evidence-graph-container">
        <div className="ceg-status denied">
          Claim-Evidence Graph was not generated (execution denied).
        </div>
      </div>
    );
  }

  if (status === "failed") {
    return (
      <div className="claim-evidence-graph-container">
        <div className="ceg-status failed">
          Claim-Evidence Graph generation failed{error ? `: ${error}` : ""}.
        </div>
      </div>
    );
  }

  if (!artifact || !artifact.svg_data) {
    if (status === "planning" || status === "permission_required" || status === "running") {
      return (
        <div className="claim-evidence-graph-container">
          <div className="ceg-status loading">
            Generating Claim-Evidence Graph...
          </div>
        </div>
      );
    }
    return null;
  }

  return (
    <div className="claim-evidence-graph-container">
      <div className="ceg-header">
        <h3 className="ceg-title">{artifact.title || "Claim-Evidence Graph"}</h3>
      </div>
      <div
        className="ceg-svg-wrapper"
        dangerouslySetInnerHTML={{ __html: artifact.svg_data }}
      />
      <details className="ceg-details">
        <summary>Execution Details</summary>
        <div className="ceg-details-content">
          <p>Artifact ID: {artifact.artifact_id}</p>
          <p>Execution ID: {artifact.execution_id}</p>
          {artifact.metadata && (
            <p>Nodes: {String(artifact.metadata.nodes_rendered ?? "?")} | Edges: {String(artifact.metadata.edges_rendered ?? "?")}</p>
          )}
        </div>
      </details>
    </div>
  );
}
