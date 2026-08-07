#!/usr/bin/env python3
"""Trusted Claim-Evidence Graph renderer.

Reads a validated JSON specification and produces an SVG visualization.
This script runs INSIDE an OpenShell sandbox with restricted permissions.

Usage:
    python3 claim_evidence_renderer.py /tmp/input/claim_evidence.json /tmp/output/claim-evidence.svg
"""

import html
import json
import math
import sys
from pathlib import Path


def sanitize_text(text: str) -> str:
    """Escape text for safe SVG embedding."""
    return html.escape(text, quote=True)


def wrap_text(text: str, max_width: int = 25) -> list[str]:
    """Wrap text into lines of approximately max_width characters."""
    words = text.split()
    lines: list[str] = []
    current_line = ""
    for word in words:
        if len(current_line) + len(word) + 1 > max_width and current_line:
            lines.append(current_line)
            current_line = word
        else:
            current_line = f"{current_line} {word}" if current_line else word
    if current_line:
        lines.append(current_line)
    return lines or [""]


def validate_spec(spec: dict) -> list[str]:
    """Basic validation of the spec before rendering."""
    errors: list[str] = []
    nodes = spec.get("nodes", [])
    edges = spec.get("edges", [])

    if not isinstance(nodes, list) or len(nodes) == 0:
        errors.append("No nodes in spec")
    if not isinstance(edges, list):
        errors.append("edges must be a list")
    if len(nodes) > 36:
        errors.append(f"Too many nodes: {len(nodes)}")
    if len(edges) > 48:
        errors.append(f"Too many edges: {len(edges)}")

    for node in nodes:
        if not node.get("id"):
            errors.append("Node missing id")
        if not node.get("label"):
            errors.append(f"Node {node.get('id', '?')} missing label")
        if len(node.get("label", "")) > 300:
            errors.append(f"Node {node.get('id', '?')} label too long")

    return errors


def compute_layout(nodes: list[dict]) -> dict[str, tuple[float, float]]:
    """Compute node positions using a simple layered layout.
    Claims on the left, evidence on the right."""
    claims = [n for n in nodes if n.get("type") == "claim"]
    evidence = [n for n in nodes if n.get("type") == "evidence"]

    positions: dict[str, tuple[float, float]] = {}

    claim_x = 200.0
    evidence_x = 600.0
    y_spacing = 120.0

    for i, node in enumerate(claims):
        y = 80 + i * y_spacing
        positions[node["id"]] = (claim_x, y)

    for i, node in enumerate(evidence):
        y = 80 + i * y_spacing * 0.8
        positions[node["id"]] = (evidence_x, y)

    return positions


