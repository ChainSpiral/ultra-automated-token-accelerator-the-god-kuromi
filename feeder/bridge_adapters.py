#!/usr/bin/env python3
"""Proof-backed bridge semantic adapters.

Bridge adapters convert decoded receipt logs into normalized semantic bridge
events plus cross-chain scan routes. They intentionally do not create narrative
edges: if a receipt log does not expose enough machine-readable fields, the
adapter emits a gap instead of inventing a bridge relationship.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from eth_utils import keccak


ADAPTER_VERSION = "bridge_adapters/1"

CONFIDENCE_EXACT = "exact"
CONFIDENCE_RECEIPT = "inferred_from_receipt"
CONFIDENCE_GAP = "low_confidence_gap"

ZERO = "0x0000000000000000000000000000000000000000"


LAYERZERO_EIDS: dict[int, dict[str, Any]] = {
    30101: {"chainId": 1, "name": "ethereum"},
    30102: {"chainId": 56, "name": "bsc"},
    30106: {"chainId": 43114, "name": "avalanche"},
    30109: {"chainId": 137, "name": "polygon"},
    30110: {"chainId": 42161, "name": "arbitrum"},
    30111: {"chainId": 10, "name": "optimism"},
    30184: {"chainId": 8453, "name": "base"},
    30370: {"chainId": 98866, "name": "plume"},
}

CCTP_DOMAINS: dict[int, dict[str, Any]] = {
    0: {"chainId": 1, "name": "ethereum"},
    1: {"chainId": 43114, "name": "avalanche"},
    2: {"chainId": 10, "name": "optimism"},
    3: {"chainId": 42161, "name": "arbitrum"},
    4: {"chainId": None, "name": "noble"},
    5: {"chainId": None, "name": "solana"},
    6: {"chainId": 8453, "name": "base"},
    7: {"chainId": 137, "name": "polygon"},
}

WORMHOLE_CHAIN_IDS: dict[int, dict[str, Any]] = {
    1: {"chainId": None, "name": "solana"},
    2: {"chainId": 1, "name": "ethereum"},
    4: {"chainId": 56, "name": "bsc"},
    5: {"chainId": 137, "name": "polygon"},
    6: {"chainId": 43114, "name": "avalanche"},
    10: {"chainId": 250, "name": "fantom"},
    14: {"chainId": 42220, "name": "celo"},
    16: {"chainId": 1284, "name": "moonbeam"},
    23: {"chainId": 42161, "name": "arbitrum"},
    24: {"chainId": 10, "name": "optimism"},
    25: {"chainId": 100, "name": "gnosis"},
    30: {"chainId": 8453, "name": "base"},
}

CCIP_SELECTORS: dict[int, dict[str, Any]] = {
    5009297550715157269: {"chainId": 1, "name": "ethereum"},
    6433500567565415381: {"chainId": 43114, "name": "avalanche"},
    3734403246176062136: {"chainId": 10, "name": "optimism"},
    4949039107694359620: {"chainId": 42161, "name": "arbitrum"},
    4051577828743386545: {"chainId": 137, "name": "polygon"},
    15971525489660198786: {"chainId": 8453, "name": "base"},
}

CANONICAL_BRIDGE_CONTRACTS: dict[str, dict[str, Any]] = {
    "0x99c9fc46f92e8a1c0dec1b1747d010903e884be1": {"counterpartyChainId": 10, "counterpartyChainName": "optimism"},
    "0x3154cf16ccdb4c6d922629664174b904d80f2c35": {"counterpartyChainId": 8453, "counterpartyChainName": "base"},
}

LAYERZERO_EVENTS = {"OFTSent", "OFTReceived", "SendToChain", "ReceiveFromChain"}
CCTP_EVENTS = {"DepositForBurn", "DepositForBurnWithCaller", "MintAndWithdraw"}
WORMHOLE_EVENTS = {
    "LogMessagePublished",
    "TransferTokens",
    "TransferTokensWithPayload",
    "TransferRedeemed",
}
CCIP_EVENTS = {"CCIPSendRequested", "MessageExecuted", "ExecutionStateChanged"}
ACROSS_EVENTS = {"FundsDeposited", "FilledRelay"}
STARGATE_EVENTS = {"Swap", "RedeemRemote", "SendCredits", "CreditChainPath"}
SOCKET_EVENTS = {"SocketBridge", "SocketSwapTokens", "TokensBridged"}
CANONICAL_EVENTS = {
    "ETHBridgeInitiated",
    "ERC20BridgeInitiated",
    "ETHBridgeFinalized",
    "ERC20BridgeFinalized",
    "DepositInitiated",
    "WithdrawalInitiated",
    "WithdrawalFinalized",
}

LAYERZERO_OFT_EVENT_SIGNATURES = {
    "OFTSent": "OFTSent(bytes32,uint32,address,uint256,uint256)",
    "OFTReceived": "OFTReceived(bytes32,uint32,address,uint256)",
}

CANONICAL_BRIDGE_EVENT_SIGNATURES = {
    "ETHBridgeInitiated": "ETHBridgeInitiated(address,address,uint256,bytes)",
    "ETHBridgeFinalized": "ETHBridgeFinalized(address,address,uint256,bytes)",
    "ERC20BridgeInitiated": "ERC20BridgeInitiated(address,address,address,address,uint256,bytes)",
    "ERC20BridgeFinalized": "ERC20BridgeFinalized(address,address,address,address,uint256,bytes)",
}

LAYERZERO_OFT_TOPICS = {
    "0x" + keccak(text=signature).hex(): name
    for name, signature in LAYERZERO_OFT_EVENT_SIGNATURES.items()
}

CANONICAL_BRIDGE_TOPICS = {
    "0x" + keccak(text=signature).hex(): name
    for name, signature in CANONICAL_BRIDGE_EVENT_SIGNATURES.items()
}


def event_topic(signature: str) -> str:
    return "0x" + keccak(text=signature).hex()


def parse_bridge_logs(
    logs: Iterable[dict[str, Any]],
    *,
    chain_id: int = 1,
    source: str = "receipt_logs",
    emit_unknown_gaps: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """Parse decoded bridge logs across the supported bridge families."""

    output = _new_output()
    for log in logs:
        parsed = _parse_bridge_log(
            decode_bridge_log(log),
            chain_id=chain_id,
            source=source,
            emit_unknown_gaps=emit_unknown_gaps,
        )
        _extend(output, parsed)
    return output


def decode_bridge_log(log: dict[str, Any]) -> dict[str, Any]:
    """Decode known raw bridge logs, returning the original row when unsupported."""

    if _decoded_event_name(log):
        return log
    return decode_layerzero_oft_log(log) or decode_canonical_bridge_log(log) or log


def decode_layerzero_oft_log(log: dict[str, Any]) -> dict[str, Any] | None:
    """Decode LayerZero OFT v2 OFTSent/OFTReceived raw receipt logs."""

    topics = _topics(log)
    if not topics:
        return None
    event_name = LAYERZERO_OFT_TOPICS.get(topics[0])
    if not event_name:
        return None

    words = _words(log.get("data"))
    decoded = dict(log)
    if event_name == "OFTSent":
        if len(topics) < 3 or len(words) < 3:
            return None
        decoded["event"] = "OFTSent"
        decoded["args"] = {
            "guid": _topic_b32_at(topics, 1),
            "fromAddress": _topic_addr_at(topics, 2),
            "dstEid": _word_int_at(words, 0),
            "amountSentLD": _word_int_at(words, 1),
            "amountReceivedLD": _word_int_at(words, 2),
        }
        return decoded

    if len(topics) < 3 or len(words) < 2:
        return None
    decoded["event"] = "OFTReceived"
    decoded["args"] = {
        "guid": _topic_b32_at(topics, 1),
        "toAddress": _topic_addr_at(topics, 2),
        "srcEid": _word_int_at(words, 0),
        "amountReceivedLD": _word_int_at(words, 1),
    }
    return decoded


def decode_canonical_bridge_log(log: dict[str, Any]) -> dict[str, Any] | None:
    """Decode OP-stack StandardBridge raw ETH/ERC20 bridge logs."""

    topics = _topics(log)
    if not topics:
        return None
    event_name = CANONICAL_BRIDGE_TOPICS.get(topics[0])
    if not event_name:
        return None

    words = _words(log.get("data"))
    decoded = dict(log)
    decoded["event"] = event_name
    if event_name.startswith("ETHBridge"):
        if len(topics) < 3 or len(words) < 1:
            return None
        decoded["args"] = {
            "from": _topic_addr_at(topics, 1),
            "to": _topic_addr_at(topics, 2),
            "token": ZERO,
            "amount": _word_int_at(words, 0),
        }
        return decoded

    if len(topics) < 4 or len(words) < 2:
        return None
    decoded["args"] = {
        "localToken": _topic_addr_at(topics, 1),
        "remoteToken": _topic_addr_at(topics, 2),
        "from": _topic_addr_at(topics, 3),
        "to": _word_addr_at(words, 0),
        "amount": _word_int_at(words, 1),
    }
    return decoded


def parse_layerzero_oft_logs(
    logs: Iterable[dict[str, Any]],
    *,
    chain_id: int = 1,
    source: str = "receipt_logs",
) -> dict[str, list[dict[str, Any]]]:
    return _parse_logs_with((decode_bridge_log(log) for log in logs), "layerzero_oft", chain_id=chain_id, source=source)


def parse_cctp_logs(
    logs: Iterable[dict[str, Any]],
    *,
    chain_id: int = 1,
    source: str = "receipt_logs",
) -> dict[str, list[dict[str, Any]]]:
    return _parse_logs_with(logs, "cctp", chain_id=chain_id, source=source)


def parse_wormhole_logs(
    logs: Iterable[dict[str, Any]],
    *,
    chain_id: int = 1,
    source: str = "receipt_logs",
) -> dict[str, list[dict[str, Any]]]:
    return _parse_logs_with(logs, "wormhole", chain_id=chain_id, source=source)


def parse_ccip_logs(
    logs: Iterable[dict[str, Any]],
    *,
    chain_id: int = 1,
    source: str = "receipt_logs",
) -> dict[str, list[dict[str, Any]]]:
    return _parse_logs_with(logs, "ccip", chain_id=chain_id, source=source)


def parse_across_logs(
    logs: Iterable[dict[str, Any]],
    *,
    chain_id: int = 1,
    source: str = "receipt_logs",
) -> dict[str, list[dict[str, Any]]]:
    return _parse_logs_with(logs, "across", chain_id=chain_id, source=source)


def parse_stargate_logs(
    logs: Iterable[dict[str, Any]],
    *,
    chain_id: int = 1,
    source: str = "receipt_logs",
) -> dict[str, list[dict[str, Any]]]:
    return _parse_logs_with(logs, "stargate", chain_id=chain_id, source=source)


def parse_socket_logs(
    logs: Iterable[dict[str, Any]],
    *,
    chain_id: int = 1,
    source: str = "receipt_logs",
) -> dict[str, list[dict[str, Any]]]:
    return _parse_logs_with(logs, "socket", chain_id=chain_id, source=source)


def parse_canonical_bridge_logs(
    logs: Iterable[dict[str, Any]],
    *,
    chain_id: int = 1,
    source: str = "receipt_logs",
) -> dict[str, list[dict[str, Any]]]:
    return _parse_logs_with(logs, "canonical_bridge", chain_id=chain_id, source=source)


def match_bridge_routes(
    outbound_events: Iterable[dict[str, Any]],
    inbound_events: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pair bridge send/receive events when both sides expose a deterministic id."""

    outbound_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for event in outbound_events:
        if event.get("direction") != "out":
            continue
        key = _match_key(event)
        if key:
            outbound_by_key.setdefault(key, []).append(event)

    matches: list[dict[str, Any]] = []
    for inbound in inbound_events:
        if inbound.get("direction") != "in":
            continue
        key = _match_key(inbound)
        if not key:
            continue
        for outbound in outbound_by_key.get(key, []):
            evidence_ids = [
                *outbound.get("evidenceIds", []),
                *inbound.get("evidenceIds", []),
            ]
            matches.append({
                "id": _record_id("bridge_match", key, outbound.get("txHash"), inbound.get("txHash")),
                "bridge": outbound.get("bridge") or inbound.get("bridge"),
                "matchKey": key[1],
                "sourceChainId": outbound.get("chainId"),
                "destinationChainId": inbound.get("chainId"),
                "sourceTx": outbound.get("txHash"),
                "destinationTx": inbound.get("txHash"),
                "actor": outbound.get("actor"),
                "recipient": inbound.get("recipient") or outbound.get("recipient"),
                "token": outbound.get("tokenAddress") or inbound.get("tokenAddress"),
                "rawAmount": outbound.get("rawAmount") or inbound.get("rawAmount"),
                "confidence": CONFIDENCE_EXACT,
                "evidenceIds": sorted(set(evidence_ids)),
            })
    return matches


