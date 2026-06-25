#!/usr/bin/env python3
"""Build an EOA-flow artifact from proof-backed bridge adapter events."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from feeder.bridge_adapters import event_topic, parse_bridge_logs
from feeder.strategy_graph_builder import DEFAULT_ENV, ZERO, load_env


DEFAULT_OUT_DIR = REPO / "graphs" / "frontend"
OPTIMISM_L1_STANDARD_BRIDGE = "0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1"
ETH_BRIDGE_INITIATED = "ETHBridgeInitiated(address,address,uint256,bytes)"


def norm_addr(value: str) -> str:
    value = (value or "").strip().lower()
    if value and not value.startswith("0x"):
        value = "0x" + value
    return value


def short_addr(address: str) -> str:
    address = norm_addr(address)
    return f"{address[:6]}...{address[-4:]}" if len(address) == 42 else address


def seed_file_name(address: str, depth: int | str = 0) -> str:
    lower = norm_addr(address)
    return f"eoa.seed.{lower[:6]}{lower[-4:]}.d{depth}.json"


def topic_addr(address: str) -> str:
    return "0x" + norm_addr(address)[2:].rjust(64, "0")


def etherscan_logs(params: dict[str, str], api_key: str) -> list[dict[str, Any]]:
    query = {"chainid": "1", "module": "logs", "action": "getLogs", **params, "apikey": api_key}
    url = "https://api.etherscan.io/v2/api?" + urllib.parse.urlencode(query)
    with urllib.request.urlopen(url, timeout=60) as resp:
        payload = json.loads(resp.read().decode())
    result = payload.get("result")
    if payload.get("status") != "1" or not isinstance(result, list):
        raise RuntimeError(f"etherscan logs failed: {payload.get('message')} {str(result)[:200]}")
    return result


def fetch_optimism_eth_bridge_logs(seed: str, from_block: int, to_block: str, api_key: str, max_events: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    topic0 = event_topic(ETH_BRIDGE_INITIATED)
    for page in range(1, 20):
        batch = etherscan_logs(
            {
                "address": OPTIMISM_L1_STANDARD_BRIDGE,
                "fromBlock": str(from_block),
                "toBlock": to_block,
                "topic0": topic0,
                "topic1": topic_addr(seed),
                "topic0_1_opr": "and",
                "page": str(page),
                "offset": str(min(1000, max_events)),
            },
            api_key,
        )
        rows.extend(batch)
        if len(rows) >= max_events or len(batch) < min(1000, max_events):
            break
    return rows[:max_events]


def raw_log(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "address": row.get("address"),
        "transactionHash": row.get("transactionHash"),
        "blockNumber": row.get("blockNumber"),
        "transactionIndex": row.get("transactionIndex"),
        "logIndex": row.get("logIndex"),
        "topics": row.get("topics") or [],
        "data": row.get("data"),
    }


def amount_eth(raw: Any) -> float:
    try:
        return int(raw) / 10**18
    except (TypeError, ValueError):
        return 0.0


def make_detail(event: dict[str, Any], seed: str, recipient: str, direction: str) -> dict[str, Any]:
    amount = amount_eth(event.get("rawAmount"))
    return {
        "event_id": event.get("id"),
        "address": seed,
        "tx_hash": event.get("txHash"),
        "block_number": event.get("blockNumber"),
        "category": "bridge",
        "protocol": "Optimism StandardBridge",
        "action": "ETHBridgeInitiated",
        "transfers": [
            {
                "direction": direction,
                "token": ZERO,
                "symbol": "ETH",
                "from": seed,
                "to": recipient,
                "amount": amount,
                "amount_source": "receipt_logs",
                "count": 1,
            }
        ],
    }


def build_payload(seed: str, events: list[dict[str, Any]], *, from_block: int, to_block: str, max_events: int) -> dict[str, Any]:
    seed = norm_addr(seed)
    parsed_events = [event for event in events if norm_addr(str(event.get("actor") or "")) == seed]
    parsed_events.sort(key=lambda event: (event.get("blockNumber") or 0, event.get("logIndex") or 0, event.get("txHash") or ""))
    if not parsed_events:
        raise RuntimeError("no parsed bridge events for seed")

    recipient_counts: dict[str, int] = {}
    for event in parsed_events:
        recipient = norm_addr(str(event.get("recipient") or ""))
        recipient_counts[recipient] = recipient_counts.get(recipient, 0) + 1
    recipient = max(recipient_counts.items(), key=lambda item: item[1])[0]

    total_eth = sum(amount_eth(event.get("rawAmount")) for event in parsed_events)
    first_block = parsed_events[0].get("blockNumber")
    last_block = parsed_events[-1].get("blockNumber")
    send_details = [make_detail(event, seed, recipient, "out") for event in parsed_events]
    receive_details = [make_detail(event, seed, recipient, "in") for event in parsed_events]

    seed_id = f"eoa:{seed}"
    bridge_id = "protocol:optimism-standard-bridge"
    recipient_id = f"counterparty:optimism:{recipient}"
    generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return {
        "nodes": [
            {
                "id": seed_id,
                "type": "eoa",
                "label": f"EOA {short_addr(seed)}",
                "data": {
                    "kind": "eoa",
                    "address": seed,
                    "dfs_depth": 0,
                    "discovered_by": "seed",
                    "event_count": len(parsed_events),
                    "category_counts": {"bridge": len(parsed_events)},
                    "first_seen_utc": None,
                    "last_seen_utc": None,
                },
            },
            {
                "id": bridge_id,
                "type": "protocol",
                "label": "Optimism L1 StandardBridge",
                "data": {
                    "kind": "protocol",
                    "category": "bridge",
                    "protocol": "canonical_bridge",
                    "address": norm_addr(OPTIMISM_L1_STANDARD_BRIDGE),
                    "event_count": len(parsed_events),
                    "target": "optimism",
                    "target_label": "Ethereum -> Optimism",
                },
            },
            {
                "id": recipient_id,
                "type": "counterparty",
                "label": f"OP recipient {short_addr(recipient)}",
                "data": {
                    "kind": "counterparty",
                    "category": "bridge_destination",
                    "protocol": "canonical_bridge",
                    "address": recipient,
                    "event_count": len(parsed_events),
                    "target": "optimism",
                    "target_label": "recipient on Optimism",
                },
            },
        ],
        "edges": [
            {
                "id": f"edge:bridge-send:{seed}:optimism",
                "source": seed_id,
                "target": bridge_id,
                "edge_type": "bridge_send",
                "category": "bridge",
                "label": f"{total_eth:,.2f} ETH bridged to Optimism",
                "amount": total_eth,
                "symbol": "ETH",
                "tx_hash": parsed_events[-1].get("txHash"),
                "event_count": len(parsed_events),
                "details": send_details,
            },
            {
                "id": f"edge:bridge-receive:{seed}:optimism:{recipient}",
                "source": bridge_id,
                "target": recipient_id,
                "edge_type": "bridge_receive",
                "category": "bridge",
                "label": f"{total_eth:,.2f} ETH recipient on Optimism",
                "amount": total_eth,
                "symbol": "ETH",
                "tx_hash": parsed_events[-1].get("txHash"),
                "event_count": len(parsed_events),
                "details": receive_details,
            },
        ],
        "events": send_details,
        "metadata": {
            "source": "feeder/bridge_eoa_flow.py (etherscan logs -> bridge_adapters.parse_bridge_logs)",
            "view": "d0",
            "format_version": 1,
            "address_count": 1,
            "event_count": len(parsed_events),
            "category_counts": {"bridge": len(parsed_events)},
            "max_events_per_address": max_events,
            "chain": "ethereum",
            "chain_id": 1,
            "from_block": first_block or from_block,
            "to_block": last_block or to_block,
            "receipt_transfers": "none",
            "important_only": False,
            "generated_at_utc": generated_at,
            "bridge": {
                "adapter": "bridge_adapters/1",
                "bridge": "canonical_bridge",
                "contract": norm_addr(OPTIMISM_L1_STANDARD_BRIDGE),
                "destination_chain_id": 10,
                "destination": "optimism",
                "total_eth": total_eth,
                "recipient": recipient,
            },
            "dfs": {
                "seed_addresses": [seed],
                "depth": 0,
                "directions": "bridge-events",
                "discovered_addresses": 1,
                "discovery_edges": 0,
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", default="0xf4e147db314947fc1275a8cbb6cde48c510cd8cf")
    parser.add_argument("--from-block", type=int, default=25_000_000)
    parser.add_argument("--to-block", default="latest")
    parser.add_argument("--max-events", type=int, default=500)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    env = load_env(args.env)
    api_key = env.get("ETHERSCAN_API_KEY") or ""
    if not api_key:
        raise RuntimeError("ETHERSCAN_API_KEY is not configured")

    rows = fetch_optimism_eth_bridge_logs(args.seed, args.from_block, args.to_block, api_key, args.max_events)
    parsed = parse_bridge_logs([raw_log(row) for row in rows], chain_id=1, source="etherscan_logs", emit_unknown_gaps=False)
    payload = build_payload(args.seed, parsed.get("events") or [], from_block=args.from_block, to_block=args.to_block, max_events=args.max_events)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / seed_file_name(args.seed, 0)
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    bridge = payload["metadata"]["bridge"]
    print(
        f"saved {out_path} events={payload['metadata']['event_count']} "
        f"total_eth={bridge['total_eth']:.6f} recipient={bridge['recipient']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