def render_svg(spec: dict) -> str:
    """Render the spec to an SVG string."""
    nodes = spec.get("nodes", [])
    edges = spec.get("edges", [])
    title = sanitize_text(spec.get("title", "Claim-Evidence Graph"))

    positions = compute_layout(nodes)

    max_y = max((y for _, y in positions.values()), default=200) + 100
    svg_height = max(max_y + 60, 400)
    svg_width = 850

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_width} {svg_height}" '
        f'width="{svg_width}" height="{svg_height}">'
    )

    # Styles that work in both light and dark contexts
    parts.append("""<defs>
  <marker id="arrow-supports" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
    <path d="M0,0 L8,3 L0,6" fill="#4CAF50"/>
  </marker>
  <marker id="arrow-contradicts" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
    <path d="M0,0 L8,3 L0,6" fill="#F44336"/>
  </marker>
  <marker id="arrow-partial" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
    <path d="M0,0 L8,3 L0,6" fill="#FF9800"/>
  </marker>
</defs>""")

    # Title
    parts.append(
        f'<text x="{svg_width // 2}" y="30" text-anchor="middle" '
        f'font-family="sans-serif" font-size="16" font-weight="bold" '
        f'fill="currentColor">{title}</text>'
    )

    # Edges
    node_map = {n["id"]: n for n in nodes}
    for edge in edges:
        src_id = edge.get("source", "")
        tgt_id = edge.get("target", "")
        relation = edge.get("relation", "supports")

        if src_id not in positions or tgt_id not in positions:
            continue

        sx, sy = positions[src_id]
        tx, ty = positions[tgt_id]

        color = "#4CAF50"
        marker = "arrow-supports"
        dash = ""
        if relation == "contradicts":
            color = "#F44336"
            marker = "arrow-contradicts"
        elif relation == "partially_supports":
            color = "#FF9800"
            marker = "arrow-partial"
            dash = ' stroke-dasharray="5,3"'

        # Offset to node edge
        dx = tx - sx
        dy = ty - sy
        dist = math.sqrt(dx * dx + dy * dy) or 1
        ox = dx / dist * 60
        oy = dy / dist * 30

        parts.append(
            f'<line x1="{sx + ox:.1f}" y1="{sy + oy:.1f}" '
            f'x2="{tx - ox:.1f}" y2="{ty - oy:.1f}" '
            f'stroke="{color}" stroke-width="2"{dash} '
            f'marker-end="url(#{marker})"/>'
        )

    # Nodes
    for node in nodes:
        nid = node["id"]
        if nid not in positions:
            continue
        x, y = positions[nid]
        ntype = node.get("type", "claim")
        label = sanitize_text(node.get("label", ""))
        lines = wrap_text(label, 22)

        if ntype == "claim":
            # Rounded rectangle (blue)
            rx, ry, rw, rh = x - 90, y - 30, 180, 60
            confidence = node.get("confidence", 0)
            opacity = 0.3 + confidence * 0.7
            parts.append(
                f'<rect x="{rx}" y="{ry}" width="{rw}" height="{rh}" rx="8" ry="8" '
                f'fill="rgba(33,150,243,{opacity:.2f})" stroke="#2196F3" stroke-width="2"/>'
            )
        else:
            # Diamond-ish shape (green)
            rx, ry, rw, rh = x - 80, y - 25, 160, 50
            parts.append(
                f'<rect x="{rx}" y="{ry}" width="{rw}" height="{rh}" rx="4" ry="4" '
                f'fill="rgba(76,175,80,0.2)" stroke="#4CAF50" stroke-width="1.5"/>'
            )

        # Label text
        for i, line in enumerate(lines[:3]):
            ty_offset = y - 8 + i * 14
            parts.append(
                f'<text x="{x}" y="{ty_offset}" text-anchor="middle" '
                f'font-family="sans-serif" font-size="11" fill="currentColor">'
                f'{sanitize_text(line)}</text>'
            )

    # Legend
    legend_y = svg_height - 40
    parts.append(f'<line x1="50" y1="{legend_y}" x2="80" y2="{legend_y}" stroke="#4CAF50" stroke-width="2"/>')
    parts.append(f'<text x="85" y="{legend_y + 4}" font-family="sans-serif" font-size="10" fill="currentColor">Supports</text>')
    parts.append(f'<line x1="180" y1="{legend_y}" x2="210" y2="{legend_y}" stroke="#F44336" stroke-width="2"/>')
    parts.append(f'<text x="215" y="{legend_y + 4}" font-family="sans-serif" font-size="10" fill="currentColor">Contradicts</text>')
    parts.append(f'<line x1="320" y1="{legend_y}" x2="350" y2="{legend_y}" stroke="#FF9800" stroke-width="2" stroke-dasharray="5,3"/>')
    parts.append(f'<text x="355" y="{legend_y + 4}" font-family="sans-serif" font-size="10" fill="currentColor">Partially supports</text>')

    parts.append("</svg>")
    return "\n".join(parts)


def main():
    if len(sys.argv) < 3:
        print("Usage: claim_evidence_renderer.py <input.json> <output.svg>", file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    spec = json.loads(input_path.read_text(encoding="utf-8"))

    errors = validate_spec(spec)
    if errors:
        print(f"Validation errors: {errors}", file=sys.stderr)
        sys.exit(1)

    svg = render_svg(spec)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")

    # Write metadata
    metadata_path = output_path.parent / "artifact-metadata.json"
    metadata = {
        "nodes_rendered": len(spec.get("nodes", [])),
        "edges_rendered": len(spec.get("edges", [])),
        "title": spec.get("title", ""),
        "format": "svg",
    }
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    print(f"Rendered {len(spec.get('nodes', []))} nodes, {len(spec.get('edges', []))} edges")


if __name__ == "__main__":
    main()