def _parse_logs_with(
    logs: Iterable[dict[str, Any]],
    bridge: str,
    *,
    chain_id: int,
    source: str,
) -> dict[str, list[dict[str, Any]]]:
    output = _new_output()
    for log in logs:
        parsed = _parse_for_bridge(bridge, log, chain_id=chain_id, source=source)
        _extend(output, parsed)
    return output


def _parse_bridge_log(
    log: dict[str, Any],
    *,
    chain_id: int,
    source: str,
    emit_unknown_gaps: bool,
) -> dict[str, list[dict[str, Any]]]:
    bridge = _bridge_family(log)
    if not bridge:
        if not emit_unknown_gaps:
            return _new_output()
        return _gap_output(log, "bridge", chain_id, "unsupported_or_undecoded_bridge_log")
    return _parse_for_bridge(bridge, log, chain_id=chain_id, source=source)


def _parse_for_bridge(
    bridge: str,
    log: dict[str, Any],
    *,
    chain_id: int,
    source: str,
) -> dict[str, list[dict[str, Any]]]:
    if bridge == "layerzero_oft":
        return _parse_layerzero_oft_log(log, chain_id=chain_id, source=source)
    if bridge == "cctp":
        return _parse_cctp_log(log, chain_id=chain_id, source=source)
    if bridge == "wormhole":
        return _parse_wormhole_log(log, chain_id=chain_id, source=source)
    if bridge == "ccip":
        return _parse_ccip_log(log, chain_id=chain_id, source=source)
    if bridge == "across":
        return _parse_across_log(log, chain_id=chain_id, source=source)
    if bridge == "stargate":
        return _parse_stargate_log(log, chain_id=chain_id, source=source)
    if bridge == "socket":
        return _parse_socket_log(log, chain_id=chain_id, source=source)
    if bridge == "canonical_bridge":
        return _parse_canonical_bridge_log(log, chain_id=chain_id, source=source)
    return _gap_output(log, bridge, chain_id, "unsupported_bridge_family")


