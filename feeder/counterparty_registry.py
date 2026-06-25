#!/usr/bin/env python3
"""Local registry-backed classification for strategy-graph counterparties.

This module is deliberately offline and deterministic. It turns versioned local
registries into decisions the graph producer can use:

- known infra/protocol/CEX endpoints are retained as nodes
- those endpoints are excluded from wallet-cluster DFS
- token transfers only become graph-building signals when the token reputation
  registry explicitly allows them
"""

from __future__ import annotations

import copy
import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, Iterable, Optional


ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)
COUNTERPARTY_REGISTRY_PATH = os.path.join(REPO, "registry", "counterparties.json")
TOKEN_REPUTATION_REGISTRY_PATH = os.path.join(REPO, "registry", "token_reputation.json")

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
NATIVE_ETH = "native:eth"

UNKNOWN_COUNTERPARTY_CATEGORY = "unknown"
EXPANDABLE_WALLET_KINDS = {"eoa", "safe", "contract_wallet"}
EXCLUDED_COUNTERPARTY_CATEGORIES = {
    "cex",
    "bridge",
    "router",
    "solver",
    "protocol_contract",
}


def norm_addr(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value == NATIVE_ETH:
        return value
    if not value.startswith("0x"):
        value = "0x" + value
    return value.lower()


def is_addr(value: str) -> bool:
    return bool(ADDRESS_RE.match(value or ""))


def norm_token(value: str) -> str:
    value = (value or "").strip().lower()
    if value == NATIVE_ETH:
        return value
    return norm_addr(value)


def _load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=4)
def load_counterparty_registry(path: str = COUNTERPARTY_REGISTRY_PATH) -> dict[str, Any]:
    data = _load_json(path)
    for chain in (data.get("chains") or {}).values():
        addresses = chain.get("addresses") or {}
        chain["addresses"] = {norm_addr(addr): entry for addr, entry in addresses.items()}
    return data


@lru_cache(maxsize=4)
def load_token_reputation_registry(path: str = TOKEN_REPUTATION_REGISTRY_PATH) -> dict[str, Any]:
    data = _load_json(path)
    for chain in (data.get("chains") or {}).values():
        allowlisted = chain.get("allowlisted_tokens") or {}
        blocked = chain.get("blocked_tokens") or {}
        chain["allowlisted_tokens"] = {norm_token(token): entry for token, entry in allowlisted.items()}
        chain["blocked_tokens"] = {norm_token(token): entry for token, entry in blocked.items()}
    return data


def _chain(data: dict[str, Any], chain_id: int) -> dict[str, Any]:
    return (data.get("chains") or {}).get(str(chain_id), {})


