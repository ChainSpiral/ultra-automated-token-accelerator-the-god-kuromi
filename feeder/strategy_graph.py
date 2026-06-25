#!/usr/bin/env python3
"""Build proof-backed vault/entity strategy graph payloads.

This module is intentionally conservative. It converts machine-derived local
artifacts into the strategy graph contract and refuses to emit narrative-only
relationships. Research notes may decide which entity name maps to which local
seed, but graph edges come only from parsed flow artifacts with evidence.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from .strategy_graph_validator import validate_strategy_graph
except ImportError:  # pragma: no cover - direct script execution
    from strategy_graph_validator import validate_strategy_graph


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FLOW_DIR = ROOT / "graphs" / "frontend"
ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

ENTITY_PRESETS: dict[str, dict[str, Any]] = {
    "stream": {
        "label": "Stream Finance / xUSD",
        "address": "0xe2fc85bfb48c4cf147921fbe110cf92ef9f26f94",
        "legacy_flow": "stream",
        "notes": ["entity preset only chooses local onchain artifacts; it does not create graph edges"],
    },
    "fx": {
        "label": "f(x) Protocol / fxUSDC",
        "address": "0x4f460bb11cf958606c69a963b4a17f9daeeea8b6",
        "actor_seed": "0x325228217e02e31529bf4bc6e32db695ea525669",
        "notes": ["actor_seed is a local investigation seed; relationships require parsed events"],
    },
    "yield-basis": {
        "label": "Yield Basis / yb-cbBTC",
        "address": "0xd6a1147666f6e4d7161caf436d9923d44d901112",
        "actor_seed": "0x325228217e02e31529bf4bc6e32db695ea525669",
        "notes": ["actor_seed is a local investigation seed; relationships require parsed events"],
    },
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


def slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9:_@.-]+", "-", value.lower()).strip("-")
    return text or "item"


def short_addr(address: str) -> str:
    return f"{address[:6]}...{address[-4:]}" if ADDRESS_RE.match(address) else address


def seed_file_name(address: str, depth: int | str) -> str:
    lower = address.lower()
    return f"eoa.seed.{lower[:6]}{lower[-4:]}.d{depth}.json"


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None


def ensure_node(nodes: dict[str, dict[str, Any]], node: dict[str, Any]) -> None:
    existing = nodes.get(node["id"])
    if existing:
        meta = {**(existing.get("meta") or {}), **(node.get("meta") or {})}
        existing.update({k: v for k, v in node.items() if v is not None})
        existing["meta"] = meta
        return
    nodes[node["id"]] = {k: v for k, v in node.items() if v is not None}


def add_evidence(evidence: dict[str, dict[str, Any]], item: dict[str, Any]) -> str:
    evidence[item["id"]] = {k: v for k, v in item.items() if v is not None}
    return item["id"]


def node_from_eoa_node(raw: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    address = data.get("address") or data.get("target")
    kind = data.get("kind") or raw.get("type") or "unknown"
    node_id = f"{prefix}{raw.get('id')}"
    return {
        "id": node_id,
        "kind": str(kind).lower(),
        "label": raw.get("label") or short_addr(str(address or raw.get("id") or node_id)),
        "address": address.lower() if isinstance(address, str) and ADDRESS_RE.match(address) else None,
        "chainId": 1,
        "meta": {
            "sourceNodeId": raw.get("id"),
            "category": data.get("category"),
            "protocol": data.get("protocol"),
        },
    }


def node_from_legacy_node(raw: dict[str, Any], prefix: str = "legacy:") -> dict[str, Any]:
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    address = data.get("address") if isinstance(data.get("address"), str) else raw.get("id")
    kind = data.get("kind") or raw.get("type") or "unknown"
    return {
        "id": f"{prefix}{raw.get('id')}",
        "kind": str(kind).lower(),
        "label": raw.get("label") or short_addr(str(address)),
        "address": address.lower() if isinstance(address, str) and ADDRESS_RE.match(address) else None,
        "chainId": 1,
        "meta": {
            "sourceNodeId": raw.get("id"),
            "isSeed": data.get("is_seed"),
            "inCycle": data.get("in_cycle"),
        },
    }


def transfer_evidence_from_detail(detail: dict[str, Any], adapter: str, fallback: str) -> dict[str, Any]:
    transfers = detail.get("transfers") if isinstance(detail.get("transfers"), list) else []
    first = transfers[0] if transfers and isinstance(transfers[0], dict) else {}
    return {
        "id": f"ev:{adapter}:{detail.get('tx_hash') or fallback}:{detail.get('event_id') or len(transfers)}",
        "source": "eoa_timeline",
        "adapter": adapter,
        "confidence": "exact" if detail.get("tx_hash") else "inferred_from_receipt",
        "chainId": 1,
        "blockNumber": detail.get("block_number"),
        "txHash": detail.get("tx_hash"),
        "contractAddress": first.get("token"),
        "eventName": detail.get("action"),
        "tokenAddress": first.get("token"),
        "symbol": first.get("symbol"),
        "amount": first.get("amount") if isinstance(first.get("amount"), (int, float)) else None,
        "meta": {
            "category": detail.get("category"),
            "protocol": detail.get("protocol"),
            "transfers": transfers,
        },
    }


def append_eoa_artifact(payload: dict[str, Any], graph: dict[str, Any], *, prefix: str = "") -> None:
    nodes: dict[str, dict[str, Any]] = graph["node_map"]
    evidence: dict[str, dict[str, Any]] = graph["evidence_map"]
    for raw in payload.get("nodes") or []:
        if isinstance(raw, dict):
            ensure_node(nodes, node_from_eoa_node(raw, prefix))

    for index, raw in enumerate(payload.get("edges") or []):
        if not isinstance(raw, dict):
            continue
        kinds = {str(raw.get("edge_type") or "").lower(), str(raw.get("category") or "").lower()}
        if kinds & NARRATIVE_EDGE_KINDS:
            graph["gaps"].append({
                "id": f"gap:narrative-eoa-edge:{index}",
                "kind": "narrative_edge_blocked",
                "message": f"Blocked narrative edge in eoa artifact: {raw.get('id') or index}",
                "adapter": "strategy_graph_builder",
            })
            continue

        source = f"{prefix}{raw.get('source')}"
        target = f"{prefix}{raw.get('target')}"
        if source not in nodes:
            ensure_node(nodes, {"id": source, "kind": "unknown", "label": str(raw.get("source")), "chainId": 1})
        if target not in nodes:
            ensure_node(nodes, {"id": target, "kind": "unknown", "label": str(raw.get("target")), "chainId": 1})

        evidence_ids: list[str] = []
        for detail in raw.get("details") or []:
            if isinstance(detail, dict):
                evidence_ids.append(add_evidence(evidence, transfer_evidence_from_detail(detail, "eoa_timeline_protocol_flow", str(index))))
        if not evidence_ids and raw.get("tx_hash"):
            evidence_ids.append(add_evidence(evidence, {
                "id": f"ev:eoa-edge:{raw.get('tx_hash')}:{index}",
                "source": "eoa_timeline",
                "adapter": "eoa_timeline_graph_edge",
                "confidence": "exact",
                "chainId": 1,
                "blockNumber": raw.get("block_number"),
                "txHash": raw.get("tx_hash"),
                "tokenAddress": raw.get("token"),
                "symbol": raw.get("symbol"),
                "amount": raw.get("amount") if isinstance(raw.get("amount"), (int, float)) else None,
                "meta": {"edgeType": raw.get("edge_type"), "category": raw.get("category")},
            }))
        if not evidence_ids:
            graph["gaps"].append({
                "id": f"gap:eoa-edge-missing-evidence:{index}",
                "kind": "missing_edge_evidence",
                "message": f"Skipped eoa edge without proof: {raw.get('id') or index}",
                "source": source,
                "target": target,
                "adapter": "strategy_graph_builder",
            })
            continue

        graph["edges"].append({
            "id": f"{prefix}{raw.get('id') or f'eoa-edge-{index}'}",
            "source": source,
            "target": target,
            "kind": raw.get("edge_type") or "flow",
            "category": raw.get("category"),
            "semanticType": raw.get("action") or raw.get("edge_type"),
            "label": raw.get("label"),
            "evidenceIds": evidence_ids,
            "meta": {
                "eventCount": raw.get("event_count"),
                "sampleTx": raw.get("tx_hash"),
            },
        })


def append_legacy_artifact(payload: dict[str, Any], graph: dict[str, Any], *, prefix: str = "legacy:") -> None:
    nodes: dict[str, dict[str, Any]] = graph["node_map"]
    evidence: dict[str, dict[str, Any]] = graph["evidence_map"]
    source_name = ((payload.get("metadata") or {}).get("source") or "legacy_flow").strip()

    for raw in payload.get("nodes") or []:
        if isinstance(raw, dict):
            ensure_node(nodes, node_from_legacy_node(raw, prefix))

    for index, raw in enumerate(payload.get("edges") or []):
        if not isinstance(raw, dict):
            continue
        relation = raw.get("role") or ("morpho" if raw.get("morpho") else "mint_burn" if raw.get("mint_burn") else "token_transfer")
        category = "lending" if raw.get("morpho") else "mint_burn" if raw.get("mint_burn") else "value_flow"
        if str(relation).lower() in NARRATIVE_EDGE_KINDS or str(category).lower() in NARRATIVE_EDGE_KINDS:
            graph["gaps"].append({
                "id": f"gap:narrative-legacy-edge:{index}",
                "kind": "narrative_edge_blocked",
                "message": f"Blocked narrative legacy edge: {raw.get('id') or index}",
                "adapter": "legacy_flow_trace_asset_transfers",
            })
            continue
        source = f"{prefix}{raw.get('source')}"
        target = f"{prefix}{raw.get('target')}"
        if source not in nodes or target not in nodes:
            graph["gaps"].append({
                "id": f"gap:legacy-edge-missing-node:{index}",
                "kind": "missing_node",
                "message": f"Skipped legacy edge with missing endpoint: {raw.get('id') or index}",
                "source": source,
                "target": target,
                "adapter": "legacy_flow_trace_asset_transfers",
            })
            continue
        ev_id = add_evidence(evidence, {
            "id": f"ev:legacy:{slug(str(raw.get('id') or index))}",
            "source": source_name,
            "adapter": "legacy_flow_trace_asset_transfers",
            "confidence": "exact" if raw.get("sample_tx") else "inferred_from_snapshot",
            "chainId": 1,
            "txHash": raw.get("sample_tx"),
            "tokenAddress": raw.get("token"),
            "symbol": raw.get("asset"),
            "amount": raw.get("amount") if isinstance(raw.get("amount"), (int, float)) else None,
            "meta": {
                "count": raw.get("count"),
                "blockRange": raw.get("block_range"),
                "inCycle": raw.get("in_cycle"),
                "morpho": raw.get("morpho"),
                "role": raw.get("role"),
            },
        })
        graph["edges"].append({
            "id": f"{prefix}{raw.get('id') or index}",
            "source": source,
            "target": target,
            "kind": relation,
            "category": category,
            "semanticType": relation,
            "label": raw.get("label"),
            "evidenceIds": [ev_id],
            "meta": {"sampleTx": raw.get("sample_tx"), "count": raw.get("count")},
        })


def new_graph(label: str, seed: str | None = None) -> dict[str, Any]:
    graph = {
        "node_map": {},
        "evidence_map": {},
        "edges": [],
        "gaps": [],
        "notes": [],
        "metadata": {
            "label": label,
            "seed": seed,
            "builder": "feeder/strategy_graph.py",
            "contract": "onchain_proven_strategy_graph",
        },
    }
    if seed:
        ensure_node(graph["node_map"], {
            "id": f"entity:{slug(label)}",
            "kind": "entity",
            "label": label,
            "address": seed.lower() if ADDRESS_RE.match(seed) else None,
            "chainId": 1,
            "meta": {"seed": True},
        })
    return graph


def finalize(graph: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "nodes": list(graph.pop("node_map").values()),
        "edges": graph["edges"],
        "evidence": list(graph.pop("evidence_map").values()),
        "gaps": graph["gaps"],
        "notes": graph["notes"],
        "metadata": graph["metadata"],
    }
    errors = validate_strategy_graph(payload)
    if errors:
        raise ValueError("invalid strategy graph payload:\n" + "\n".join(errors))
    return payload


def build_for_address(address: str, flow_dir: Path, depth: int | str) -> dict[str, Any]:
    if not ADDRESS_RE.match(address):
        raise ValueError(f"invalid address: {address}")
    graph = new_graph(f"Entity {short_addr(address.lower())}", address.lower())
    path = flow_dir / seed_file_name(address, depth)
    payload = read_json(path)
    if not payload:
        graph["gaps"].append({
            "id": "gap:eoa-artifact-missing",
            "kind": "missing_artifact",
            "message": f"Missing local EOA artifact: {path.name}",
            "adapter": "strategy_graph_builder",
        })
    else:
        graph["metadata"]["sources"] = [str(path)]
        append_eoa_artifact(payload, graph)
    return finalize(graph)


def build_for_entity(entity: str, flow_dir: Path, depth: int | str) -> dict[str, Any]:
    preset = ENTITY_PRESETS.get(entity)
    if not preset:
        raise ValueError(f"unknown entity: {entity}")
    graph = new_graph(preset["label"], preset.get("address"))
    graph["metadata"]["entity"] = entity
    graph["metadata"]["preset"] = {k: v for k, v in preset.items() if k != "notes"}
    for index, note in enumerate(preset.get("notes") or []):
        graph["notes"].append({"id": f"note:{entity}:{index}", "message": note})

    sources: list[str] = []
    actor_seed = preset.get("actor_seed")
    if isinstance(actor_seed, str):
        path = flow_dir / seed_file_name(actor_seed, depth)
        data = read_json(path)
        if data:
            append_eoa_artifact(data, graph, prefix="actor:")
            sources.append(str(path))
        else:
            graph["gaps"].append({
                "id": f"gap:{entity}:actor-eoa-artifact-missing",
                "kind": "missing_artifact",
                "message": f"Missing actor EOA artifact: {path.name}",
                "adapter": "strategy_graph_builder",
            })

    legacy_name = preset.get("legacy_flow")
    if isinstance(legacy_name, str):
        path = flow_dir / f"flow.{legacy_name}.json"
        data = read_json(path)
        if data:
            append_legacy_artifact(data, graph)
            sources.append(str(path))
        else:
            graph["gaps"].append({
                "id": f"gap:{entity}:legacy-flow-missing",
                "kind": "missing_artifact",
                "message": f"Missing legacy flow artifact: {path.name}",
                "adapter": "strategy_graph_builder",
            })

    if not graph["edges"]:
        graph["gaps"].append({
            "id": f"gap:{entity}:no-proof-backed-edges",
            "kind": "no_proof_backed_edges",
            "message": "No proof-backed edges were emitted for this entity seed",
            "adapter": "strategy_graph_builder",
        })
    graph["metadata"]["sources"] = sources
    return finalize(graph)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--entity", choices=sorted(ENTITY_PRESETS))
    target.add_argument("--address")
    parser.add_argument("--depth", default="0", help="EOA artifact DFS depth suffix")
    parser.add_argument("--flow-dir", type=Path, default=DEFAULT_FLOW_DIR)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    payload = build_for_entity(args.entity, args.flow_dir, args.depth) if args.entity else build_for_address(args.address, args.flow_dir, args.depth)
    raw = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(raw + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