def _parse_layerzero_oft_log(
    log: dict[str, Any],
    *,
    chain_id: int,
    source: str,
) -> dict[str, list[dict[str, Any]]]:
    name = _decoded_event_name(log)
    if name not in LAYERZERO_EVENTS:
        return _gap_output(log, "layerzero_oft", chain_id, "unsupported_layerzero_event")

    args = _args(log)
    contract = _contract_address(log)
    guid = _lower_hex(_first(args, "guid", "messageId", "message_id"))
    raw_amount = _arg_int(args, "amountSentLD", "amountReceivedLD", "amountLD", "amount")
    token_amount = _token_amount(contract, raw_amount, symbol=_first(args, "symbol"))
    block_number = _block_number(log)
    tx_hash = _tx_hash(log)
    log_index = _log_index(log)

    if name in {"OFTSent", "SendToChain"}:
        dst_eid = _arg_int(args, "dstEid", "dstChainId", "chainId")
        dst = LAYERZERO_EIDS.get(dst_eid or -1, {})
        actor = _arg_addr(args, "fromAddress", "from", "sender")
        recipient = _arg_addr(args, "toAddress", "to", "recipient") or _bytes32_to_address(_first(args, "toAddress", "to", "recipient"))
        extra = {
            "bridge": "layerzero_oft",
            "direction": "out",
            "actor": actor,
            "recipient": recipient,
            "tokenAddress": contract,
            "rawAmount": str(raw_amount) if raw_amount is not None else None,
            "guid": guid,
            "dstEid": dst_eid,
            "destinationEndpointId": dst_eid,
            "dstChainId": dst.get("chainId"),
            "destinationChainId": dst.get("chainId"),
            "counterpartyChainId": dst.get("chainId"),
            "counterpartyChainName": dst.get("name"),
        }
        return _event_output(
            log,
            adapter="bridge-layerzero-oft",
            bridge="layerzero_oft",
            chain_id=chain_id,
            source=source,
            event_name=name,
            token_amount=token_amount,
            extra=extra,
            route_reason="layerzero_oft_out",
        )

    src_eid = _arg_int(args, "srcEid", "srcChainId", "chainId")
    src = LAYERZERO_EIDS.get(src_eid or -1, {})
    recipient = _arg_addr(args, "toAddress", "to", "recipient") or _bytes32_to_address(_first(args, "toAddress", "to", "recipient"))
    extra = {
        "bridge": "layerzero_oft",
        "direction": "in",
        "actor": recipient,
        "recipient": recipient,
        "tokenAddress": contract,
        "rawAmount": str(raw_amount) if raw_amount is not None else None,
        "guid": guid,
        "srcEid": src_eid,
        "sourceEndpointId": src_eid,
        "srcChainId": src.get("chainId"),
        "sourceChainId": src.get("chainId"),
        "counterpartyChainId": src.get("chainId"),
        "counterpartyChainName": src.get("name"),
    }
    return _event_output(
        log,
        adapter="bridge-layerzero-oft",
        bridge="layerzero_oft",
        chain_id=chain_id,
        source=source,
        event_name=name,
        token_amount=token_amount,
        extra=extra,
        route_reason=None,
        confidence=CONFIDENCE_EXACT if guid else CONFIDENCE_RECEIPT,
    )