def _public_evidence(evidence: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(evidence, list):
        return out
    for item in evidence:
        if not isinstance(item, dict):
            continue
        out.append(copy.deepcopy(item))
    return out


def _registry_evidence(path: str, reason: str) -> list[dict[str, Any]]:
    return [
        {
            "source": "local:" + os.path.relpath(path, REPO),
            "source_type": "local_registry",
            "description": reason,
            "confidence": "registry_backed",
        }
    ]


def _counterparty_output(address: str, chain_id: int, entry: Optional[dict[str, Any]]) -> dict[str, Any]:
    address = norm_addr(address)
    if not entry:
        return {
            "address": address,
            "chain_id": chain_id,
            "is_known": False,
            "label": address,
            "category": UNKNOWN_COUNTERPARTY_CATEGORY,
            "subtype": "",
            "endpoint_role": "",
            "exclude_from_wallet_cluster": False,
            "retain_as_endpoint": False,
            "semantic_tags": [],
            "evidence": [],
        }

    category = str(entry.get("category") or UNKNOWN_COUNTERPARTY_CATEGORY)
    exclude = bool(entry.get("exclude_from_wallet_cluster"))
    if category in EXCLUDED_COUNTERPARTY_CATEGORIES:
        exclude = True
    return {
        "address": address,
        "chain_id": chain_id,
        "is_known": True,
        "label": str(entry.get("label") or address),
        "category": category,
        "subtype": str(entry.get("subtype") or ""),
        "endpoint_role": str(entry.get("endpoint_role") or category),
        "exclude_from_wallet_cluster": exclude,
        "retain_as_endpoint": bool(entry.get("retain_as_endpoint", exclude)),
        "semantic_tags": list(entry.get("semantic_tags") or []),
        "evidence": _public_evidence(entry.get("evidence")),
    }


def classify_counterparty(
    address: str,
    *,
    chain_id: int = 1,
    registry: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Classify a counterparty address from the local registry only."""
    address = norm_addr(address)
    if not is_addr(address):
        return _counterparty_output(address, chain_id, None)
    data = registry or load_counterparty_registry()
    entry = ((_chain(data, chain_id).get("addresses") or {}).get(address))
    return _counterparty_output(address, chain_id, entry)


def counterparty_labels(*, chain_id: int = 1, registry: Optional[dict[str, Any]] = None) -> dict[str, str]:
    data = registry or load_counterparty_registry()
    addresses = _chain(data, chain_id).get("addresses") or {}
    return {addr: str(entry.get("label") or addr) for addr, entry in addresses.items()}


def is_wallet_cluster_excluded(
    address: str,
    *,
    chain_id: int = 1,
    registry: Optional[dict[str, Any]] = None,
) -> bool:
    return bool(classify_counterparty(address, chain_id=chain_id, registry=registry).get("exclude_from_wallet_cluster"))


def should_expand_wallet_cluster(
    address: str,
    wallet_kind: str,
    *,
    chain_id: int = 1,
    registry: Optional[dict[str, Any]] = None,
) -> bool:
    """Return whether DFS may expand through this node as a wallet."""
    kind = (wallet_kind or "").strip().lower()
    if kind not in EXPANDABLE_WALLET_KINDS:
        return False
    return not is_wallet_cluster_excluded(address, chain_id=chain_id, registry=registry)


def counterparty_graph_node(
    address: str,
    *,
    chain_id: int = 1,
    node_id: Optional[str] = None,
    registry: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Return a graph-ready endpoint node for known counterparties."""
    cp = classify_counterparty(address, chain_id=chain_id, registry=registry)
    if not cp.get("is_known") or not cp.get("retain_as_endpoint"):
        return None
    return {
        "id": node_id or f"counterparty:{chain_id}:{cp['address']}",
        "type": "counterparty",
        "label": cp["label"],
        "data": {
            "kind": cp["category"],
            "address": cp["address"],
            "chain_id": chain_id,
            "category": cp["category"],
            "subtype": cp["subtype"],
            "endpoint_role": cp["endpoint_role"],
            "exclude_from_wallet_cluster": cp["exclude_from_wallet_cluster"],
            "semantic_tags": cp["semantic_tags"],
            "evidence": cp["evidence"],
        },
    }


def counterparty_edge_metadata(
    address: str,
    *,
    chain_id: int = 1,
    registry: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cp = classify_counterparty(address, chain_id=chain_id, registry=registry)
    if not cp.get("is_known"):
        return {}
    return {
        "counterparty": {
            "address": cp["address"],
            "chain_id": chain_id,
            "label": cp["label"],
            "category": cp["category"],
            "subtype": cp["subtype"],
            "endpoint_role": cp["endpoint_role"],
            "exclude_from_wallet_cluster": cp["exclude_from_wallet_cluster"],
            "evidence": cp["evidence"],
        }
    }


def token_allowlist_symbols(
    *,
    chain_id: int = 1,
    registry: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    data = registry or load_token_reputation_registry()
    entries = _chain(data, chain_id).get("allowlisted_tokens") or {}
    return {token: str(entry.get("symbol") or token) for token, entry in entries.items()}


def _normalized_label(value: str) -> str:
    return re.sub(r"[\s_\-]+", " ", (value or "").strip().lower()).strip()


def _contains_block_term(value: str, terms: Iterable[str]) -> str:
    normalized = _normalized_label(value)
    for term in terms:
        if term and term in normalized:
            return term
    return ""


def classify_token_for_graph(
    token: str,
    *,
    symbol: str = "",
    name: str = "",
    chain_id: int = 1,
    registry: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return deterministic token reputation for DFS/graph-building use."""
    token = norm_token(token)
    data = registry or load_token_reputation_registry()
    chain = _chain(data, chain_id)
    allowlisted = chain.get("allowlisted_tokens") or {}
    blocked = chain.get("blocked_tokens") or {}

    if token in allowlisted:
        entry = allowlisted[token]
        return {
            "token": token,
            "chain_id": chain_id,
            "symbol": str(entry.get("symbol") or symbol or token),
            "allowed_for_wallet_cluster": bool(entry.get("allowed_for_wallet_cluster", True)),
            "status": "allowlisted",
            "reason": "local_allowlist",
            "evidence": _public_evidence(entry.get("evidence")),
        }

    if token in blocked:
        entry = blocked[token]
        return {
            "token": token,
            "chain_id": chain_id,
            "symbol": str(entry.get("symbol") or symbol or token),
            "allowed_for_wallet_cluster": False,
            "status": "blocked",
            "reason": str(entry.get("reason") or "local_blocklist"),
            "evidence": _public_evidence(entry.get("evidence")),
        }

    if token != NATIVE_ETH and not is_addr(token):
        return {
            "token": token,
            "chain_id": chain_id,
            "symbol": symbol,
            "allowed_for_wallet_cluster": False,
            "status": "invalid",
            "reason": "invalid_token",
            "evidence": _registry_evidence(TOKEN_REPUTATION_REGISTRY_PATH, "Invalid token identifier rejected by deterministic token filter."),
        }

    low_signal = set(chain.get("low_signal_symbols") or data.get("low_signal_symbols") or [])
    block_terms = list(chain.get("block_terms") or data.get("block_terms") or [])
    normalized_symbol = _normalized_label(symbol)
    normalized_name = _normalized_label(name)
    block_hit = _contains_block_term(symbol, block_terms) or _contains_block_term(name, block_terms)
    if block_hit:
        reason = f"blocked_label_term:{block_hit}"
    elif normalized_symbol in low_signal or normalized_name in low_signal:
        reason = "low_signal_label"
    else:
        reason = "unknown_token_not_in_local_registry"

    return {
        "token": token,
        "chain_id": chain_id,
        "symbol": symbol,
        "allowed_for_wallet_cluster": False,
        "status": "denied",
        "reason": reason,
        "evidence": _registry_evidence(
            TOKEN_REPUTATION_REGISTRY_PATH,
            "Token denied by deterministic local token registry policy.",
        ),
    }


def token_allowed_for_wallet_cluster(
    token: str,
    *,
    symbol: str = "",
    name: str = "",
    chain_id: int = 1,
    registry: Optional[dict[str, Any]] = None,
) -> bool:
    return bool(
        classify_token_for_graph(
            token,
            symbol=symbol,
            name=name,
            chain_id=chain_id,
            registry=registry,
        ).get("allowed_for_wallet_cluster")
    )

