#!/usr/bin/env python3
"""Proof-backed protocol semantic adapters for strategy graph ingestion.

The functions in this module are intentionally source-agnostic. Collectors can
feed decoded receipt logs, raw receipt logs, or protocol API rows, and each
normalized semantic event carries evidence ids back to the machine proof that
created it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Iterable

from eth_utils import keccak


ADAPTER_VERSION = "protocol_semantics/1"

CONFIDENCE_EXACT = "exact"
CONFIDENCE_RECEIPT = "inferred_from_receipt"
CONFIDENCE_SNAPSHOT = "inferred_from_snapshot"
CONFIDENCE_GAP = "low_confidence_gap"


def event_topic(signature: str) -> str:
    return "0x" + keccak(text=signature).hex()


AAVE_SPARK_EVENT_SIGNATURES = {
    "Supply": "Supply(address,address,address,uint256,uint16)",
    "Withdraw": "Withdraw(address,address,address,uint256)",
    "Borrow": "Borrow(address,address,address,uint256,uint8,uint256,uint16)",
    "Repay": "Repay(address,address,address,uint256,bool)",
    "LiquidationCall": "LiquidationCall(address,address,address,uint256,uint256,address,bool)",
}

AAVE_SPARK_TOPICS = {
    event_topic(signature): name for name, signature in AAVE_SPARK_EVENT_SIGNATURES.items()
}

MORPHO_BLUE_EVENT_SIGNATURES = {
    "Supply": "Supply(bytes32,address,address,uint256,uint256)",
    "Withdraw": "Withdraw(bytes32,address,address,address,uint256,uint256)",
    "Borrow": "Borrow(bytes32,address,address,address,uint256,uint256)",
    "Repay": "Repay(bytes32,address,address,uint256,uint256)",
    "SupplyCollateral": "SupplyCollateral(bytes32,address,address,uint256)",
    "WithdrawCollateral": "WithdrawCollateral(bytes32,address,address,address,uint256)",
    "Liquidate": "Liquidate(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)",
}

MORPHO_BLUE_TOPICS = {
    event_topic(signature): name for name, signature in MORPHO_BLUE_EVENT_SIGNATURES.items()
}

ERC4626_EVENT_SIGNATURES = {
    "Deposit": "Deposit(address,address,uint256,uint256)",
    "Withdraw": "Withdraw(address,address,address,uint256,uint256)",
}

ERC4626_TOPICS = {
    event_topic(signature): name for name, signature in ERC4626_EVENT_SIGNATURES.items()
}

ERC4626_SELECTORS = {
    "asset": "0x38d52e0f",
    "totalAssets": "0x01e1d114",
    "convertToAssets": "0x07a2d13a",
    "totalSupply": "0x18160ddd",
    "decimals": "0x313ce567",
}

KNOWN_UNSUPPORTED_SIGNATURES = {
    "aave_spark": [
        "ReserveUsedAsCollateralEnabled(address,address)",
        "ReserveUsedAsCollateralDisabled(address,address)",
        "FlashLoan(address,address,address,uint256,uint8,uint256,uint16)",
        "IsolationModeTotalDebtUpdated(address,uint256)",
    ],
    "morpho_blue": [
        "CreateMarket(bytes32,(address,address,address,address,uint256))",
        "AccrueInterest(bytes32,uint256,uint256,uint256)",
        "FlashLoan(address,address,uint256)",
        "SetAuthorization(address,address,bool)",
    ],
    "erc4626": [
        "Transfer(address,address,uint256)",
    ],
}


def adapter_gap_catalog() -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    for adapter, signatures in KNOWN_UNSUPPORTED_SIGNATURES.items():
        out[adapter] = [
            {"signature": signature, "topic0": event_topic(signature)}
            for signature in signatures
        ]
    return out


def merge_outputs(*outputs: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    merged = {"events": [], "evidence": [], "gaps": []}
    for output in outputs:
        for key in merged:
            merged[key].extend(output.get(key, []))
    return merged


def parse_aave_spark_logs(
    logs: Iterable[dict[str, Any]],
    *,
    reserve_meta: dict[str, dict[str, Any]] | None = None,
    chain_id: int = 1,
    protocol: str = "aave_v3",
    source: str = "eth_getLogs",
) -> dict[str, list[dict[str, Any]]]:
    adapter = "spark-v3" if protocol.lower().startswith("spark") else "aave-v3"
    output = {"events": [], "evidence": [], "gaps": []}
    meta = _lower_keys(reserve_meta)
    for log in logs:
        event_name = _decoded_event_name(log) or AAVE_SPARK_TOPICS.get(_topic0(log))
        if event_name not in AAVE_SPARK_EVENT_SIGNATURES:
            output["gaps"].append(_unsupported_gap(log, adapter, chain_id, "unsupported_aave_spark_event_signature"))
            continue
        event = _parse_aave_spark_log(log, event_name, meta, chain_id, protocol, adapter, source)
        if event is None:
            output["gaps"].append(_unsupported_gap(log, adapter, chain_id, "malformed_aave_spark_event"))
            continue
        output["events"].append(event["event"])
        output["evidence"].append(event["evidence"])
    return output


def parse_aave_spark_api_rows(
    rows: Iterable[dict[str, Any]],
    *,
    reserve_meta: dict[str, dict[str, Any]] | None = None,
    chain_id: int = 1,
    protocol: str = "aave_v3",
    source: str = "protocol_api",
) -> dict[str, list[dict[str, Any]]]:
    adapter = "spark-v3" if protocol.lower().startswith("spark") else "aave-v3"
    output = {"events": [], "evidence": [], "gaps": []}
    meta = _lower_keys(reserve_meta)
    for row in rows:
        action = _row_action(row)
        if action not in {"Supply", "Withdraw", "Borrow", "Repay", "LiquidationCall"}:
            output["gaps"].append(_api_gap(row, adapter, chain_id, "unsupported_aave_spark_api_row"))
            continue
        event = _aave_api_row_to_event(row, action, meta, chain_id, protocol, adapter, source)
        if event is None:
            output["gaps"].append(_api_gap(row, adapter, chain_id, "malformed_aave_spark_api_row"))
            continue
        output["events"].append(event["event"])
        output["evidence"].append(event["evidence"])
    return output


def parse_morpho_blue_logs(
    logs: Iterable[dict[str, Any]],
    *,
    market_meta: dict[str, dict[str, Any]] | None = None,
    chain_id: int = 1,
    source: str = "eth_getLogs",
) -> dict[str, list[dict[str, Any]]]:
    adapter = "morpho-blue"
    output = {"events": [], "evidence": [], "gaps": []}
    meta = _lower_keys(market_meta)
    for log in logs:
        event_name = _decoded_event_name(log) or MORPHO_BLUE_TOPICS.get(_topic0(log))
        if event_name not in MORPHO_BLUE_EVENT_SIGNATURES:
            output["gaps"].append(_unsupported_gap(log, adapter, chain_id, "unsupported_morpho_blue_event_signature"))
            continue
        event = _parse_morpho_blue_log(log, event_name, meta, chain_id, source)
        if event is None:
            output["gaps"].append(_unsupported_gap(log, adapter, chain_id, "malformed_morpho_blue_event"))
            continue
        output["events"].append(event["event"])
        output["evidence"].append(event["evidence"])
        if event.get("gap"):
            output["gaps"].append(event["gap"])
    return output


def parse_morpho_api_rows(
    rows: Iterable[dict[str, Any]],
    *,
    market_meta: dict[str, dict[str, Any]] | None = None,
    chain_id: int = 1,
    source: str = "morpho_graphql",
) -> dict[str, list[dict[str, Any]]]:
    output = {"events": [], "evidence": [], "gaps": []}
    meta = _lower_keys(market_meta)
    for row in rows:
        row_output = _morpho_api_row_to_events(row, meta, chain_id, source)
        output["events"].extend(row_output["events"])
        output["evidence"].extend(row_output["evidence"])
        output["gaps"].extend(row_output["gaps"])
    return output


def parse_metamorpho_api_rows(
    rows: Iterable[dict[str, Any]],
    *,
    chain_id: int = 1,
    source: str = "morpho_graphql",
) -> dict[str, list[dict[str, Any]]]:
    output = {"events": [], "evidence": [], "gaps": []}
    for row in rows:
        event = _metamorpho_api_row_to_event(row, chain_id, source)
        if event is None:
            output["gaps"].append(_api_gap(row, "metamorpho", chain_id, "unsupported_metamorpho_api_row"))
            continue
        output["events"].append(event["event"])
        output["evidence"].append(event["evidence"])
    return output


def parse_erc4626_logs(
    logs: Iterable[dict[str, Any]],
    *,
    vault_meta: dict[str, Any] | None = None,
    chain_id: int = 1,
    source: str = "eth_getLogs",
) -> dict[str, list[dict[str, Any]]]:
    output = {"events": [], "evidence": [], "gaps": []}
    meta = vault_meta or {}
    for log in logs:
        event_name = _decoded_event_name(log) or ERC4626_TOPICS.get(_topic0(log))
        if event_name not in ERC4626_EVENT_SIGNATURES:
            output["gaps"].append(_unsupported_gap(log, "erc4626", chain_id, "unsupported_erc4626_event_signature"))
            continue
        event = _parse_erc4626_log(log, event_name, meta, chain_id, source)
        if event is None:
            output["gaps"].append(_unsupported_gap(log, "erc4626", chain_id, "malformed_erc4626_event"))
            continue
        output["events"].append(event["event"])
        output["evidence"].append(event["evidence"])
    return output


def read_erc4626_snapshot(
    vault: str,
    block: int,
    eth_call: Callable[[str, str, int], str | None],
    *,
    chain_id: int = 1,
    source: str = "eth_call",
) -> dict[str, list[dict[str, Any]]]:
    output = {"events": [], "evidence": [], "gaps": []}
    vault_addr = _norm_addr(vault)
    decimals_raw = eth_call(vault_addr, ERC4626_SELECTORS["decimals"], block)
    share_decimals = _hex_int(decimals_raw)
    if share_decimals is None or share_decimals > 36:
        share_decimals = 18
    share_unit = 10 ** share_decimals

    reads = {
        "asset": eth_call(vault_addr, ERC4626_SELECTORS["asset"], block),
        "totalAssets": eth_call(vault_addr, ERC4626_SELECTORS["totalAssets"], block),
        "totalSupply": eth_call(vault_addr, ERC4626_SELECTORS["totalSupply"], block),
        "convertToAssets": eth_call(
            vault_addr,
            ERC4626_SELECTORS["convertToAssets"] + _encode_uint(share_unit),
            block,
        ),
    }
    asset = _addr_from_return(reads["asset"])
    total_assets = _hex_int(reads["totalAssets"])
    total_supply = _hex_int(reads["totalSupply"])
    assets_per_share_unit = _hex_int(reads["convertToAssets"])

    missing = [name for name, value in reads.items() if not value or value == "0x"]
    if missing or not asset:
        output["gaps"].append({
            "kind": "needs_adapter",
            "adapter": "erc4626",
            "chainId": chain_id,
            "blockNumber": block,
            "contractAddress": vault_addr,
            "reason": "missing_erc4626_read",
            "missing": missing,
            "confidence": CONFIDENCE_GAP,
        })
        return output

    evidence_ids = []
    for function_name, raw_output in reads.items():
        ev = _evidence(
            adapter="erc4626",
            source=source,
            chain_id=chain_id,
            block_number=block,
            contract=vault_addr,
            event_name=function_name,
            function_signature=_erc4626_function_signature(function_name),
            confidence=CONFIDENCE_SNAPSHOT,
            extra={
                "rpcMethod": "eth_call",
                "callData": _erc4626_call_data(function_name, share_unit),
                "rawOutput": raw_output,
            },
        )
        evidence_ids.append(ev["id"])
        output["evidence"].append(ev)

    event = {
        "id": _record_id("sem", "erc4626", vault_addr, block, "snapshot"),
        "type": "vault_share",
        "semanticType": "vault_share",
        "protocol": "erc4626",
        "chainId": chain_id,
        "blockNumber": block,
        "vault": vault_addr,
        "shareToken": vault_addr,
        "assetToken": asset,
        "totalAssetsRaw": str(total_assets),
        "totalSupplyRaw": str(total_supply),
        "convertToAssetsInputRaw": str(share_unit),
        "convertToAssetsOutputRaw": str(assets_per_share_unit),
        "position": {
            "kind": "share_asset_relationship",
            "shareToken": vault_addr,
            "assetToken": asset,
        },
        "evidenceIds": evidence_ids,
    }
    output["events"].append(event)
    return output


def _parse_aave_spark_log(
    log: dict[str, Any],
    event_name: str,
    reserve_meta: dict[str, dict[str, Any]],
    chain_id: int,
    protocol: str,
    adapter: str,
    source: str,
) -> dict[str, dict[str, Any]] | None:
    args = _args(log)
    topics = _topics(log)
    words = _words(log.get("data"))
    block = _block_number(log)
    log_index = _log_index(log)
    tx_hash = _tx_hash(log)
    contract = _contract_address(log)
    signature = AAVE_SPARK_EVENT_SIGNATURES[event_name]

    if event_name == "Supply":
        reserve = _arg_addr(args, "reserve") or _topic_addr_at(topics, 1)
        user = _arg_addr(args, "user") or _word_addr_at(words, 0)
        on_behalf = _arg_addr(args, "onBehalfOf", "onBehalf") or _topic_addr_at(topics, 2)
        raw_amount = _arg_int(args, "amount") if args else _word_int_at(words, 1)
        referral = _arg_int(args, "referralCode") if args else _topic_int_at(topics, 3)
        semantic_type = "supply"
        position = _aave_receipt_position(reserve, reserve_meta, on_behalf)
        extra = {"user": user, "onBehalfOf": on_behalf, "referralCode": referral, "position": position}
    elif event_name == "Withdraw":
        reserve = _arg_addr(args, "reserve") or _topic_addr_at(topics, 1)
        user = _arg_addr(args, "user") or _topic_addr_at(topics, 2)
        to = _arg_addr(args, "to", "receiver") or _topic_addr_at(topics, 3)
        raw_amount = _arg_int(args, "amount") if args else _word_int_at(words, 0)
        semantic_type = "withdraw"
        position = _aave_receipt_position(reserve, reserve_meta, user)
        extra = {"user": user, "receiver": to, "position": position}
    elif event_name == "Borrow":
        reserve = _arg_addr(args, "reserve") or _topic_addr_at(topics, 1)
        user = _arg_addr(args, "user") or _word_addr_at(words, 0)
        on_behalf = _arg_addr(args, "onBehalfOf", "onBehalf") or _topic_addr_at(topics, 2)
        raw_amount = _arg_int(args, "amount") if args else _word_int_at(words, 1)
        mode = _arg_int(args, "interestRateMode") if args else _word_int_at(words, 2)
        borrow_rate = _arg_int(args, "borrowRate") if args else _word_int_at(words, 3)
        referral = _arg_int(args, "referralCode") if args else _topic_int_at(topics, 3)
        semantic_type = "borrow"
        position = _aave_debt_position(reserve, reserve_meta, on_behalf, mode)
        extra = {
            "receiver": user,
            "onBehalfOf": on_behalf,
            "interestRateMode": mode,
            "borrowRateRaw": str(borrow_rate) if borrow_rate is not None else None,
            "referralCode": referral,
            "position": position,
        }
    elif event_name == "Repay":
        reserve = _arg_addr(args, "reserve") or _topic_addr_at(topics, 1)
        user = _arg_addr(args, "user") or _topic_addr_at(topics, 2)
        repayer = _arg_addr(args, "repayer", "payer") or _topic_addr_at(topics, 3)
        raw_amount = _arg_int(args, "amount") if args else _word_int_at(words, 0)
        use_atokens = _arg_bool(args, "useATokens") if args else _word_bool_at(words, 1)
        semantic_type = "repay"
        position = _aave_debt_position(reserve, reserve_meta, user, None)
        extra = {"user": user, "repayer": repayer, "useATokens": use_atokens, "position": position}
    elif event_name == "LiquidationCall":
        reserve = _arg_addr(args, "debtAsset") or _topic_addr_at(topics, 2)
        collateral = _arg_addr(args, "collateralAsset") or _topic_addr_at(topics, 1)
        user = _arg_addr(args, "user") or _topic_addr_at(topics, 3)
        raw_amount = _arg_int(args, "debtToCover") if args else _word_int_at(words, 0)
        collateral_raw = _arg_int(args, "liquidatedCollateralAmount") if args else _word_int_at(words, 1)
        liquidator = _arg_addr(args, "liquidator") or _word_addr_at(words, 2)
        receive_atoken = _arg_bool(args, "receiveAToken") if args else _word_bool_at(words, 3)
        semantic_type = "liquidation"
        position = _aave_debt_position(reserve, reserve_meta, user, None)
        extra = {
            "user": user,
            "liquidator": liquidator,
            "collateralAsset": collateral,
            "collateralAmount": _amount(collateral, collateral_raw, reserve_meta),
            "receiveAToken": receive_atoken,
            "position": position,
        }
    else:
        return None

    if not reserve or raw_amount is None:
        return None
    token_amount = _amount(reserve, raw_amount, reserve_meta)
    evidence = _log_evidence(
        adapter=adapter,
        source=source,
        chain_id=chain_id,
        block_number=block,
        tx_hash=tx_hash,
        log_index=log_index,
        contract=contract,
        event_name=event_name,
        signature=signature,
        token_amount=token_amount,
        confidence=CONFIDENCE_RECEIPT,
        extra={
            "protocol": protocol,
            "decodedArgs": _jsonish(args) if args else None,
            "topics": topics,
        },
    )
    event = _semantic_event(
        adapter=adapter,
        protocol=protocol,
        semantic_type=semantic_type,
        chain_id=chain_id,
        block_number=block,
        tx_hash=tx_hash,
        log_index=log_index,
        contract=contract,
        token_amount=token_amount,
        evidence_id=evidence["id"],
        extra=extra,
    )
    return {"event": event, "evidence": evidence}


def _aave_api_row_to_event(
    row: dict[str, Any],
    action: str,
    reserve_meta: dict[str, dict[str, Any]],
    chain_id: int,
    protocol: str,
    adapter: str,
    source: str,
) -> dict[str, dict[str, Any]] | None:
    reserve = _norm_addr(_first(row, "reserve", "asset", "tokenAddress", "underlyingAsset"))
    raw_amount = _row_raw_amount(row)
    if not reserve or raw_amount is None:
        return None
    block = _parse_int(_first(row, "blockNumber", "block"))
    log_index = _parse_int(_first(row, "logIndex", "log_index"))
    tx_hash = _first(row, "txHash", "tx", "transactionHash")
    contract = _norm_addr(_first(row, "contractAddress", "pool", "poolAddress"))
    token_amount = _amount(reserve, raw_amount, reserve_meta)
    semantic_type = "liquidation" if action == "LiquidationCall" else action.lower()
    user = _norm_addr(_first(row, "user", "account", "owner"))
    on_behalf = _norm_addr(_first(row, "onBehalfOf", "onBehalf", "borrower")) or user
    mode = _parse_int(_first(row, "interestRateMode", "rateMode"))
    if semantic_type == "borrow":
        position = _aave_debt_position(reserve, reserve_meta, on_behalf, mode)
    elif semantic_type == "repay":
        position = _aave_debt_position(reserve, reserve_meta, user, mode)
    else:
        position = _aave_receipt_position(reserve, reserve_meta, on_behalf or user)
    evidence = _api_evidence(
        adapter=adapter,
        source=row.get("source") or source,
        chain_id=chain_id,
        block_number=block,
        tx_hash=tx_hash,
        log_index=log_index,
        contract=contract,
        event_name=action,
        token_amount=token_amount,
        confidence=CONFIDENCE_EXACT if tx_hash else CONFIDENCE_SNAPSHOT,
        row=row,
        extra={"protocol": protocol},
    )
    event = _semantic_event(
        adapter=adapter,
        protocol=protocol,
        semantic_type=semantic_type,
        chain_id=chain_id,
        block_number=block,
        tx_hash=tx_hash,
        log_index=log_index,
        contract=contract,
        token_amount=token_amount,
        evidence_id=evidence["id"],
        extra={
            "user": user,
            "receiver": _norm_addr(_first(row, "receiver", "to")),
            "repayer": _norm_addr(_first(row, "repayer", "payer")),
            "onBehalfOf": on_behalf,
            "position": position,
        },
    )
    return {"event": event, "evidence": evidence}


def _parse_morpho_blue_log(
    log: dict[str, Any],
    event_name: str,
    market_meta: dict[str, dict[str, Any]],
    chain_id: int,
    source: str,
) -> dict[str, dict[str, Any]] | None:
    args = _args(log)
    topics = _topics(log)
    words = _words(log.get("data"))
    block = _block_number(log)
    log_index = _log_index(log)
    tx_hash = _tx_hash(log)
    contract = _contract_address(log)
    signature = MORPHO_BLUE_EVENT_SIGNATURES[event_name]

    market_id = _lower_hex(_first(args, "id", "marketId", "marketUniqueKey")) if args else _topic_b32_at(topics, 1)
    market = market_meta.get((market_id or "").lower(), {})
    token_meta = _morpho_token_meta(market)
    gap = None
    if not market:
        gap = {
            "kind": "needs_adapter",
            "adapter": "morpho-blue",
            "chainId": chain_id,
            "blockNumber": block,
            "txHash": tx_hash,
            "logIndex": log_index,
            "contractAddress": contract,
            "marketId": market_id,
            "reason": "missing_morpho_market_metadata",
            "confidence": CONFIDENCE_GAP,
        }

    if event_name == "Supply":
        caller = _arg_addr(args, "caller") or _topic_addr_at(topics, 2)
        on_behalf = _arg_addr(args, "onBehalf", "onBehalfOf") or _topic_addr_at(topics, 3)
        raw_assets = _arg_int(args, "assets") if args else _word_int_at(words, 0)
        raw_shares = _arg_int(args, "shares") if args else _word_int_at(words, 1)
        semantic_type = "supply"
        token = _norm_addr(market.get("loanToken") or market.get("loanAsset"))
        extra = {"caller": caller, "onBehalfOf": on_behalf, "sharesRaw": str(raw_shares), "position": _morpho_position("supply_shares", market_id, on_behalf, raw_shares)}
    elif event_name == "Withdraw":
        caller = _arg_addr(args, "caller") or _word_addr_at(words, 0)
        on_behalf = _arg_addr(args, "onBehalf", "onBehalfOf") or _topic_addr_at(topics, 2)
        receiver = _arg_addr(args, "receiver") or _topic_addr_at(topics, 3)
        raw_assets = _arg_int(args, "assets") if args else _word_int_at(words, 1)
        raw_shares = _arg_int(args, "shares") if args else _word_int_at(words, 2)
        semantic_type = "withdraw"
        token = _norm_addr(market.get("loanToken") or market.get("loanAsset"))
        extra = {"caller": caller, "onBehalfOf": on_behalf, "receiver": receiver, "sharesRaw": str(raw_shares), "position": _morpho_position("supply_shares", market_id, on_behalf, raw_shares)}
    elif event_name == "Borrow":
        caller = _arg_addr(args, "caller") or _word_addr_at(words, 0)
        on_behalf = _arg_addr(args, "onBehalf", "onBehalfOf") or _topic_addr_at(topics, 2)
        receiver = _arg_addr(args, "receiver") or _topic_addr_at(topics, 3)
        raw_assets = _arg_int(args, "assets") if args else _word_int_at(words, 1)
        raw_shares = _arg_int(args, "shares") if args else _word_int_at(words, 2)
        semantic_type = "borrow"
        token = _norm_addr(market.get("loanToken") or market.get("loanAsset"))
        extra = {"caller": caller, "onBehalfOf": on_behalf, "receiver": receiver, "sharesRaw": str(raw_shares), "position": _morpho_position("borrow_shares", market_id, on_behalf, raw_shares)}
    elif event_name == "Repay":
        caller = _arg_addr(args, "caller") or _topic_addr_at(topics, 2)
        on_behalf = _arg_addr(args, "onBehalf", "onBehalfOf") or _topic_addr_at(topics, 3)
        raw_assets = _arg_int(args, "assets") if args else _word_int_at(words, 0)
        raw_shares = _arg_int(args, "shares") if args else _word_int_at(words, 1)
        semantic_type = "repay"
        token = _norm_addr(market.get("loanToken") or market.get("loanAsset"))
        extra = {"caller": caller, "onBehalfOf": on_behalf, "sharesRaw": str(raw_shares), "position": _morpho_position("borrow_shares", market_id, on_behalf, raw_shares)}
    elif event_name == "SupplyCollateral":
        caller = _arg_addr(args, "caller") or _topic_addr_at(topics, 2)
        on_behalf = _arg_addr(args, "onBehalf", "onBehalfOf") or _topic_addr_at(topics, 3)
        raw_assets = _arg_int(args, "assets") if args else _word_int_at(words, 0)
        semantic_type = "collateralize"
        token = _norm_addr(market.get("collateralToken") or market.get("collateralAsset"))
        extra = {"caller": caller, "onBehalfOf": on_behalf, "position": _morpho_position("collateral", market_id, on_behalf, raw_assets)}
    elif event_name == "WithdrawCollateral":
        caller = _arg_addr(args, "caller") or _word_addr_at(words, 0)
        on_behalf = _arg_addr(args, "onBehalf", "onBehalfOf") or _topic_addr_at(topics, 2)
        receiver = _arg_addr(args, "receiver") or _topic_addr_at(topics, 3)
        raw_assets = _arg_int(args, "assets") if args else _word_int_at(words, 1)
        semantic_type = "withdraw"
        token = _norm_addr(market.get("collateralToken") or market.get("collateralAsset"))
        extra = {"caller": caller, "onBehalfOf": on_behalf, "receiver": receiver, "position": _morpho_position("collateral", market_id, on_behalf, raw_assets)}
    elif event_name == "Liquidate":
        caller = _arg_addr(args, "caller") or _topic_addr_at(topics, 2)
        borrower = _arg_addr(args, "borrower") or _topic_addr_at(topics, 3)
        raw_assets = _arg_int(args, "repaidAssets") if args else _word_int_at(words, 0)
        repaid_shares = _arg_int(args, "repaidShares") if args else _word_int_at(words, 1)
        seized_assets = _arg_int(args, "seizedAssets") if args else _word_int_at(words, 2)
        bad_debt_assets = _arg_int(args, "badDebtAssets") if args else _word_int_at(words, 3)
        bad_debt_shares = _arg_int(args, "badDebtShares") if args else _word_int_at(words, 4)
        semantic_type = "liquidation"
        token = _norm_addr(market.get("loanToken") or market.get("loanAsset"))
        collateral_token = _norm_addr(market.get("collateralToken") or market.get("collateralAsset"))
        extra = {
            "caller": caller,
            "user": borrower,
            "onBehalfOf": borrower,
            "repaidSharesRaw": str(repaid_shares),
            "seizedCollateral": _amount(collateral_token, seized_assets, token_meta) if collateral_token else {"rawAmount": str(seized_assets)},
            "badDebtAssetsRaw": str(bad_debt_assets),
            "badDebtSharesRaw": str(bad_debt_shares),
            "position": _morpho_position("borrow_shares", market_id, borrower, repaid_shares),
        }
    else:
        return None

    if not market_id or raw_assets is None:
        return None
    token_amount = _amount(token, raw_assets, token_meta) if token else {"rawAmount": str(raw_assets)}
    evidence = _log_evidence(
        adapter="morpho-blue",
        source=source,
        chain_id=chain_id,
        block_number=block,
        tx_hash=tx_hash,
        log_index=log_index,
        contract=contract,
        event_name=event_name,
        signature=signature,
        token_amount=token_amount,
        confidence=CONFIDENCE_RECEIPT,
        extra={
            "marketId": market_id,
            "decodedArgs": _jsonish(args) if args else None,
            "topics": topics,
        },
    )
    event = _semantic_event(
        adapter="morpho-blue",
        protocol="morpho_blue",
        semantic_type=semantic_type,
        chain_id=chain_id,
        block_number=block,
        tx_hash=tx_hash,
        log_index=log_index,
        contract=contract,
        token_amount=token_amount,
        evidence_id=evidence["id"],
        extra={"marketId": market_id, **extra},
    )
    return {"event": event, "evidence": evidence, "gap": gap}


def _morpho_api_row_to_events(
    row: dict[str, Any],
    market_meta: dict[str, dict[str, Any]],
    chain_id: int,
    source: str,
) -> dict[str, list[dict[str, Any]]]:
    output = {"events": [], "evidence": [], "gaps": []}
    market_id = _lower_hex(_first(row, "marketId", "marketUniqueKey", "id"))
    user = _extract_user(row)
    block = _parse_int(_first(row, "blockNumber", "block"))
    market = market_meta.get((market_id or "").lower(), {})
    if not market_id or not user:
        output["gaps"].append(_api_gap(row, "morpho-blue", chain_id, "malformed_morpho_api_row"))
        return output
    if not market:
        output["gaps"].append({
            "kind": "needs_adapter",
            "adapter": "morpho-blue",
            "chainId": chain_id,
            "blockNumber": block,
            "marketId": market_id,
            "reason": "missing_morpho_market_metadata",
            "confidence": CONFIDENCE_GAP,
        })
    token_meta = _morpho_token_meta(market)

    specs = [
        ("supply", "supplyAssets", "supplyShares", "loanToken", "supply_shares"),
        ("borrow", "borrowAssets", "borrowShares", "loanToken", "borrow_shares"),
        ("collateralize", "collateral", "collateral", "collateralToken", "collateral"),
    ]
    for semantic_type, amount_key, shares_key, token_key, position_kind in specs:
        raw_assets = _row_raw_amount(row, amount_key)
        raw_shares = _parse_int(_first(row, shares_key))
        if not raw_assets and not raw_shares:
            continue
        token = _norm_addr(market.get(token_key) or market.get(token_key.replace("Token", "Asset")))
        token_amount = _amount(token, raw_assets or 0, token_meta) if token else {"rawAmount": str(raw_assets or 0)}
        evidence = _api_evidence(
            adapter="morpho-blue",
            source=row.get("source") or source,
            chain_id=chain_id,
            block_number=block,
            tx_hash=_first(row, "txHash", "tx", "transactionHash"),
            log_index=_parse_int(_first(row, "logIndex", "log_index")),
            contract=_norm_addr(_first(row, "contractAddress", "morpho")),
            event_name=f"{semantic_type}_snapshot",
            token_amount=token_amount,
            confidence=CONFIDENCE_SNAPSHOT,
            row=row,
            extra={"marketId": market_id},
        )
        event = _semantic_event(
            adapter="morpho-blue",
            protocol="morpho_blue",
            semantic_type=semantic_type,
            chain_id=chain_id,
            block_number=block,
            tx_hash=_first(row, "txHash", "tx", "transactionHash"),
            log_index=_parse_int(_first(row, "logIndex", "log_index")),
            contract=_norm_addr(_first(row, "contractAddress", "morpho")),
            token_amount=token_amount,
            evidence_id=evidence["id"],
            extra={
                "marketId": market_id,
                "onBehalfOf": user,
                "user": user,
                "sharesRaw": str(raw_shares) if raw_shares is not None else None,
                "position": _morpho_position(position_kind, market_id, user, raw_shares or raw_assets),
            },
        )
        output["events"].append(event)
        output["evidence"].append(evidence)
    if not output["events"]:
        output["gaps"].append(_api_gap(row, "morpho-blue", chain_id, "empty_morpho_position_row"))
    return output


def _metamorpho_api_row_to_event(
    row: dict[str, Any],
    chain_id: int,
    source: str,
) -> dict[str, dict[str, Any]] | None:
    vault = _norm_addr(_first(row, ("vault", "address"), "vaultAddress", "vault"))
    market_id = _lower_hex(_first(row, "marketId", "marketUniqueKey", ("market", "uniqueKey"), ("market", "id")))
    raw_assets = _row_raw_amount(row, "supplyAssets", "assets", "allocationAssets")
    if not vault or not market_id or raw_assets is None:
        return None
    block = _parse_int(_first(row, "blockNumber", "block"))
    token = _norm_addr(_first(row, "loanToken", ("market", "loanAsset", "address"), ("market", "loanAssetAddress")))
    token_amount = {"tokenAddress": token, "rawAmount": str(raw_assets)}
    evidence = _api_evidence(
        adapter="metamorpho",
        source=row.get("source") or source,
        chain_id=chain_id,
        block_number=block,
        tx_hash=_first(row, "txHash", "tx", "transactionHash"),
        log_index=_parse_int(_first(row, "logIndex", "log_index")),
        contract=vault,
        event_name="vault_allocation_snapshot",
        token_amount=token_amount,
        confidence=CONFIDENCE_SNAPSHOT,
        row=row,
        extra={"marketId": market_id},
    )
    event = _semantic_event(
        adapter="metamorpho",
        protocol="metamorpho",
        semantic_type="supply",
        chain_id=chain_id,
        block_number=block,
        tx_hash=_first(row, "txHash", "tx", "transactionHash"),
        log_index=_parse_int(_first(row, "logIndex", "log_index")),
        contract=vault,
        token_amount=token_amount,
        evidence_id=evidence["id"],
        extra={
            "actor": vault,
            "onBehalfOf": vault,
            "marketId": market_id,
            "position": {
                "kind": "vault_allocation",
                "vault": vault,
                "marketId": market_id,
            },
        },
    )
    return {"event": event, "evidence": evidence}


def _parse_erc4626_log(
    log: dict[str, Any],
    event_name: str,
    vault_meta: dict[str, Any],
    chain_id: int,
    source: str,
) -> dict[str, dict[str, Any]] | None:
    args = _args(log)
    topics = _topics(log)
    words = _words(log.get("data"))
    block = _block_number(log)
    log_index = _log_index(log)
    tx_hash = _tx_hash(log)
    vault = _contract_address(log)
    asset = _norm_addr(vault_meta.get("asset") or vault_meta.get("assetToken"))
    decimals = _parse_int(vault_meta.get("assetDecimals") or vault_meta.get("decimals"))
    token_meta = {asset: {"decimals": decimals, "symbol": vault_meta.get("assetSymbol")}} if asset else {}

    if event_name == "Deposit":
        sender = _arg_addr(args, "sender") or _topic_addr_at(topics, 1)
        owner = _arg_addr(args, "owner") or _topic_addr_at(topics, 2)
        raw_assets = _arg_int(args, "assets") if args else _word_int_at(words, 0)
        raw_shares = _arg_int(args, "shares") if args else _word_int_at(words, 1)
        semantic_type = "vault_share"
        extra = {"sender": sender, "owner": owner, "sharesRaw": str(raw_shares), "position": _erc4626_position(vault, asset, owner, raw_shares)}
    elif event_name == "Withdraw":
        sender = _arg_addr(args, "sender") or _topic_addr_at(topics, 1)
        receiver = _arg_addr(args, "receiver") or _topic_addr_at(topics, 2)
        owner = _arg_addr(args, "owner") or _topic_addr_at(topics, 3)
        raw_assets = _arg_int(args, "assets") if args else _word_int_at(words, 0)
        raw_shares = _arg_int(args, "shares") if args else _word_int_at(words, 1)
        semantic_type = "redeem"
        extra = {"sender": sender, "receiver": receiver, "owner": owner, "sharesRaw": str(raw_shares), "position": _erc4626_position(vault, asset, owner, raw_shares)}
    else:
        return None
    if raw_assets is None:
        return None
    token_amount = _amount(asset, raw_assets, token_meta) if asset else {"rawAmount": str(raw_assets)}
    evidence = _log_evidence(
        adapter="erc4626",
        source=source,
        chain_id=chain_id,
        block_number=block,
        tx_hash=tx_hash,
        log_index=log_index,
        contract=vault,
        event_name=event_name,
        signature=ERC4626_EVENT_SIGNATURES[event_name],
        token_amount=token_amount,
        confidence=CONFIDENCE_RECEIPT,
        extra={
            "vault": vault,
            "assetToken": asset,
            "decodedArgs": _jsonish(args) if args else None,
            "topics": topics,
        },
    )
    event = _semantic_event(
        adapter="erc4626",
        protocol="erc4626",
        semantic_type=semantic_type,
        chain_id=chain_id,
        block_number=block,
        tx_hash=tx_hash,
        log_index=log_index,
        contract=vault,
        token_amount=token_amount,
        evidence_id=evidence["id"],
        extra={"vault": vault, "assetToken": asset, **extra},
    )
    return {"event": event, "evidence": evidence}


def _semantic_event(
    *,
    adapter: str,
    protocol: str,
    semantic_type: str,
    chain_id: int,
    block_number: int | None,
    tx_hash: str | None,
    log_index: int | None,
    contract: str | None,
    token_amount: dict[str, Any],
    evidence_id: str,
    extra: dict[str, Any],
) -> dict[str, Any]:
    event = {
        "id": _record_id("sem", adapter, semantic_type, tx_hash, log_index, block_number, contract, extra),
        "type": semantic_type,
        "semanticType": semantic_type,
        "protocol": protocol,
        "adapter": adapter,
        "adapterVersion": ADAPTER_VERSION,
        "chainId": chain_id,
        "blockNumber": block_number,
        "txHash": tx_hash,
        "logIndex": log_index,
        "contractAddress": contract,
        "token": token_amount,
        "evidenceIds": [evidence_id],
    }
    event.update({k: v for k, v in extra.items() if v is not None})
    return event


def _log_evidence(
    *,
    adapter: str,
    source: str,
    chain_id: int,
    block_number: int | None,
    tx_hash: str | None,
    log_index: int | None,
    contract: str | None,
    event_name: str,
    signature: str,
    token_amount: dict[str, Any],
    confidence: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _evidence(
        adapter=adapter,
        source=source,
        chain_id=chain_id,
        block_number=block_number,
        tx_hash=tx_hash,
        log_index=log_index,
        contract=contract,
        event_name=event_name,
        function_signature=signature,
        token_amount=token_amount,
        confidence=confidence,
        extra=extra,
    )


def _api_evidence(
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
    row: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = {"apiRow": _jsonish(row)}
    if extra:
        merged.update(extra)
    return _evidence(
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
        extra=merged,
    )


def _evidence(
    *,
    adapter: str,
    source: str,
    chain_id: int,
    block_number: int | None,
    tx_hash: str | None = None,
    log_index: int | None = None,
    contract: str | None = None,
    event_name: str | None = None,
    function_signature: str | None = None,
    token_amount: dict[str, Any] | None = None,
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
        "functionSignature": function_signature,
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
    }
    if tx_hash:
        evidence["txHash"] = tx_hash
    if log_index is not None:
        evidence["logIndex"] = log_index
    if contract:
        evidence["contractAddress"] = contract
    if event_name:
        evidence["eventName"] = event_name
    if function_signature:
        evidence["functionSignature"] = function_signature
    if token_amount:
        evidence.update(_flatten_amount(token_amount))
        evidence["token"] = token_amount
    if extra:
        for key, value in extra.items():
            if value is not None:
                evidence[key] = value
    return evidence


def _aave_receipt_position(
    reserve: str | None,
    reserve_meta: dict[str, dict[str, Any]],
    owner: str | None,
) -> dict[str, Any]:
    meta = reserve_meta.get((reserve or "").lower(), {})
    receipt = _norm_addr(_first(meta, "aTokenAddress", "aToken", "receiptToken"))
    return {
        "kind": "receipt_token",
        "protocol": "aave_v3",
        "owner": owner,
        "underlyingToken": reserve,
        "receiptToken": receipt,
        "tokenStandard": "aToken" if receipt else None,
    }


def _aave_debt_position(
    reserve: str | None,
    reserve_meta: dict[str, dict[str, Any]],
    owner: str | None,
    mode: int | None,
) -> dict[str, Any]:
    meta = reserve_meta.get((reserve or "").lower(), {})
    if mode == 1:
        debt = _norm_addr(_first(meta, "stableDebtTokenAddress", "stableDebtToken"))
        debt_kind = "stable_debt_token"
    else:
        debt = _norm_addr(_first(meta, "variableDebtTokenAddress", "variableDebtToken", "debtToken"))
        debt_kind = "variable_debt_token"
    return {
        "kind": "debt_position",
        "protocol": "aave_v3",
        "owner": owner,
        "underlyingToken": reserve,
        "debtToken": debt,
        "debtTokenKind": debt_kind,
    }


def _morpho_position(kind: str, market_id: str | None, owner: str | None, raw_value: int | None) -> dict[str, Any]:
    return {
        "kind": kind,
        "protocol": "morpho_blue",
        "marketId": market_id,
        "owner": owner,
        "rawValue": str(raw_value) if raw_value is not None else None,
    }


def _morpho_token_meta(market: dict[str, Any]) -> dict[str, dict[str, Any]]:
    loan = _norm_addr(_first(market, "loanToken", "loanAsset", "loanAssetAddress", ("loanAsset", "address")))
    collateral = _norm_addr(_first(
        market,
        "collateralToken",
        "collateralAsset",
        "collateralAssetAddress",
        ("collateralAsset", "address"),
    ))
    out: dict[str, dict[str, Any]] = {}
    if loan:
        out[loan] = {
            "symbol": _first(market, "loanSymbol", "loanAssetSymbol", ("loanAsset", "symbol"))
            or (market.get("symbol") if not collateral else None),
            "decimals": _first(market, "loanDecimals", "loanAssetDecimals", ("loanAsset", "decimals"))
            or (market.get("decimals") if not collateral else None),
        }
    if collateral:
        out[collateral] = {
            "symbol": _first(market, "collateralSymbol", "collateralAssetSymbol", ("collateralAsset", "symbol"))
            or (market.get("symbol") if not loan else None),
            "decimals": _first(
                market,
                "collateralDecimals",
                "collateralAssetDecimals",
                ("collateralAsset", "decimals"),
            )
            or (market.get("decimals") if not loan else None),
        }
    return out


def _erc4626_position(vault: str | None, asset: str | None, owner: str | None, raw_shares: int | None) -> dict[str, Any]:
    return {
        "kind": "share_asset_relationship",
        "protocol": "erc4626",
        "vault": vault,
        "shareToken": vault,
        "assetToken": asset,
        "owner": owner,
        "sharesRaw": str(raw_shares) if raw_shares is not None else None,
    }


def _amount(token: str | None, raw_amount: int | str | None, token_meta: dict[str, dict[str, Any]]) -> dict[str, Any]:
    raw = _parse_int(raw_amount)
    out: dict[str, Any] = {"tokenAddress": _norm_addr(token), "rawAmount": str(raw) if raw is not None else None}
    meta = token_meta.get((_norm_addr(token) or "").lower(), {})
    decimals = _parse_int(meta.get("decimals"))
    if decimals is not None:
        out["decimals"] = decimals
        if raw is not None:
            out["amount"] = raw / (10 ** decimals)
    symbol = meta.get("symbol") or meta.get("underlyingSymbol")
    if symbol:
        out["symbol"] = symbol
    usd = _parse_float(meta.get("usd") or meta.get("priceUsd"))
    if usd is not None and out.get("amount") is not None:
        out["usdValue"] = out["amount"] * usd
    return out


def _flatten_amount(token_amount: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "tokenAddress": "tokenAddress",
        "symbol": "symbol",
        "decimals": "decimals",
        "rawAmount": "rawAmount",
        "amount": "amount",
        "usdValue": "usdValue",
    }
    return {dst: token_amount[src] for src, dst in mapping.items() if src in token_amount and token_amount[src] is not None}


def _unsupported_gap(log: dict[str, Any], adapter: str, chain_id: int, reason: str) -> dict[str, Any]:
    return {
        "kind": "needs_adapter",
        "adapter": adapter,
        "chainId": chain_id,
        "blockNumber": _block_number(log),
        "txHash": _tx_hash(log),
        "logIndex": _log_index(log),
        "contractAddress": _contract_address(log),
        "topic0": _topic0(log),
        "eventName": _decoded_event_name(log),
        "reason": reason,
        "confidence": CONFIDENCE_GAP,
    }


def _api_gap(row: dict[str, Any], adapter: str, chain_id: int, reason: str) -> dict[str, Any]:
    return {
        "kind": "needs_adapter",
        "adapter": adapter,
        "chainId": chain_id,
        "blockNumber": _parse_int(_first(row, "blockNumber", "block")),
        "txHash": _first(row, "txHash", "tx", "transactionHash"),
        "contractAddress": _norm_addr(_first(row, "contractAddress", "pool", "vault", "morpho")),
        "eventName": _row_action(row),
        "reason": reason,
        "confidence": CONFIDENCE_GAP,
        "apiRow": _jsonish(row),
    }


def _row_action(row: dict[str, Any]) -> str:
    value = _first(row, "eventName", "event", "action", "kind", "type")
    if not isinstance(value, str):
        return ""
    clean = value.replace("_", "").replace("-", "").lower()
    aliases = {
        "supply": "Supply",
        "deposit": "Supply",
        "withdraw": "Withdraw",
        "borrow": "Borrow",
        "repay": "Repay",
        "liquidation": "LiquidationCall",
        "liquidationcall": "LiquidationCall",
    }
    return aliases.get(clean, value)


def _row_raw_amount(row: dict[str, Any], *preferred_keys: str) -> int | None:
    keys = preferred_keys or ("rawAmount", "amountRaw", "amount", "assets", "assetsRaw")
    for key in keys:
        value = _first(row, key)
        parsed = _parse_int(value)
        if parsed is not None:
            return parsed
    return None


def _extract_user(row: dict[str, Any]) -> str | None:
    return _norm_addr(_first(row, ("user", "address"), "account", "owner", "onBehalf", "onBehalfOf", "user"))


def _topic0(log: dict[str, Any]) -> str | None:
    topics = _topics(log)
    if topics:
        return _lower_hex(topics[0])
    return _lower_hex(log.get("topic0"))


def _topics(log: dict[str, Any]) -> list[str]:
    topics = log.get("topics") or []
    if isinstance(topics, str):
        return [topics.lower()]
    return [_lower_hex(t) for t in topics if isinstance(t, str)]


def _words(data: Any) -> list[str]:
    if not isinstance(data, str) or not data or data == "0x":
        return []
    s = data[2:] if data.startswith("0x") else data
    return ["0x" + s[i:i + 64] for i in range(0, len(s), 64) if s[i:i + 64]]


def _topic_addr_at(topics: list[str], index: int) -> str | None:
    if len(topics) <= index:
        return None
    return _word_addr(topics[index])


def _topic_b32_at(topics: list[str], index: int) -> str | None:
    if len(topics) <= index:
        return None
    return _lower_hex(topics[index])


def _topic_int_at(topics: list[str], index: int) -> int | None:
    if len(topics) <= index:
        return None
    return _parse_int(topics[index])


def _word_addr_at(words: list[str], index: int) -> str | None:
    if len(words) <= index:
        return None
    return _word_addr(words[index])


def _word_int_at(words: list[str], index: int) -> int | None:
    if len(words) <= index:
        return None
    return _parse_int(words[index])


def _word_bool_at(words: list[str], index: int) -> bool | None:
    value = _word_int_at(words, index)
    if value is None:
        return None
    return bool(value)


def _word_addr(word: str | None) -> str | None:
    if not isinstance(word, str):
        return None
    clean = word[2:] if word.startswith("0x") else word
    if len(clean) < 40:
        return None
    return _norm_addr("0x" + clean[-40:])


def _addr_from_return(value: str | None) -> str | None:
    return _word_addr(value)


def _arg_addr(args: dict[str, Any], *names: str) -> str | None:
    return _norm_addr(_first(args, *names))


def _arg_int(args: dict[str, Any], *names: str) -> int | None:
    return _parse_int(_first(args, *names))


def _arg_bool(args: dict[str, Any], *names: str) -> bool | None:
    value = _first(args, *names)
    if isinstance(value, bool):
        return value
    parsed = _parse_int(value)
    if parsed is None:
        return None
    return bool(parsed)


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


def _lower_keys(mapping: dict[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    if not mapping:
        return {}
    return {str(k).lower(): v for k, v in mapping.items() if isinstance(v, dict)}


def _lower_hex(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.lower()


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


def _hex_int(value: str | None) -> int | None:
    return _parse_int(value)


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _encode_uint(value: int) -> str:
    return f"{int(value):064x}"


def _erc4626_function_signature(function_name: str) -> str:
    if function_name == "convertToAssets":
        return "convertToAssets(uint256)"
    return f"{function_name}()"


def _erc4626_call_data(function_name: str, share_unit: int) -> str:
    selector = ERC4626_SELECTORS[function_name]
    if function_name == "convertToAssets":
        return selector + _encode_uint(share_unit)
    return selector