def _parse_cctp_log(
    log: dict[str, Any],
    *,
    chain_id: int,
    source: str,
) -> dict[str, list[dict[str, Any]]]:
    name = _decoded_event_name(log)
    if name not in CCTP_EVENTS:
        return _gap_output(log, "cctp", chain_id, "unsupported_cctp_event")

    args = _args(log)
    contract = _contract_address(log)
    if name.startswith("DepositForBurn"):
        destination_domain = _arg_int(args, "destinationDomain", "destination_domain")
        destination = CCTP_DOMAINS.get(destination_domain or -1, {})
        token = _arg_addr(args, "burnToken", "token") or contract
        raw_amount = _arg_int(args, "amount")
        recipient = _arg_addr(args, "mintRecipient", "recipient") or _bytes32_to_address(_first(args, "mintRecipient", "recipient"))
        extra = {
            "bridge": "cctp",
            "direction": "out",
            "actor": _arg_addr(args, "depositor", "from", "sender"),
            "recipient": recipient,
            "tokenAddress": token,
            "rawAmount": str(raw_amount) if raw_amount is not None else None,
            "destinationDomain": destination_domain,
            "dstChainId": destination.get("chainId"),
            "destinationChainId": destination.get("chainId"),
            "counterpartyChainId": destination.get("chainId"),
            "counterpartyChainName": destination.get("name"),
            "nonce": _arg_int(args, "nonce"),
        }
        return _event_output(
            log,
            adapter="bridge-cctp",
            bridge="cctp",
            chain_id=chain_id,
            source=source,
            event_name=name,
            token_amount=_token_amount(token, raw_amount),
            extra=extra,
            route_reason="cctp_deposit_for_burn",
        )

    token = _arg_addr(args, "mintToken", "token") or contract
    raw_amount = _arg_int(args, "amount")
    recipient = _arg_addr(args, "mintRecipient", "recipient", "to")
    extra = {
        "bridge": "cctp",
        "direction": "in",
        "actor": recipient,
        "recipient": recipient,
        "tokenAddress": token,
        "rawAmount": str(raw_amount) if raw_amount is not None else None,
    }
    return _event_output(
        log,
        adapter="bridge-cctp",
        bridge="cctp",
        chain_id=chain_id,
        source=source,
        event_name=name,
        token_amount=_token_amount(token, raw_amount),
        extra=extra,
        route_reason=None,
    )


def _parse_wormhole_log(
    log: dict[str, Any],
    *,
    chain_id: int,
    source: str,
) -> dict[str, list[dict[str, Any]]]:
    name = _decoded_event_name(log)
    if name not in WORMHOLE_EVENTS:
        return _gap_output(log, "wormhole", chain_id, "unsupported_wormhole_event")

    args = _args(log)
    contract = _contract_address(log)
    raw_amount = _arg_int(args, "amount", "amountRaw")
    token = _arg_addr(args, "token", "tokenAddress", "asset") or contract
    sequence = _arg_int(args, "sequence")

    if name in {"TransferRedeemed"}:
        src_chain = _arg_int(args, "emitterChainId", "sourceChain", "srcChainId")
        source_chain = WORMHOLE_CHAIN_IDS.get(src_chain or -1, {})
        recipient = _arg_addr(args, "recipient", "to")
        extra = {
            "bridge": "wormhole",
            "direction": "in",
            "actor": recipient,
            "recipient": recipient,
            "tokenAddress": token,
            "rawAmount": str(raw_amount) if raw_amount is not None else None,
            "sequence": sequence,
            "srcWormholeChainId": src_chain,
            "srcChainId": source_chain.get("chainId"),
            "sourceChainId": source_chain.get("chainId"),
            "counterpartyChainId": source_chain.get("chainId"),
            "counterpartyChainName": source_chain.get("name"),
        }
        return _event_output(log, adapter="bridge-wormhole", bridge="wormhole", chain_id=chain_id, source=source, event_name=name, token_amount=_token_amount(token, raw_amount), extra=extra, route_reason=None)

    dst_chain = _arg_int(args, "targetChain", "recipientChain", "dstChainId", "chainId")
    destination = WORMHOLE_CHAIN_IDS.get(dst_chain or -1, {})
    extra = {
        "bridge": "wormhole",
        "direction": "out",
        "actor": _arg_addr(args, "sender", "from"),
        "recipient": _arg_addr(args, "recipient", "to") or _bytes32_to_address(_first(args, "recipient", "to")),
        "tokenAddress": token,
        "rawAmount": str(raw_amount) if raw_amount is not None else None,
        "sequence": sequence,
        "dstWormholeChainId": dst_chain,
        "dstChainId": destination.get("chainId"),
        "destinationChainId": destination.get("chainId"),
        "counterpartyChainId": destination.get("chainId"),
        "counterpartyChainName": destination.get("name"),
    }
    confidence = CONFIDENCE_EXACT if dst_chain is not None and raw_amount is not None else CONFIDENCE_RECEIPT
    reason = "wormhole_token_transfer" if dst_chain is not None else None
    return _event_output(
        log,
        adapter="bridge-wormhole",
        bridge="wormhole",
        chain_id=chain_id,
        source=source,
        event_name=name,
        token_amount=_token_amount(token, raw_amount),
        extra=extra,
        route_reason=reason,
        confidence=confidence,
    )


