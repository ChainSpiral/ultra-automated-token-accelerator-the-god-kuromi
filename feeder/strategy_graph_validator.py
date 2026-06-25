#!/usr/bin/env python3
"""Validate proof-backed vault/entity strategy graph payloads.

This validator intentionally rejects research-summary graphs. Edges must be
backed by evidence records; unproven relationships belong in gaps or notes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


VALID_CONFIDENCE = {
    "exact",
    "inferred_from_receipt",
    "inferred_from_trace",
    "inferred_from_snapshot",
    "registry_backed",
    "low_confidence_gap",
}

NARRATIVE_EDGE_KINDS = {
    "incident_context",
    "issues",
    "research",
    "research_summary",
    "research_says",
    "known_exposure",
    "company_relationship",
    "story",
}


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _edge_kinds(edge: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("kind", "category", "semanticType", "semantic_type", "edge_type"):
        value = edge.get(key)
        if _is_non_empty_string(value):
            values.append(value.strip().lower())
    return values


def validate_strategy_graph(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["payload must be an object"]

    nodes = payload.get("nodes")
    edges = payload.get("edges")
    evidence = payload.get("evidence")

    if not isinstance(nodes, list):
        errors.append("nodes must be an array")
    if not isinstance(edges, list):
        errors.append("edges must be an array")
    if not isinstance(evidence, list):
        errors.append("evidence must be an array")
    if errors:
        return errors

    node_ids: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"nodes[{index}] must be an object")
            continue
        node_id = node.get("id")
        if not _is_non_empty_string(node_id):
            errors.append(f"nodes[{index}].id is required")
            continue
        if node_id in node_ids:
            errors.append(f"duplicate node id: {node_id}")
        node_ids.add(node_id)

    evidence_ids: set[str] = set()
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            errors.append(f"evidence[{index}] must be an object")
            continue

        evidence_id = item.get("id")
        if not _is_non_empty_string(evidence_id):
            errors.append(f"evidence[{index}].id is required")
        elif evidence_id in evidence_ids:
            errors.append(f"duplicate evidence id: {evidence_id}")
        else:
            evidence_ids.add(evidence_id)

        source = item.get("source")
        adapter = item.get("adapter")
        confidence = item.get("confidence")
        if not _is_non_empty_string(source):
            errors.append(f"evidence[{index}].source is required")
        if not _is_non_empty_string(adapter):
            errors.append(f"evidence[{index}].adapter is required")
        if not _is_non_empty_string(confidence):
            errors.append(f"evidence[{index}].confidence is required")
        elif confidence not in VALID_CONFIDENCE:
            errors.append(f"evidence[{index}].confidence is invalid: {confidence}")

    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(f"edges[{index}] must be an object")
            continue

        edge_id = edge.get("id") if _is_non_empty_string(edge.get("id")) else f"#{index}"
        source = edge.get("source")
        target = edge.get("target")
        if not _is_non_empty_string(source):
            errors.append(f"edges[{index}].source is required")
        elif source not in node_ids:
            errors.append(f"edge {edge_id} source node is missing: {source}")
        if not _is_non_empty_string(target):
            errors.append(f"edges[{index}].target is required")
        elif target not in node_ids:
            errors.append(f"edge {edge_id} target node is missing: {target}")

        for kind in _edge_kinds(edge):
            if kind in NARRATIVE_EDGE_KINDS:
                errors.append(f"edge {edge_id} uses narrative-only kind/category: {kind}")

        refs = edge.get("evidenceIds")
        if refs is None:
            refs = edge.get("evidence_ids")
        if not isinstance(refs, list) or not refs:
            errors.append(f"edge {edge_id} must reference at least one evidence id")
            continue
        for ref in refs:
            if not _is_non_empty_string(ref):
                errors.append(f"edge {edge_id} has an invalid evidence id reference")
            elif ref not in evidence_ids:
                errors.append(f"edge {edge_id} references missing evidence id: {ref}")

    return errors


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="strategy graph JSON files")
    args = parser.parse_args()

    ok = True
    for path in args.paths:
        errors = validate_strategy_graph(load_json(path))
        if errors:
            ok = False
            print(f"{path}: invalid")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"{path}: ok")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
