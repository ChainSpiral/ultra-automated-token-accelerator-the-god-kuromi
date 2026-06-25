#!/usr/bin/env python3
"""Build a proof-backed strategy graph from an address or registry entity seed.

This is intentionally narrow: the first factual adapter emits ERC-20 Transfer
edges from raw `eth_getLogs` rows. Protocol semantics are left as gaps until
specific adapters can prove supply/borrow/swap/vault actions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from feeder.bridge_adapters import ADAPTER_VERSION as BRIDGE_ADAPTER_VERSION
from feeder.bridge_adapters import event_topic
from feeder.bridge_adapters import parse_bridge_logs
from feeder.strategy_graph_validator import validate_strategy_graph

DEFAULT_ENV = Path("/Users/link/podotree/.env")
REGISTRY_PATH = REPO / "registry" / "vault_entities.json"
CACHE = ROOT / "cache" / "strategy_graph"
CACHE.mkdir(parents=True, exist_ok=True)

ZERO = "0x0000000000000000000000000000000000000000"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
ADAPTER_VERSION = "erc20-transfer-log@v1"
GRAPH_SCHEMA = "strategy_graph.v0"

DIRECT_BRIDGE_EVENT_FILTERS = (
    {"signature": "OFTSent(bytes32,uint32,address,uint256,uint256)", "positions": (2,)},
    {"signature": "OFTReceived(bytes32,uint32,address,uint256)", "positions": (2,)},
    {"signature": "ETHBridgeInitiated(address,address,uint256,bytes)", "positions": (1, 2)},
    {"signature": "ETHBridgeFinalized(address,address,uint256,bytes)", "positions": (1, 2)},
    {"signature": "ERC20BridgeInitiated(address,address,address,address,uint256,bytes)", "positions": (3,)},
    {"signature": "ERC20BridgeFinalized(address,address,address,address,uint256,bytes)", "positions": (3,)},
)

MISSING_PROTOCOL_ADAPTERS = (
    "aave-v3",
    "spark",
    "morpho-blue",
    "erc4626-vault",
    "dex-lp",
    "staking-lst-lrt",
    "cex-router-solver",
)


def norm_addr(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if not value.startswith("0x"):
        value = "0x" + value
    return value.lower()


def is_addr(value: str) -> bool:
    return bool(ADDRESS_RE.match(value or ""))


def address_node_id(chain_id: int, address: str) -> str:
    return f"address:{chain_id}:{norm_addr(address)}"


def short_addr(address: str) -> str:
    address = norm_addr(address)
    return f"{address[:6]}...{address[-4:]}" if len(address) == 42 else address


def int_from_quantity(value: Any) -> int:
    if isinstance(value, int):
        return value
    if not value or value == "0x":
        return 0
    return int(str(value), 16)


def topic_for_address(address: str) -> str:
    return "0x" + norm_addr(address)[2:].rjust(64, "0")


def address_from_topic(topic: str) -> str:
    return "0x" + (topic or "")[-40:].lower()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_id(prefix: str, parts: Iterable[Any]) -> str:
    digest = hashlib.sha256(stable_json(list(parts)).encode()).hexdigest()[:16]
    return f"{prefix}:{digest}"


def load_env(path: Path = DEFAULT_ENV) -> dict[str, str]:
    env = dict(os.environ)
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {"entities": {}, "instances": {}}


def registry_instance(address: str, registry: dict[str, Any]) -> Optional[dict[str, Any]]:
    instances = registry.get("instances") or {}
    entry = instances.get(norm_addr(address))
    return entry if isinstance(entry, dict) else None


def _registry_match_keys(address: str, entry: dict[str, Any], registry: dict[str, Any]) -> set[str]:
    keys = {address.lower()}
    entity_id = str(entry.get("entity") or "").lower()
    if entity_id:
        keys.add(entity_id)
        entity = (registry.get("entities") or {}).get(entity_id) or {}
        for field in ("display_name", "operator_or_project"):
            value = entity.get(field)
            if value:
                keys.add(str(value).lower())
    for field in ("name", "symbol", "contract_label", "classification", "curator"):
        value = entry.get(field)
        if value:
            keys.add(str(value).lower())
    return keys


def resolve_seed(seed: str, registry: dict[str, Any]) -> dict[str, Any]:
    requested = (seed or "").strip()
    normalized = norm_addr(requested)
    if is_addr(normalized):
        entry = registry_instance(normalized, registry)
        return {
            "requested": requested,
            "address": normalized,
            "kind": "address",
            "registryEntry": entry,
            "gaps": [],
        }

    wanted = requested.lower()
    matches: list[tuple[str, dict[str, Any]]] = []
    for address, entry in (registry.get("instances") or {}).items():
        if not isinstance(entry, dict):
            continue
        if wanted in _registry_match_keys(address, entry, registry):
            matches.append((norm_addr(address), entry))

    if len(matches) == 1:
        address, entry = matches[0]
        return {
            "requested": requested,
            "address": address,
            "kind": "registry_entity",
            "registryEntry": entry,
            "gaps": [],
        }
    if len(matches) > 1:
        return {
            "requested": requested,
            "address": "",
            "kind": "unresolved",
            "registryEntry": None,
            "gaps": [
                {
                    "id": stable_id("gap:ambiguous_seed", [requested, [m[0] for m in matches]]),
                    "kind": "ambiguous_seed",
                    "seed": requested,
                    "candidates": [m[0] for m in matches],
                    "reason": "registry seed matched multiple addresses",
                }
            ],
        }
    return {
        "requested": requested,
        "address": "",
        "kind": "unresolved",
        "registryEntry": None,
        "gaps": [
            {
                "id": stable_id("gap:unresolved_seed", [requested]),
                "kind": "unresolved_seed",
                "seed": requested,
                "reason": "seed is not an address and did not match registry/vault_entities.json",
            }
        ],
    }


class RpcClient:
    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url

    def cache_path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return CACHE / f"{digest}.json"

    def call(self, method: str, params: list[Any]) -> Any:
        if not self.rpc_url:
            raise RuntimeError("ETH_RPC/ALCHEMY_RPC/RPC_URL is not configured")
        key = stable_json({"method": method, "params": params})
        cached = self.cache_path(key)
        if cached.exists():
            with cached.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(
            self.rpc_url,
            data=body,
            headers={"content-type": "application/json", "user-agent": "defi-dagggg-strategy-graph"},
        )
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    payload = json.loads(resp.read().decode())
                if "error" in payload:
                    raise RuntimeError(f"{method}: {payload['error']}")
                result = payload.get("result")
                with cached.open("w", encoding="utf-8") as handle:
                    json.dump(result, handle, ensure_ascii=False)
                return result
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < 4:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise
            except urllib.error.URLError:
                if attempt < 4:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise
        raise RuntimeError(f"{method}: rpc request failed")

    def get_logs(self, log_filter: dict[str, Any]) -> list[dict[str, Any]]:
        result = self.call("eth_getLogs", [log_filter])
        if not isinstance(result, list):
            raise RuntimeError("eth_getLogs returned a non-array result")
        return result

    def get_transaction_receipt(self, tx_hash: str) -> dict[str, Any]:
        result = self.call("eth_getTransactionReceipt", [tx_hash])
        if not isinstance(result, dict):
            raise RuntimeError("eth_getTransactionReceipt returned a non-object result")
        return result


def fetch_seed_transfer_logs(
    rpc_client: RpcClient,
    seed_address: str,
    from_block: int,
    to_block: int,
) -> list[dict[str, Any]]:
    seed_topic = topic_for_address(seed_address)
    base = {"fromBlock": hex(from_block), "toBlock": hex(to_block)}
    filters = [
        {**base, "topics": [TRANSFER_TOPIC, seed_topic, None]},
        {**base, "topics": [TRANSFER_TOPIC, None, seed_topic]},
    ]
    logs_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for log_filter in filters:
        for row in rpc_client.get_logs(log_filter):
            tx_hash = str(row.get("transactionHash") or "").lower()
            log_index = int_from_quantity(row.get("logIndex"))
            logs_by_key[(tx_hash, log_index)] = row
    return sorted(
        logs_by_key.values(),
        key=lambda row: (
            int_from_quantity(row.get("blockNumber")),
            int_from_quantity(row.get("transactionIndex")),
            int_from_quantity(row.get("logIndex")),
            str(row.get("transactionHash") or "").lower(),
        ),
    )


def fetch_seed_bridge_logs(
    rpc_client: RpcClient,
    seed_address: str,
    from_block: int,
    to_block: int,
) -> list[dict[str, Any]]:
    seed_topic = topic_for_address(seed_address)
    base = {"fromBlock": hex(from_block), "toBlock": hex(to_block)}
    logs_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for spec in DIRECT_BRIDGE_EVENT_FILTERS:
        topic0 = event_topic(str(spec["signature"]))
        for position in spec["positions"]:
            topics: list[str | None] = [topic0]
            while len(topics) <= int(position):
                topics.append(None)
            topics[int(position)] = seed_topic
            for row in rpc_client.get_logs({**base, "topics": topics}):
                tx_hash = str(row.get("transactionHash") or "").lower()
                log_index = int_from_quantity(row.get("logIndex"))
                logs_by_key[(tx_hash, log_index)] = row
    return sorted(
        logs_by_key.values(),
        key=lambda row: (
            int_from_quantity(row.get("blockNumber")),
            int_from_quantity(row.get("transactionIndex")),
            int_from_quantity(row.get("logIndex")),
            str(row.get("transactionHash") or "").lower(),
        ),
    )


def fetch_transaction_receipts(
    rpc_client: RpcClient,
    tx_hashes: Iterable[str],
    *,
    max_receipts: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    receipts: list[dict[str, Any]] = []
    failed: list[str] = []
    for tx_hash in sorted({str(tx).lower() for tx in tx_hashes if str(tx).startswith("0x")})[:max_receipts]:
        try:
            receipt = rpc_client.get_transaction_receipt(tx_hash)
        except Exception:
            failed.append(tx_hash)
            continue
        receipts.append(receipt)
    return receipts, failed


def receipt_logs(receipts: Any) -> list[dict[str, Any]]:
    if receipts is None:
        return []
    if isinstance(receipts, dict):
        values = receipts.values()
    elif isinstance(receipts, list):
        values = receipts
    else:
        return []

    logs: list[dict[str, Any]] = []
    for receipt in values:
        if not isinstance(receipt, dict):
            continue
        tx_hash = str(receipt.get("transactionHash") or "").lower()
        block_number = receipt.get("blockNumber")
        tx_index = receipt.get("transactionIndex")
        for row in receipt.get("logs") or []:
            if not isinstance(row, dict):
                continue
            merged = dict(row)
            if tx_hash and not merged.get("transactionHash"):
                merged["transactionHash"] = tx_hash
            if block_number is not None and not merged.get("blockNumber"):
                merged["blockNumber"] = block_number
            if tx_index is not None and not merged.get("transactionIndex"):
                merged["transactionIndex"] = tx_index
            logs.append(merged)
    return logs


def decode_transfer_log(row: dict[str, Any]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    topics = row.get("topics") or []
    if row.get("removed"):
        return None, "removed_log"
    if len(topics) < 3:
        return None, "missing_transfer_topics"
    if str(topics[0]).lower() != TRANSFER_TOPIC:
        return None, "not_erc20_transfer"
    token = norm_addr(str(row.get("address") or ""))
    if not is_addr(token):
        return None, "invalid_token_address"
    src = address_from_topic(str(topics[1]))
    dst = address_from_topic(str(topics[2]))
    if not is_addr(src) or not is_addr(dst):
        return None, "invalid_transfer_party"
    try:
        raw_amount = str(int_from_quantity(row.get("data")))
        block_number = int_from_quantity(row.get("blockNumber"))
        tx_index = int_from_quantity(row.get("transactionIndex"))
        log_index = int_from_quantity(row.get("logIndex"))
    except Exception:
        return None, "invalid_numeric_field"
    tx_hash = str(row.get("transactionHash") or "").lower()
    if not tx_hash.startswith("0x"):
        return None, "missing_tx_hash"
    return {
        "token": token,
        "from": src,
        "to": dst,
        "rawAmount": raw_amount,
        "blockNumber": block_number,
        "transactionIndex": tx_index,
        "txHash": tx_hash,
        "logIndex": log_index,
    }, None


def make_address_node(
    chain_id: int,
    address: str,
    *,
    seed: bool = False,
    registry_entry: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    address = norm_addr(address)
    if address == ZERO:
        return {
            "id": address_node_id(chain_id, address),
            "kind": "mint_burn",
            "label": "mint/burn",
            "chainId": chain_id,
            "address": address,
        }
    label = short_addr(address)
    kind = "address"
    if registry_entry:
        label = registry_entry.get("name") or registry_entry.get("symbol") or label
        kind = registry_entry.get("classification") or registry_entry.get("contract_label") or kind
    node = {
        "id": address_node_id(chain_id, address),
        "kind": kind,
        "label": label,
        "chainId": chain_id,
        "address": address,
    }
    if seed:
        node["seed"] = True
    if registry_entry:
        node["registry"] = {
            "source": str(REGISTRY_PATH.relative_to(REPO)),
            "entity": registry_entry.get("entity"),
            "confidence": registry_entry.get("confidence"),
            "classification": registry_entry.get("classification"),
        }
    return node


def bridge_route_node_id(event: dict[str, Any]) -> str:
    bridge = str(event.get("bridge") or "bridge").replace("_", "-")
    token = str(event.get("tokenAddress") or (event.get("token") or {}).get("tokenAddress") or "asset").lower()
    if event.get("direction") == "in":
        src = event.get("sourceChainId") or event.get("srcChainId") or event.get("counterpartyChainId") or "unknown"
        dst = event.get("chainId") or "unknown"
    else:
        src = event.get("chainId") or "unknown"
        dst = event.get("destinationChainId") or event.get("dstChainId") or event.get("counterpartyChainId") or "unknown"
    return f"bridge-route:{bridge}:{src}->{dst}:{token}"


def make_bridge_route_node(event: dict[str, Any]) -> dict[str, Any]:
    bridge = str(event.get("bridge") or "bridge")
    if event.get("direction") == "in":
        src = event.get("sourceChainId") or event.get("srcChainId") or event.get("counterpartyChainId") or "unknown"
        dst = event.get("chainId") or "unknown"
    else:
        src = event.get("chainId") or "unknown"
        dst = event.get("destinationChainId") or event.get("dstChainId") or event.get("counterpartyChainId") or "unknown"
    token = event.get("tokenAddress") or (event.get("token") or {}).get("tokenAddress")
    return {
        "id": bridge_route_node_id(event),
        "kind": "bridge_route",
        "type": "bridge_route",
        "label": f"{bridge.replace('_', ' ').title()} {src} -> {dst}",
        "bridge": bridge,
        "sourceChainId": src,
        "destinationChainId": dst,
        "tokenAddress": token,
        "data": {
            "kind": "bridge_route",
            "bridge": bridge,
            "sourceChainId": src,
            "destinationChainId": dst,
            "tokenAddress": token,
        },
    }


def bridge_edge_from_event(
    event: dict[str, Any],
    *,
    chain_id: int,
    seed_address: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    route_node = make_bridge_route_node(event)
    direction = event.get("direction")
    route_id = route_node["id"]
    if direction == "in":
        recipient = norm_addr(event.get("recipient") or event.get("actor") or seed_address)
        if not is_addr(recipient):
            return None, None
        source = route_id
        target = address_node_id(chain_id, recipient)
        kind = "bridge_receive"
    else:
        actor = norm_addr(event.get("actor") or seed_address)
        if not is_addr(actor):
            return None, None
        source = address_node_id(chain_id, actor)
        target = route_id
        kind = "bridge_send"

    edge = {
        "id": f"edge:{kind}:{event.get('chainId')}:{event.get('txHash')}:{event.get('logIndex')}",
        "source": source,
        "target": target,
        "kind": kind,
        "semanticType": "bridge",
        "category": "bridge",
        "bridge": event.get("bridge"),
        "direction": direction,
        "chainId": event.get("chainId"),
        "blockNumber": event.get("blockNumber"),
        "txHash": event.get("txHash"),
        "logIndex": event.get("logIndex"),
        "contractAddress": event.get("contractAddress"),
        "tokenAddress": event.get("tokenAddress") or (event.get("token") or {}).get("tokenAddress"),
        "rawAmount": event.get("rawAmount") or (event.get("token") or {}).get("rawAmount"),
        "sourceChainId": event.get("sourceChainId") or event.get("srcChainId"),
        "destinationChainId": event.get("destinationChainId") or event.get("dstChainId"),
        "counterpartyChainId": event.get("counterpartyChainId"),
        "guid": event.get("guid"),
        "srcEid": event.get("srcEid"),
        "dstEid": event.get("dstEid"),
        "positionType": "historical_bridge_flow",
        "evidenceIds": list(event.get("evidenceIds") or []),
    }
    return route_node, edge


def adapter_gap(seed_address: str, chain_id: int, from_block: int, to_block: int) -> dict[str, Any]:
    return {
        "id": stable_id("gap:needs_adapter", [seed_address, chain_id, from_block, to_block, MISSING_PROTOCOL_ADAPTERS]),
        "kind": "needs_adapter",
        "seedAddress": seed_address,
        "chainId": chain_id,
        "fromBlock": from_block,
        "toBlock": to_block,
        "adapters": list(MISSING_PROTOCOL_ADAPTERS),
        "reason": "core builder only emits ERC20 token_transfer edges; protocol semantic adapters are not implemented here",
    }


def source_query(seed_address: str, from_block: int, to_block: int) -> dict[str, Any]:
    return {
        "method": "eth_getLogs",
        "fromBlock": from_block,
        "toBlock": to_block,
        "topics": [
            "Transfer(address,address,uint256)",
            "seed indexed as from OR seed indexed as to",
        ],
        "seedAddress": seed_address,
    }


def build_strategy_graph(
    seed: str,
    from_block: int,
    to_block: int,
    *,
    chain_id: int = 1,
    raw_logs: Optional[list[dict[str, Any]]] = None,
    raw_bridge_logs: Optional[list[dict[str, Any]]] = None,
    raw_receipts: Optional[Any] = None,
    rpc_url: str = "",
    include_adapter_gaps: bool = True,
    include_bridge_receipts: bool = True,
    registry_path: Path = REGISTRY_PATH,
    max_logs: int = 5000,
    max_receipts: int = 200,
) -> dict[str, Any]:
    if from_block > to_block:
        raise ValueError("from_block must be <= to_block")

    registry = load_registry(registry_path)
    seed_resolution = resolve_seed(seed, registry)
    seed_address = seed_resolution.get("address") or ""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = list(seed_resolution.get("gaps") or [])

    logs: list[dict[str, Any]] = []
    rpc_client = RpcClient(rpc_url) if rpc_url else None
    collection_attempted = raw_logs is not None
    collection_failed = False
    if seed_address:
        nodes[address_node_id(chain_id, seed_address)] = make_address_node(
            chain_id,
            seed_address,
            seed=True,
            registry_entry=seed_resolution.get("registryEntry"),
        )
        if raw_logs is not None:
            logs = list(raw_logs)
        elif rpc_url:
            collection_attempted = True
            try:
                assert rpc_client is not None
                logs = fetch_seed_transfer_logs(rpc_client, seed_address, from_block, to_block)
            except Exception as exc:
                collection_failed = True
                gaps.append(
                    {
                        "id": stable_id("gap:log_collection_failed", [seed_address, from_block, to_block, type(exc).__name__]),
                        "kind": "log_collection_failed",
                        "seedAddress": seed_address,
                        "chainId": chain_id,
                        "fromBlock": from_block,
                        "toBlock": to_block,
                        "source": "eth_getLogs",
                        "reason": type(exc).__name__,
                    }
                )
        else:
            gaps.append(
                {
                    "id": stable_id("gap:missing_rpc", [seed_address, from_block, to_block]),
                    "kind": "missing_rpc",
                    "seedAddress": seed_address,
                    "chainId": chain_id,
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "reason": "no raw logs supplied and ETH_RPC/ALCHEMY_RPC/RPC_URL is not configured",
                }
            )

    if len(logs) > max_logs:
        gaps.append(
            {
                "id": stable_id("gap:max_logs", [seed_address, from_block, to_block, len(logs), max_logs]),
                "kind": "result_limited",
                "seedAddress": seed_address,
                "chainId": chain_id,
                "fromBlock": from_block,
                "toBlock": to_block,
                "observedLogs": len(logs),
                "maxLogs": max_logs,
                "reason": "transfer log result exceeded max_logs; tail rows were not emitted",
            }
        )
        logs = logs[:max_logs]

    seen_logs: set[tuple[str, int]] = set()
    decoded_count = 0
    candidate_tx_hashes: set[str] = set()
    for row in logs:
        event, decode_error = decode_transfer_log(row)
        if decode_error:
            gaps.append(
                {
                    "id": stable_id("gap:decode_transfer_log", [seed_address, row.get("transactionHash"), row.get("logIndex"), decode_error]),
                    "kind": "decode_transfer_log_failed",
                    "seedAddress": seed_address,
                    "chainId": chain_id,
                    "reason": decode_error,
                    "source": "eth_getLogs",
                }
            )
            continue
        assert event is not None
        if seed_address and seed_address not in {event["from"], event["to"]}:
            continue
        key = (event["txHash"], event["logIndex"])
        if key in seen_logs:
            continue
        seen_logs.add(key)
        decoded_count += 1
        candidate_tx_hashes.add(event["txHash"])

        from_id = address_node_id(chain_id, event["from"])
        to_id = address_node_id(chain_id, event["to"])
        nodes.setdefault(from_id, make_address_node(chain_id, event["from"], seed=event["from"] == seed_address))
        nodes.setdefault(to_id, make_address_node(chain_id, event["to"], seed=event["to"] == seed_address))

        evidence_id = f"ev:erc20-transfer:{chain_id}:{event['txHash']}:{event['logIndex']}"
        evidence.append(
            {
                "id": evidence_id,
                "source": "eth_getLogs",
                "adapter": ADAPTER_VERSION,
                "confidence": "exact",
                "chainId": chain_id,
                "blockNumber": event["blockNumber"],
                "txHash": event["txHash"],
                "logIndex": event["logIndex"],
                "contractAddress": event["token"],
                "eventName": "Transfer",
                "eventSignature": "Transfer(address,address,uint256)",
                "tokenAddress": event["token"],
                "rawAmount": event["rawAmount"],
                "sourceQuery": source_query(seed_address, from_block, to_block),
            }
        )
        edges.append(
            {
                "id": f"edge:token-transfer:{chain_id}:{event['txHash']}:{event['logIndex']}",
                "source": from_id,
                "target": to_id,
                "kind": "token_transfer",
                "semanticType": "token_transfer",
                "chainId": chain_id,
                "blockNumber": event["blockNumber"],
                "txHash": event["txHash"],
                "logIndex": event["logIndex"],
                "tokenAddress": event["token"],
                "rawAmount": event["rawAmount"],
                "positionType": "historical_flow",
                "evidenceIds": [evidence_id],
            }
        )

    direct_bridge_logs: list[dict[str, Any]] = []
    direct_bridge_tx_hashes: set[str] = set()
    if seed_address and include_bridge_receipts:
        if raw_bridge_logs is not None:
            direct_bridge_logs = list(raw_bridge_logs)
        elif rpc_client:
            try:
                direct_bridge_logs = fetch_seed_bridge_logs(rpc_client, seed_address, from_block, to_block)
            except Exception as exc:
                gaps.append(
                    {
                        "id": stable_id("gap:bridge_log_collection_failed", [seed_address, from_block, to_block, type(exc).__name__]),
                        "kind": "bridge_log_collection_failed",
                        "seedAddress": seed_address,
                        "chainId": chain_id,
                        "fromBlock": from_block,
                        "toBlock": to_block,
                        "source": "eth_getLogs",
                        "reason": type(exc).__name__,
                    }
                )
        direct_bridge_tx_hashes = {
            str(row.get("transactionHash") or "").lower()
            for row in direct_bridge_logs
            if str(row.get("transactionHash") or "").startswith("0x")
        }

    if seed_address and collection_attempted and not collection_failed and decoded_count == 0 and not direct_bridge_logs:
        gaps.append(
            {
                "id": stable_id("gap:no_transfer_logs", [seed_address, from_block, to_block]),
                "kind": "no_erc20_transfer_logs",
                "seedAddress": seed_address,
                "chainId": chain_id,
                "fromBlock": from_block,
                "toBlock": to_block,
                "reason": "no decodable ERC20 Transfer logs touching the seed were found in the supplied or fetched rows",
            }
        )

    bridge_routes: list[dict[str, Any]] = []
    if seed_address and include_bridge_receipts:
        receipts: list[dict[str, Any]] = []
        receipt_source = "eth_getTransactionReceipt"
        if raw_receipts is not None:
            receipts = list(raw_receipts.values()) if isinstance(raw_receipts, dict) else list(raw_receipts)
            receipt_source = "raw_receipt_fixture"
        elif rpc_client and candidate_tx_hashes:
            if len(candidate_tx_hashes) > max_receipts:
                gaps.append(
                    {
                        "id": stable_id("gap:max_receipts", [seed_address, from_block, to_block, len(candidate_tx_hashes), max_receipts]),
                        "kind": "result_limited",
                        "seedAddress": seed_address,
                        "chainId": chain_id,
                        "fromBlock": from_block,
                        "toBlock": to_block,
                        "observedTransactions": len(candidate_tx_hashes),
                        "maxReceipts": max_receipts,
                        "reason": "candidate transaction count exceeded max_receipts; tail receipts were not fetched",
                    }
                )
            receipts, failed_receipts = fetch_transaction_receipts(
                rpc_client,
                candidate_tx_hashes,
                max_receipts=max_receipts,
            )
            for tx_hash in failed_receipts:
                gaps.append(
                    {
                        "id": stable_id("gap:receipt_fetch_failed", [seed_address, tx_hash]),
                        "kind": "receipt_fetch_failed",
                        "seedAddress": seed_address,
                        "chainId": chain_id,
                        "txHash": tx_hash,
                        "source": "eth_getTransactionReceipt",
                        "reason": "rpc_request_failed",
                    }
                )

        bridge_outputs: list[dict[str, list[dict[str, Any]]]] = []
        if direct_bridge_logs:
            bridge_outputs.append(parse_bridge_logs(
                direct_bridge_logs,
                chain_id=chain_id,
                source="eth_getLogs",
                emit_unknown_gaps=False,
            ))
        if receipts:
            bridge_outputs.append(parse_bridge_logs(
                receipt_logs(receipts),
                chain_id=chain_id,
                source=receipt_source,
                emit_unknown_gaps=False,
            ))

        for bridge_output in bridge_outputs:
            gaps.extend(bridge_output.get("gaps") or [])
            bridge_routes.extend(bridge_output.get("routes") or [])
            existing_evidence_ids = {item.get("id") for item in evidence}
            for item in bridge_output.get("evidence") or []:
                if item.get("id") not in existing_evidence_ids:
                    evidence.append(item)
                    existing_evidence_ids.add(item.get("id"))
            for event in bridge_output.get("events") or []:
                tx_hash = str(event.get("txHash") or "").lower()
                if candidate_tx_hashes and tx_hash not in candidate_tx_hashes and tx_hash not in direct_bridge_tx_hashes:
                    continue
                for address in (event.get("actor"), event.get("recipient")):
                    normalized = norm_addr(address or "")
                    if is_addr(normalized):
                        nodes.setdefault(address_node_id(chain_id, normalized), make_address_node(chain_id, normalized, seed=normalized == seed_address))
                route_node, edge = bridge_edge_from_event(event, chain_id=chain_id, seed_address=seed_address)
                if not route_node or not edge:
                    gaps.append(
                        {
                            "id": stable_id("gap:bridge_edge_missing_endpoint", [seed_address, event.get("txHash"), event.get("logIndex")]),
                            "kind": "bridge_edge_missing_endpoint",
                            "seedAddress": seed_address,
                            "chainId": chain_id,
                            "txHash": event.get("txHash"),
                            "logIndex": event.get("logIndex"),
                            "reason": "bridge event did not expose a usable actor or recipient endpoint",
                        }
                    )
                    continue
                nodes.setdefault(route_node["id"], route_node)
                if edge.get("evidenceIds"):
                    edges.append(edge)

    if seed_address and include_adapter_gaps:
        gaps.append(adapter_gap(seed_address, chain_id, from_block, to_block))

    deduped_edges: dict[str, dict[str, Any]] = {}
    for edge in edges:
        deduped_edges.setdefault(str(edge.get("id")), edge)

    sorted_nodes = sorted(nodes.values(), key=lambda node: (not node.get("seed", False), node["kind"], node["id"]))
    sorted_edges = sorted(deduped_edges.values(), key=lambda edge: (edge["blockNumber"], edge["logIndex"], edge["id"]))
    sorted_evidence = sorted(evidence, key=lambda item: (item["blockNumber"], item["logIndex"], item["id"]))
    run_id = stable_id("run", [GRAPH_SCHEMA, seed, seed_address, chain_id, from_block, to_block, sorted_edges, gaps])

    return {
        "nodes": sorted_nodes,
        "edges": sorted_edges,
        "evidence": sorted_evidence,
        "gaps": gaps,
        "notes": [
            {
                "kind": "scope",
                "message": "This payload contains ERC20 Transfer log edges plus decoded bridge receipt edges; unsupported strategy semantics are represented as gaps.",
            }
        ],
        "metadata": {
            "schema": GRAPH_SCHEMA,
            "producer": "feeder/strategy_graph_builder.py",
            "runId": run_id,
            "chainId": chain_id,
            "seed": {
                "requested": seed_resolution.get("requested"),
                "resolvedAddress": seed_address or None,
                "kind": seed_resolution.get("kind"),
            },
            "fromBlock": from_block,
            "toBlock": to_block,
            "adapters": [ADAPTER_VERSION, BRIDGE_ADAPTER_VERSION],
            "bridgeRoutes": bridge_routes,
            "validator": "feeder.strategy_graph_validator.validate_strategy_graph",
            "counts": {
                "nodes": len(sorted_nodes),
                "edges": len(sorted_edges),
                "evidence": len(sorted_evidence),
                "gaps": len(gaps),
                "bridgeRoutes": len(bridge_routes),
            },
        },
    }


def load_raw_logs(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("logs"), list):
        return payload["logs"]
    raise ValueError("--raw-log-file must contain a JSON array or an object with a logs array")


def load_raw_receipts(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("receipts"), list):
        return payload["receipts"]
    if isinstance(payload, dict):
        return payload
    raise ValueError("--raw-receipt-file must contain a receipt array, a receipts array, or a txHash->receipt object")


def parse_block(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid block number: {value}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True, help="address or exact registry entity/name/symbol seed")
    parser.add_argument("--from-block", type=parse_block, required=True)
    parser.add_argument("--to-block", type=parse_block, required=True)
    parser.add_argument("--chain-id", type=int, default=1)
    parser.add_argument("--rpc-url", default="", help="override ETH_RPC/ALCHEMY_RPC/RPC_URL without printing it")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV, help="env file to load for RPC keys")
    parser.add_argument("--raw-log-file", type=Path, help="offline eth_getLogs fixture for deterministic tests")
    parser.add_argument("--raw-bridge-log-file", type=Path, help="offline direct bridge eth_getLogs fixture for deterministic native bridge tests")
    parser.add_argument("--raw-receipt-file", type=Path, help="offline eth_getTransactionReceipt fixture for deterministic bridge decoding tests")
    parser.add_argument("--max-logs", type=int, default=5000)
    parser.add_argument("--max-receipts", type=int, default=200)
    parser.add_argument("--no-bridge-receipts", action="store_true")
    parser.add_argument("--no-adapter-gaps", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    env = load_env(args.env)
    rpc_url = args.rpc_url or env.get("ETH_RPC") or env.get("ALCHEMY_RPC") or env.get("RPC_URL") or ""
    raw_logs = load_raw_logs(args.raw_log_file) if args.raw_log_file else None
    raw_bridge_logs = load_raw_logs(args.raw_bridge_log_file) if args.raw_bridge_log_file else None
    raw_receipts = load_raw_receipts(args.raw_receipt_file) if args.raw_receipt_file else None
    payload = build_strategy_graph(
        args.seed,
        args.from_block,
        args.to_block,
        chain_id=args.chain_id,
        raw_logs=raw_logs,
        raw_bridge_logs=raw_bridge_logs,
        raw_receipts=raw_receipts,
        rpc_url=rpc_url,
        include_adapter_gaps=not args.no_adapter_gaps,
        include_bridge_receipts=not args.no_bridge_receipts,
        max_logs=args.max_logs,
        max_receipts=args.max_receipts,
    )
    errors = validate_strategy_graph(payload)
    if errors:
        print("strategy graph validation failed", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    counts = payload["metadata"]["counts"]
    print(
        f"saved {args.out} "
        f"nodes={counts['nodes']} edges={counts['edges']} "
        f"evidence={counts['evidence']} gaps={counts['gaps']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