def _parse_ccip_log(
    log: dict[str, Any],
    *,
    chain_id: int,
    source: str,
) -> dict[str, list[dict[str, Any]]]:
    name = _decoded_event_name(log)
    if name not in CCIP_EVENTS:
        return _gap_output(log, "ccip", chain_id, "unsupported_ccip_event")

    args = _args(log)
    message = _first(args, "message") if isinstance(_first(args, "message"), dict) else args
    message = message if isinstance(message, dict) else args
    token, raw_amount = _ccip_token_amount(message)

    if name == "CCIPSendRequested":
        selector = _arg_int(message, "destChainSelector", "destinationChainSelector")
        destination = CCIP_SELECTORS.get(selector or -1, {})
        receiver = _arg_addr(message, "receiver", "recipient") or _bytes32_to_address(_first(message, "receiver", "recipient"))
        extra = {
            "bridge": "ccip",
            "direction": "out",
            "actor": _arg_addr(message, "sender", "from"),
            "recipient": receiver,
            "tokenAddress": token,
            "rawAmount": str(raw_amount) if raw_amount is not None else None,
            "messageId": _lower_hex(_first(message, "messageId", "id")),
            "destinationChainSelector": selector,
            "dstChainId": destination.get("chainId"),
            "destinationChainId": destination.get("chainId"),
            "counterpartyChainId": destination.get("chainId"),
            "counterpartyChainName": destination.get("name"),
        }
        return _event_output(log, adapter="bridge-ccip", bridge="ccip", chain_id=chain_id, source=source, event_name=name, token_amount=_token_amount(token, raw_amount), extra=extra, route_reason="ccip_send_requested")

    selector = _arg_int(message, "sourceChainSelector", "srcChainSelector")
    source_chain = CCIP_SELECTORS.get(selector or -1, {})
    receiver = _arg_addr(message, "receiver", "recipient", "to")
    extra = {
        "bridge": "ccip",
        "direction": "in",
        "actor": receiver,
        "recipient": receiver,
        "tokenAddress": token,
        "rawAmount": str(raw_amount) if raw_amount is not None else None,
        "messageId": _lower_hex(_first(message, "messageId", "id")),
        "sourceChainSelector": selector,
        "srcChainId": source_chain.get("chainId"),
        "sourceChainId": source_chain.get("chainId"),
        "counterpartyChainId": source_chain.get("chainId"),
        "counterpartyChainName": source_chain.get("name"),
    }
    return _event_output(log, adapter="bridge-ccip", bridge="ccip", chain_id=chain_id, source=source, event_name=name, token_amount=_token_amount(token, raw_amount), extra=extra, route_reason=None, confidence=CONFIDENCE_RECEIPT)


def _parse_across_log(
    log: dict[str, Any],
    *,
    chain_id: int,
    source: str,
) -> dict[str, list[dict[str, Any]]]:
    name = _decoded_event_name(log)
    if name not in ACROSS_EVENTS:
        return _gap_output(log, "across", chain_id, "unsupported_across_event")

    args = _args(log)
    if name == "FundsDeposited":
        raw_amount = _arg_int(args, "inputAmount", "amount")
        token = _arg_addr(args, "inputToken", "token")
        dst_chain = _arg_int(args, "destinationChainId", "dstChainId")
        extra = {
            "bridge": "across",
            "direction": "out",
            "actor": _arg_addr(args, "depositor", "from", "sender"),
            "recipient": _arg_addr(args, "recipient", "to"),
            "tokenAddress": token,
            "rawAmount": str(raw_amount) if raw_amount is not None else None,
            "depositId": _arg_int(args, "depositId"),
            "dstChainId": dst_chain,
            "destinationChainId": dst_chain,
            "counterpartyChainId": dst_chain,
        }
        return _event_output(log, adapter="bridge-across", bridge="across", chain_id=chain_id, source=source, event_name=name, token_amount=_token_amount(token, raw_amount), extra=extra, route_reason="across_funds_deposited")

    raw_amount = _arg_int(args, "outputAmount", "inputAmount", "amount")
    token = _arg_addr(args, "outputToken", "inputToken", "token")
    origin_chain = _arg_int(args, "originChainId", "sourceChainId", "srcChainId")
    recipient = _arg_addr(args, "recipient", "to")
    extra = {
        "bridge": "across",
        "direction": "in",
        "actor": recipient,
        "recipient": recipient,
        "relayer": _arg_addr(args, "relayer"),
        "tokenAddress": token,
        "rawAmount": str(raw_amount) if raw_amount is not None else None,
        "depositId": _arg_int(args, "depositId"),
        "srcChainId": origin_chain,
        "sourceChainId": origin_chain,
        "counterpartyChainId": origin_chain,
    }
    return _event_output(log, adapter="bridge-across", bridge="across", chain_id=chain_id, source=source, event_name=name, token_amount=_token_amount(token, raw_amount), extra=extra, route_reason=None)


def _parse_stargate_log(
    log: dict[str, Any],
    *,
    chain_id: int,
    source: str,
) -> dict[str, list[dict[str, Any]]]:
    name = _decoded_event_name(log)
    if name in LAYERZERO_EVENTS:
        parsed = _parse_layerzero_oft_log(log, chain_id=chain_id, source=source)
        for event in parsed["events"]:
            event["bridge"] = "stargate"
            event["adapter"] = "bridge-stargate"
        for evidence in parsed["evidence"]:
            evidence["adapter"] = "bridge-stargate"
        for route in parsed["routes"]:
            route["bridge"] = "stargate"
        return parsed
    if name not in STARGATE_EVENTS:
        return _gap_output(log, "stargate", chain_id, "unsupported_stargate_event")

    args = _args(log)
    raw_amount = _arg_int(args, "amountLD", "amountSD", "amount")
    token = _contract_address(log)
    dst_chain = _arg_int(args, "dstChainId", "chainId")
    extra = {
        "bridge": "stargate",
        "direction": "out" if name in {"Swap", "SendCredits"} else "in",
        "actor": _arg_addr(args, "from", "sender", "to"),
        "recipient": _arg_addr(args, "to", "recipient"),
        "tokenAddress": token,
        "rawAmount": str(raw_amount) if raw_amount is not None else None,
        "dstStargateChainId": dst_chain,
        "destinationChainId": dst_chain,
        "counterpartyChainId": dst_chain,
    }
    return _event_output(log, adapter="bridge-stargate", bridge="stargate", chain_id=chain_id, source=source, event_name=name, token_amount=_token_amount(token, raw_amount), extra=extra, route_reason="stargate_swap" if extra["direction"] == "out" else None, confidence=CONFIDENCE_RECEIPT)


def _parse_socket_log(
    log: dict[str, Any],
    *,
    chain_id: int,
    source: str,
) -> dict[str, list[dict[str, Any]]]:
    name = _decoded_event_name(log)
    if name not in SOCKET_EVENTS and not _socket_like(log):
        return _gap_output(log, "socket", chain_id, "unsupported_socket_event")

    args = _args(log)
    dst_chain = _arg_int(args, "toChainId", "dstChainId", "destinationChainId")
    raw_amount = _arg_int(args, "amount", "inputAmount")
    token = _arg_addr(args, "token", "inputToken", "asset") or _contract_address(log)
    extra = {
        "bridge": "socket",
        "direction": "out",
        "actor": _arg_addr(args, "sender", "from", "depositor"),
        "recipient": _arg_addr(args, "receiver", "recipient", "to"),
        "tokenAddress": token,
        "rawAmount": str(raw_amount) if raw_amount is not None else None,
        "dstChainId": dst_chain,
        "destinationChainId": dst_chain,
        "counterpartyChainId": dst_chain,
        "bridgeName": _first(args, "bridgeName", "bridge"),
    }
    return _event_output(log, adapter="bridge-socket", bridge="socket", chain_id=chain_id, source=source, event_name=name or "SocketBridge", token_amount=_token_amount(token, raw_amount), extra=extra, route_reason="socket_bridge" if dst_chain else None, confidence=CONFIDENCE_RECEIPT)


def _parse_canonical_bridge_log(
    log: dict[str, Any],
    *,
    chain_id: int,
    source: str,
) -> dict[str, list[dict[str, Any]]]:
    name = _decoded_event_name(log)
    if name not in CANONICAL_EVENTS:
        return _gap_output(log, "canonical_bridge", chain_id, "unsupported_canonical_bridge_event")

    args = _args(log)
    initiated = name.endswith("Initiated")
    direction = "out" if initiated else "in"
    raw_amount = _arg_int(args, "amount", "value")
    token = _arg_addr(args, "l1Token", "localToken", "token") or _arg_addr(args, "l2Token", "remoteToken") or _contract_address(log)
    contract_meta = CANONICAL_BRIDGE_CONTRACTS.get(_contract_address(log) or "", {})
    counterparty_chain = _arg_int(args, "dstChainId", "destinationChainId", "l2ChainId", "srcChainId", "sourceChainId", "l1ChainId")
    if counterparty_chain is None:
        counterparty_chain = _parse_int(contract_meta.get("counterpartyChainId"))
    extra = {
        "bridge": "canonical_bridge",
        "direction": direction,
        "actor": _arg_addr(args, "from", "sender"),
        "recipient": _arg_addr(args, "to", "recipient"),
        "tokenAddress": token,
        "rawAmount": str(raw_amount) if raw_amount is not None else None,
        "counterpartyChainId": counterparty_chain,
        "counterpartyChainName": contract_meta.get("counterpartyChainName"),
        "destinationChainId": counterparty_chain if direction == "out" else None,
        "sourceChainId": counterparty_chain if direction == "in" else None,
    }
    return _event_output(log, adapter="bridge-canonical", bridge="canonical_bridge", chain_id=chain_id, source=source, event_name=name, token_amount=_token_amount(token, raw_amount), extra=extra, route_reason="canonical_bridge_out" if direction == "out" and counterparty_chain else None, confidence=CONFIDENCE_RECEIPT)


def _event_output(
    log: dict[str, Any],
    *,
    adapter: str,
    bridge: str,
    chain_id: int,
    source: str,
    event_name: str,
    token_amount: dict[str, Any],
    extra: dict[str, Any],
    route_reason: str | None,
    confidence: str = CONFIDENCE_EXACT,
) -> dict[str, list[dict[str, Any]]]:
    block_number = _block_number(log)
    tx_hash = _tx_hash(log)
    log_index = _log_index(log)
    contract = _contract_address(log)
    evidence = _evidence(
        adapter=adapter,
        source=source,
        chain_id=chain_id,
        block_number=block_number,
        tx_hash=tx_hash,
        log_index=log_index,
        contract=contract,
        event_name=event_name,
        token_amount=token_amount,
        confidence=confidence,
        extra={"bridge": bridge, "decodedArgs": _jsonish(_args(log))},
    )
    event = {
        "id": _record_id("sem", adapter, bridge, tx_hash, log_index, block_number, extra),
        "type": "bridge",
        "semanticType": "bridge",
        "protocol": bridge,
        "bridge": bridge,
        "adapter": adapter,
        "adapterVersion": ADAPTER_VERSION,
        "chainId": chain_id,
        "blockNumber": block_number,
        "txHash": tx_hash,
        "logIndex": log_index,
        "contractAddress": contract,
        "token": token_amount,
        "evidenceIds": [evidence["id"]],
    }
    event.update({k: v for k, v in extra.items() if v is not None})

    output = _new_output()
    output["events"].append(event)
    output["evidence"].append(evidence)
    route = _route_from_event(event, route_reason)
    if route:
        output["routes"].append(route)
    return output


def _route_from_event(event: dict[str, Any], reason: str | None) -> dict[str, Any] | None:
    if not reason or event.get("direction") != "out":
        return None
    destination_chain = event.get("destinationChainId") or event.get("dstChainId")
    if destination_chain is None and event.get("counterpartyChainId") is None:
        return None
    return {
        "id": _record_id("bridge_route", event.get("bridge"), event.get("txHash"), event.get("logIndex"), event.get("recipient"), destination_chain),
        "bridge": event.get("bridge"),
        "direction": "out",
        "source_chain_id": event.get("chainId"),
        "destination_chain_id": destination_chain or event.get("counterpartyChainId"),
        "destination_eid": event.get("dstEid"),
        "source_tx": event.get("txHash"),
        "recipient": event.get("recipient"),
        "asset": event.get("tokenAddress") or (event.get("token") or {}).get("tokenAddress"),
        "amount": event.get("rawAmount") or (event.get("token") or {}).get("rawAmount"),
        "reason": reason,
        "confidence": CONFIDENCE_EXACT if event.get("guid") or event.get("messageId") or event.get("depositId") is not None else CONFIDENCE_RECEIPT,
        "evidenceIds": event.get("evidenceIds", []),
    }


def _evidence(
    *,
    adapter: str,
    source: str,
    chain_id: int,
    block_number: int | None,
    tx_hash: str | None,
    log_index: int | None,
    contract: str | None,
    event_name: str,
    token_amount: dict[str, Any],
    confidence: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "source": source,
        "adapter": adapter,
        "chainId": chain_id,
        "blockNumber": block_number,
        "txHash": tx_hash,
        "logIndex": log_index,
        "contractAddress": contract,
        "eventName": event_name,
        "token": token_amount,
        "confidence": confidence,
        "extra": extra,
    }
    evidence = {
        "id": _record_id("ev", payload),
        "source": source,
        "adapter": adapter,
        "adapterVersion": ADAPTER_VERSION,
        "confidence": confidence,
        "chainId": chain_id,
        "blockNumber": block_number,
        "eventName": event_name,
    }
    if tx_hash:
        evidence["txHash"] = tx_hash
    if log_index is not None:
        evidence["logIndex"] = log_index
    if contract:
        evidence["contractAddress"] = contract
    if token_amount:
        evidence["token"] = token_amount
        evidence.update({k: v for k, v in token_amount.items() if v is not None})
    if extra:
        for key, value in extra.items():
            if value is not None:
                evidence[key] = value
    return evidence


def _gap_output(log: dict[str, Any], adapter: str, chain_id: int, reason: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "events": [],
        "evidence": [],
        "routes": [],
        "gaps": [{
            "kind": "needs_adapter",
            "adapter": adapter,
            "adapterVersion": ADAPTER_VERSION,
            "chainId": chain_id,
            "blockNumber": _block_number(log),
            "txHash": _tx_hash(log),
            "logIndex": _log_index(log),
            "contractAddress": _contract_address(log),
            "eventName": _decoded_event_name(log),
            "reason": reason,
            "confidence": CONFIDENCE_GAP,
        }],
    }


def _bridge_family(log: dict[str, Any]) -> str | None:
    name = _decoded_event_name(log)
    if name in LAYERZERO_EVENTS:
        return "layerzero_oft"
    if name in CCTP_EVENTS:
        return "cctp"
    if name in WORMHOLE_EVENTS:
        return "wormhole"
    if name in CCIP_EVENTS:
        return "ccip"
    if name in ACROSS_EVENTS:
        return "across"
    if _stargate_like(log):
        return "stargate"
    if name in SOCKET_EVENTS or _socket_like(log):
        return "socket"
    if name in CANONICAL_EVENTS:
        return "canonical_bridge"
    return None


def _socket_like(log: dict[str, Any]) -> bool:
    name = _decoded_event_name(log)
    args = _args(log)
    return name == "Bridge" and _first(args, "toChainId", "dstChainId", "destinationChainId") is not None


def _stargate_like(log: dict[str, Any]) -> bool:
    name = _decoded_event_name(log)
    if name not in STARGATE_EVENTS:
        return False
    args = _args(log)
    if name != "Swap":
        return True
    return _first(args, "dstChainId", "chainId", "dstPoolId", "amountSD", "amountLD") is not None


def _match_key(event: dict[str, Any]) -> tuple[str, str] | None:
    bridge = str(event.get("bridge") or "")
    for key in ("guid", "messageId", "sequence", "depositId"):
        value = event.get(key)
        if value is not None:
            return bridge, str(value).lower()
    return None


def _ccip_token_amount(message: dict[str, Any]) -> tuple[str | None, int | None]:
    token_amounts = _first(message, "tokenAmounts", "destTokenAmounts", "sourceTokenAmounts")
    if isinstance(token_amounts, list) and token_amounts:
        first = token_amounts[0]
        if isinstance(first, dict):
            return _arg_addr(first, "token", "tokenAddress"), _arg_int(first, "amount")
        if isinstance(first, (list, tuple)) and len(first) >= 2:
            return _norm_addr(first[0]), _parse_int(first[1])
    return _arg_addr(message, "token", "tokenAddress"), _arg_int(message, "amount")


def _new_output() -> dict[str, list[dict[str, Any]]]:
    return {"events": [], "evidence": [], "gaps": [], "routes": []}


def _extend(output: dict[str, list[dict[str, Any]]], other: dict[str, list[dict[str, Any]]]) -> None:
    for key in ("events", "evidence", "gaps", "routes"):
        output.setdefault(key, []).extend(other.get(key, []))


def _token_amount(token: str | None, raw_amount: int | None, *, symbol: Any = None, decimals: Any = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if token:
        out["tokenAddress"] = token
    if isinstance(symbol, str) and symbol:
        out["symbol"] = symbol
    parsed_decimals = _parse_int(decimals)
    if parsed_decimals is not None:
        out["decimals"] = parsed_decimals
    if raw_amount is not None:
        out["rawAmount"] = str(raw_amount)
        if parsed_decimals is not None:
            out["amount"] = raw_amount / (10 ** parsed_decimals)
    return out


def _arg_addr(args: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = _first(args, name)
        normalized = _norm_addr(value) or _bytes32_to_address(value)
        if normalized:
            return normalized
    return None


def _arg_int(args: dict[str, Any], *names: str) -> int | None:
    return _parse_int(_first(args, *names))


def _topics(log: dict[str, Any]) -> list[str]:
    topics = log.get("topics") or []
    if not isinstance(topics, list):
        return []
    return [str(topic).lower() for topic in topics if isinstance(topic, str)]


def _words(data: Any) -> list[str]:
    if not isinstance(data, str):
        return []
    clean = data[2:] if data.startswith("0x") else data
    if len(clean) % 64 != 0:
        return []
    return ["0x" + clean[i : i + 64].lower() for i in range(0, len(clean), 64)]


def _topic_addr_at(topics: list[str], index: int) -> str | None:
    if index >= len(topics):
        return None
    return _bytes32_to_address(topics[index])


def _topic_b32_at(topics: list[str], index: int) -> str | None:
    if index >= len(topics):
        return None
    value = topics[index]
    clean = value[2:] if value.startswith("0x") else value
    if len(clean) != 64:
        return None
    try:
        int(clean, 16)
    except ValueError:
        return None
    return "0x" + clean.lower()


def _word_int_at(words: list[str], index: int) -> int | None:
    if index >= len(words):
        return None
    return _parse_int(words[index])


def _word_addr_at(words: list[str], index: int) -> str | None:
    if index >= len(words):
        return None
    return _bytes32_to_address(words[index])


def _args(log: dict[str, Any]) -> dict[str, Any]:
    args = log.get("args") or log.get("decodedArgs")
    return args if isinstance(args, dict) else {}


def _decoded_event_name(log: dict[str, Any]) -> str | None:
    value = log.get("eventName") or log.get("event") or log.get("name")
    return value if isinstance(value, str) and value else None


def _block_number(log: dict[str, Any]) -> int | None:
    return _parse_int(log.get("blockNumber") or log.get("block"))


def _log_index(log: dict[str, Any]) -> int | None:
    return _parse_int(log.get("logIndex") or log.get("log_index"))


def _tx_hash(log: dict[str, Any]) -> str | None:
    value = log.get("transactionHash") or log.get("txHash") or log.get("tx")
    return _lower_hex(value) if isinstance(value, str) else None


def _contract_address(log: dict[str, Any]) -> str | None:
    return _norm_addr(log.get("address") or log.get("contractAddress"))


def _norm_addr(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.lower()
    if clean.startswith("0x"):
        clean = clean[2:]
    if len(clean) != 40:
        return None
    try:
        int(clean, 16)
    except ValueError:
        return None
    return "0x" + clean


def _bytes32_to_address(value: Any) -> str | None:
    if isinstance(value, bytes):
        value = "0x" + value.hex()
    if not isinstance(value, str):
        return None
    clean = value.lower()
    if clean.startswith("0x"):
        clean = clean[2:]
    if len(clean) != 64:
        return None
    try:
        int(clean, 16)
    except ValueError:
        return None
    return _norm_addr("0x" + clean[-40:])


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        if not value:
            return None
        try:
            return int(value, 16) if value.startswith("0x") else int(value)
        except ValueError:
            return None
    return None


def _lower_hex(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.lower()


def _first(mapping: dict[str, Any], *keys: Any) -> Any:
    for key in keys:
        value = _nested_get(mapping, key)
        if value is not None:
            return value
    return None


def _nested_get(mapping: dict[str, Any], key: Any) -> Any:
    if isinstance(key, tuple):
        cur: Any = mapping
        for part in key:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur
    return mapping.get(key)


def _record_id(prefix: str, *parts: Any) -> str:
    blob = json.dumps(_jsonish(parts), sort_keys=True, separators=(",", ":"))
    return f"{prefix}:{hashlib.sha256(blob.encode()).hexdigest()[:20]}"


def _jsonish(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(k): _jsonish(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_jsonish(v) for v in value]
        return str(value)
