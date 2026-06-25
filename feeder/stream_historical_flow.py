#!/usr/bin/env python3
"""Build a proof-backed Stream/xUSD historical flow artifact.

This intentionally uses onchain-indexed transfer rows only:
  - actor scan: Etherscan tokentx(address=<actor>)
  - token scan: Etherscan tokentx(contractaddress=<xUSD>)

Do not add article/report relationships here. If Elixir/deUSD appears, it must
appear because deUSD/sdeUSD contracts emitted Transfer events in the selected
block range.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError
from collections import defaultdict
from pathlib import Path
from typing import Any

from protocol_semantics import MORPHO_BLUE_TOPICS, parse_morpho_blue_logs

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "feeder" / "cache" / "stream_historical"
ENV = Path("/Users/link/podotree/.env")
ZERO = "0x0000000000000000000000000000000000000000"
ETHERSCAN = "https://api.etherscan.io/v2/api"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
MORPHO_BLUE = "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb"
MORPHO_GQL_ENDPOINTS = (
    "https://api.morpho.org/graphql",
    "https://blue-api.morpho.org/graphql",
)

TOKENS = {
    "xUSD": "0xe2fc85bfb48c4cf147921fbe110cf92ef9f26f94",
    "deUSD": "0x15700b564ca08d9439c58ca5053166e8317aa138",
    "sdeUSD": "0x5c5b196abe0d54485975d1ec29617d42d9198326",
    "USDC": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    "USDT": "0xdac17f958d2ee523a2206206994597c13d831ec7",
}

KNOWN_LABELS = {
    ZERO: "Mint / Burn",
    "0xcb4a7b790edb7fa3e2731efd7ed85275f92fc74a": "deUSD/sdeUSD observed actor",
    "0x1597e4b7cf6d2877a1d690b6088668afdb045763": "Stream/deUSD observed actor",
    "0x33a47b816cf4fc6698b4cf1b876da9783b18b325": "Stream/deUSD routing actor",
    "0x25e028a45a6012763a76145d7ceea3587015e990": "deUSD mint receiver",
    "0x69088d25a635d22dcbe7c4a5c7707b9cc64bd114": "Elixir mint/redeem proxy",
    "0x738744237b7fd97af670d9ddf54390c24263cea8": "Elixir Safe actor",
    "0x14bcd9da052cdc6fe0b9446d5a616d5b7b4d4550": "xUSD owner Safe",
    "0xd7cdbde6c9da34fcb2917390b491193b54c24f24": "deUSD/sdeUSD owner Safe",
    "0x5f6c431ac417f0f430b84a666a563fabe681da94": "Curve deUSD/USDC",
    "0x2c7a1b4950fe369e79fb3471284d4a4e66fbea76": "Curve sdeUSD/deUSD",
    "0x9008d19f58aabd9ed0d60971565aa8510560ab41": "CoW Protocol GPv2Settlement",
    "0x111111125421ca6dc452d289314280a0f8842a65": "1inch AggregationRouterV6",
    "0x000000000004444c5dc75cb358380d2e3de08a90": "Uniswap V4 PoolManager",
    "0x66a9893cc07d91d95644aedd05d03f95e1dba8af": "Uniswap Universal Router",
    "0xba12222222228d8ba445958a75a0704d566bf2c8": "Balancer Vault",
    "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2": "Aave V3 Pool",
    MORPHO_BLUE: "Morpho Blue",
    "0x6566194141eefa99af43bb5aa71460ca2dc90245": "Morpho Bundler3",
    "0x3a23f943181408eac424116af7b7790c94cb97a5": "SocketGateway",
    "0x4a6c312ec70e8747a587ee860a0353cd42be0ae0": "EthereumGeneralAdapter1",
    "0x6eaf19b2fc24552925db245f9ff613157a7dbb4c": "StableWrapper",
}

ROUTER_OR_SOLVER = {
    "0x9008d19f58aabd9ed0d60971565aa8510560ab41",
    "0x111111125421ca6dc452d289314280a0f8842a65",
    "0x000000000004444c5dc75cb358380d2e3de08a90",
    "0x66a9893cc07d91d95644aedd05d03f95e1dba8af",
    "0xba12222222228d8ba445958a75a0704d566bf2c8",
    "0x3a23f943181408eac424116af7b7790c94cb97a5",
    "0x4a6c312ec70e8747a587ee860a0353cd42be0ae0",
}
LENDING_PROTOCOLS = {
    "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2",
    MORPHO_BLUE,
}
BUNDLER_PROTOCOLS = {
    "0x6566194141eefa99af43bb5aa71460ca2dc90245",
}
VAULT_PROTOCOLS = {
    "0x6eaf19b2fc24552925db245f9ff613157a7dbb4c",
}

DEFAULT_ACTORS = [
    "0x1597e4b7cf6d2877a1d690b6088668afdb045763",
    "0xcb4a7b790edb7fa3e2731efd7ed85275f92fc74a",
    "0x33a47b816cf4fc6698b4cf1b876da9783b18b325",
    "0x25e028a45a6012763a76145d7ceea3587015e990",
    "0x69088d25a635d22dcbe7c4a5c7707b9cc64bd114",
    "0x738744237b7fd97af670d9ddf54390c24263cea8",
]

TOKEN_META = {
    address.lower(): {"symbol": symbol, "decimals": 6 if symbol in {"xUSD", "USDC", "USDT"} else 18}
    for symbol, address in TOKENS.items()
}

DEFAULT_SCAN_TOKENS = ["xUSD", "deUSD", "sdeUSD"]
CORE_ADDRESSES = {
    "0x1597e4b7cf6d2877a1d690b6088668afdb045763",
    "0xcb4a7b790edb7fa3e2731efd7ed85275f92fc74a",
    "0x33a47b816cf4fc6698b4cf1b876da9783b18b325",
    "0x25e028a45a6012763a76145d7ceea3587015e990",
    "0x69088d25a635d22dcbe7c4a5c7707b9cc64bd114",
    "0x738744237b7fd97af670d9ddf54390c24263cea8",
    "0x14bcd9da052cdc6fe0b9446d5a616d5b7b4d4550",
    "0xe2fc85bfb48c4cf147921fbe110cf92ef9f26f94",
}

PINNED_POOL_ADDRESSES = {
    "0x5f6c431ac417f0f430b84a666a563fabe681da94",
    "0x2c7a1b4950fe369e79fb3471284d4a4e66fbea76",
}
STREAM_CONTROLLED_SURFACES = {
    "0x14bcd9da052cdc6fe0b9446d5a616d5b7b4d4550",
    "0x33a47b816cf4fc6698b4cf1b876da9783b18b325",
    TOKENS["xUSD"].lower(),
}
STABLE_TOKENS = {
    TOKENS["USDC"].lower(),
    TOKENS["USDT"].lower(),
}
STREAM_XUSD_MINT_SURFACE = "semantic:stream-xusd-minting-surface"
STREAM_OBSERVED_CLUSTER = "semantic:stream-observed-actors"
ELIXIR_OBSERVED_CLUSTER = "semantic:elixir-observed-actors"
MORPHO_TOKEN_MARKETS = "semantic:morpho-token-markets"
MORPHO_POSITION_GROUP_PREFIX = "semantic:morpho-position-group"
STREAM_RELATED_ACTORS = {
    "0x1597e4b7cf6d2877a1d690b6088668afdb045763",
    "0xcb4a7b790edb7fa3e2731efd7ed85275f92fc74a",
    "0x33a47b816cf4fc6698b4cf1b876da9783b18b325",
    "0x25e028a45a6012763a76145d7ceea3587015e990",
}
ELIXIR_RELATED_ACTORS = {
    "0x69088d25a635d22dcbe7c4a5c7707b9cc64bd114",
    "0x738744237b7fd97af670d9ddf54390c24263cea8",
}
VISIBLE_MORPHO_POSITION_USERS = CORE_ADDRESSES | STREAM_RELATED_ACTORS | ELIXIR_RELATED_ACTORS
TOKEN_MARKET_ASSETS = {
    TOKENS["xUSD"].lower(),
    TOKENS["deUSD"].lower(),
    TOKENS["sdeUSD"].lower(),
}


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV.exists():
        return out
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def cache_path(key: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / (hashlib.sha256(key.encode()).hexdigest() + ".json")


def cached_get(key: str) -> Any | None:
    path = cache_path(key)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def cached_put(key: str, value: Any) -> None:
    cache_path(key).write_text(json.dumps(value), encoding="utf-8")


def rpc(method: str, params: list[Any], rpc_url: str) -> Any:
    key = "rpc:" + method + ":" + json.dumps(params, sort_keys=True)
    cached = cached_get(key)
    if cached is not None:
        return cached
    request = urllib.request.Request(
        rpc_url,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers={"content-type": "application/json"},
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = json.loads(response.read().decode())
            break
        except HTTPError as error:
            if error.code != 429 or attempt == 4:
                raise
            time.sleep(1.5 * (attempt + 1))
    if "error" in body:
        raise RuntimeError(f"{method} failed: {body['error']}")
    cached_put(key, body.get("result"))
    return body.get("result")


def gql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    key = "morpho_gql:" + json.dumps({"query": query, "variables": variables}, sort_keys=True)
    cached = cached_get(key)
    if cached is not None:
        return cached
    last_error: Exception | None = None
    payload = json.dumps({"query": query, "variables": variables}).encode()
    for endpoint in MORPHO_GQL_ENDPOINTS:
        request = urllib.request.Request(endpoint, data=payload, headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = json.loads(response.read().decode())
            if body.get("errors"):
                last_error = RuntimeError(f"Morpho GraphQL errors: {body['errors']}")
                continue
            cached_put(key, body)
            return body
        except Exception as error:  # noqa: BLE001 - fallback endpoint should see transport/schema failures.
            last_error = error
    raise RuntimeError(f"Morpho GraphQL failed: {last_error}")


def morpho_market_by_id(market_id: str) -> dict[str, Any] | None:
    query = """
    query MarketById($marketId: String!, $chainId: Int!) {
      marketById(marketId: $marketId, chainId: $chainId) {
        marketId
        lltv
        irmAddress
        oracle { address }
        loanAsset { address symbol decimals }
        collateralAsset { address symbol decimals }
        state {
          supplyAssets
          supplyAssetsUsd
          borrowAssets
          borrowAssetsUsd
          collateralAssets
          collateralAssetsUsd
          liquidityAssets
          liquidityAssetsUsd
          utilization
        }
        supplyingVaults { address name symbol }
        supplyingVaultV2s { address name symbol }
      }
    }
    """
    body = gql(query, {"marketId": market_id, "chainId": 1})
    market = body.get("data", {}).get("marketById")
    if not market:
        return None
    loan = market.get("loanAsset") or {}
    collateral = market.get("collateralAsset") or {}
    return {
        "marketId": norm(market.get("marketId") or market_id),
        "lltv": market.get("lltv"),
        "irmAddress": market.get("irmAddress"),
        "oracle": market.get("oracle"),
        "loanAsset": loan,
        "collateralAsset": collateral,
        "loanToken": norm(loan.get("address")),
        "loanSymbol": loan.get("symbol"),
        "loanDecimals": loan.get("decimals"),
        "collateralToken": norm(collateral.get("address")),
        "collateralSymbol": collateral.get("symbol"),
        "collateralDecimals": collateral.get("decimals"),
        "state": market.get("state"),
        "supplyingVaults": market.get("supplyingVaults") or [],
        "supplyingVaultV2s": market.get("supplyingVaultV2s") or [],
    }


def morpho_market_meta(market_ids: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for market_id in sorted(mid.lower() for mid in market_ids if mid):
        market = morpho_market_by_id(market_id)
        if market:
            out[market_id] = market
    return out


def discover_morpho_markets_for_assets(assets: set[str]) -> dict[str, dict[str, Any]]:
    if not assets:
        return {}
    query = """
    query MarketsByAssets($assets: [String!]) {
      collateralMarkets: markets(
        first: 100
        orderBy: SupplyAssetsUsd
        orderDirection: Desc
        where: { chainId_in: [1], collateralAssetAddress_in: $assets }
      ) {
        items {
          marketId
          lltv
          loanAsset { address symbol decimals }
          collateralAsset { address symbol decimals }
          state {
            supplyAssets
            supplyAssetsUsd
            borrowAssets
            borrowAssetsUsd
            collateralAssets
            collateralAssetsUsd
            liquidityAssets
            liquidityAssetsUsd
            utilization
          }
        }
      }
      loanMarkets: markets(
        first: 100
        orderBy: SupplyAssetsUsd
        orderDirection: Desc
        where: { chainId_in: [1], loanAssetAddress_in: $assets }
      ) {
        items {
          marketId
          lltv
          loanAsset { address symbol decimals }
          collateralAsset { address symbol decimals }
          state {
            supplyAssets
            supplyAssetsUsd
            borrowAssets
            borrowAssetsUsd
            collateralAssets
            collateralAssetsUsd
            liquidityAssets
            liquidityAssetsUsd
            utilization
          }
        }
      }
    }
    """
    body = gql(query, {"assets": sorted(assets)})
    out: dict[str, dict[str, Any]] = {}
    for group in ("collateralMarkets", "loanMarkets"):
        for market in body.get("data", {}).get(group, {}).get("items", []) or []:
            market_id = norm(market.get("marketId"))
            if not market_id:
                continue
            loan = market.get("loanAsset") or {}
            collateral = market.get("collateralAsset") or {}
            out[market_id] = {
                "marketId": market_id,
                "lltv": market.get("lltv"),
                "loanAsset": loan,
                "collateralAsset": collateral,
                "loanToken": norm(loan.get("address")),
                "loanSymbol": loan.get("symbol"),
                "loanDecimals": loan.get("decimals"),
                "collateralToken": norm(collateral.get("address")),
                "collateralSymbol": collateral.get("symbol"),
                "collateralDecimals": collateral.get("decimals"),
                "state": market.get("state"),
                "source": f"morpho_graphql:markets:{group}",
            }
    return out


def morpho_market_positions(market_id: str, order: str, limit: int = 10) -> list[dict[str, Any]]:
    query = """
    query MarketPositions($market: String!, $order: MarketPositionOrderBy!, $limit: Int!) {
      marketPositions(
        first: $limit
        orderBy: $order
        orderDirection: Desc
        where: { chainId_in: [1], marketUniqueKey_in: [$market] }
      ) {
        items {
          user { address }
          market {
            marketId
            lltv
            loanAsset { address symbol decimals }
            collateralAsset { address symbol decimals }
            state {
              supplyAssetsUsd
              borrowAssetsUsd
              collateralAssetsUsd
              liquidityAssetsUsd
              utilization
            }
          }
          state {
            supplyShares
            supplyAssets
            supplyAssetsUsd
            borrowShares
            borrowAssets
            borrowAssetsUsd
            collateral
            collateralUsd
          }
        }
      }
    }
    """
    body = gql(query, {"market": market_id, "order": order, "limit": limit})
    return body.get("data", {}).get("marketPositions", {}).get("items", []) or []


def morpho_positions_for_markets(market_ids: set[str], limit: int = 10) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for market_id in sorted(market_ids):
        for order in ("SupplyShares", "BorrowShares", "Collateral"):
            for row in morpho_market_positions(market_id, order, limit):
                row["source"] = "morpho_graphql:marketPositions"
                row["positionOrder"] = order
                rows.append(row)
    return rows


def morpho_market_transactions_for_users(users: set[str], limit: int = 1000) -> list[dict[str, Any]]:
    if not users:
        return []
    query = """
    query MarketTransactions($users: [String!], $limit: Int!) {
      marketTransactions(
        first: $limit
        orderBy: Timestamp
        orderDirection: Desc
        where: { userAddress_in: $users, chainId_in: [1] }
      ) {
        items {
          txHash
          blockNumber
          logIndex
          timestamp
          type
          user { address }
          market {
            marketId
            lltv
            loanAsset { address symbol decimals }
            collateralAsset { address symbol decimals }
            state {
              supplyAssetsUsd
              borrowAssetsUsd
              collateralAssetsUsd
              liquidityAssetsUsd
              utilization
            }
          }
          data {
            __typename
            ... on MarketTransactionTransferData { assets shares }
            ... on MarketTransactionCollateralTransferData { assets }
            ... on MarketTransactionLiquidationData {
              repaidAssets
              repaidShares
              seizedAssets
              badDebtAssets
              badDebtShares
              liquidator
            }
          }
        }
      }
    }
    """
    body = gql(query, {"users": sorted(users), "limit": limit})
    rows = body.get("data", {}).get("marketTransactions", {}).get("items", []) or []
    for row in rows:
        row["source"] = "morpho_graphql:marketTransactions"
    return rows


def etherscan_tokentx(params: dict[str, str], api_key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    offset = 1000
    while True:
        query = {
            "chainid": "1",
            "module": "account",
            "action": "tokentx",
            "page": str(page),
            "offset": str(offset),
            "sort": "asc",
            "apikey": api_key,
            **params,
        }
        key = "etherscan:" + urllib.parse.urlencode(sorted(query.items()))
        cached = cached_get(key)
        if cached is None:
            url = ETHERSCAN + "?" + urllib.parse.urlencode(query)
            with urllib.request.urlopen(url, timeout=45) as response:
                cached = json.loads(response.read().decode())
            cached_put(key, cached)
            time.sleep(0.22)
        result = cached.get("result")
        if cached.get("status") == "0":
            message = str(cached.get("message") or "")
            result_text = str(result)
            if "Result window is too large" in message or "Result window is too large" in result_text:
                start = int(params.get("startblock") or "0")
                end = int(params.get("endblock") or "0")
                if end > start:
                    mid = (start + end) // 2
                    left = etherscan_tokentx({**params, "startblock": str(start), "endblock": str(mid)}, api_key)
                    right = etherscan_tokentx({**params, "startblock": str(mid + 1), "endblock": str(end)}, api_key)
                    return left + right
                return rows
            if isinstance(result, list) and not result and cached.get("message") == "No transactions found":
                break
            if isinstance(result, str) and "No transactions" in result:
                break
            raise RuntimeError(f"Etherscan tokentx failed: {cached.get('message')} {result}")
        if not isinstance(result, list):
            raise RuntimeError(f"unexpected Etherscan result: {result!r}")
        rows.extend(result)
        if len(result) < offset:
            break
        if page >= 10:
            start = int(params.get("startblock") or "0")
            end = int(params.get("endblock") or "0")
            if end > start:
                mid = (start + end) // 2
                left = etherscan_tokentx({**params, "startblock": str(start), "endblock": str(mid)}, api_key)
                right = etherscan_tokentx({**params, "startblock": str(mid + 1), "endblock": str(end)}, api_key)
                return left + right
            break
        page += 1
    return rows


def etherscan_txlist(address: str, block_params: dict[str, str], api_key: str) -> list[dict[str, Any]]:
    query = {
        "chainid": "1",
        "module": "account",
        "action": "txlist",
        "address": address,
        "page": "1",
        "offset": "10000",
        "sort": "asc",
        "apikey": api_key,
        **block_params,
    }
    key = "etherscan:" + urllib.parse.urlencode(sorted(query.items()))
    cached = cached_get(key)
    if cached is None:
        url = ETHERSCAN + "?" + urllib.parse.urlencode(query)
        with urllib.request.urlopen(url, timeout=45) as response:
            cached = json.loads(response.read().decode())
        cached_put(key, cached)
        time.sleep(0.22)
    result = cached.get("result")
    if cached.get("status") == "0":
        if isinstance(result, str) and "No transactions" in result:
            return []
        raise RuntimeError(f"Etherscan txlist failed: {cached.get('message')} {result}")
    if not isinstance(result, list):
        raise RuntimeError(f"unexpected Etherscan txlist result: {result!r}")
    return result


def norm(value: str | None) -> str:
    return (value or "").lower()


def short(address: str) -> str:
    return f"{address[:6]}...{address[-4:]}"


def amount(row: dict[str, Any]) -> float:
    raw = int(row.get("value") or "0")
    decimals = int(row.get("tokenDecimal") or 0)
    return raw / (10 ** decimals if decimals else 1)


def topic_addr(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def token_symbol(row: dict[str, Any]) -> str:
    token = norm(row.get("contractAddress"))
    for symbol, address in TOKENS.items():
        if token == address.lower():
            return symbol
    return row.get("tokenSymbol") or short(token)


def node_kind(address: str) -> str:
    if address == ZERO:
        return "mint_burn"
    if address in {token.lower() for token in TOKENS.values()}:
        return "token"
    if address in ROUTER_OR_SOLVER or address in LENDING_PROTOCOLS or address in BUNDLER_PROTOCOLS or address in VAULT_PROTOCOLS:
        return "contract"
    return "address"


def row_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        norm(row.get("hash")),
        norm(row.get("contractAddress")),
        norm(row.get("from")),
        norm(row.get("to")),
        str(row.get("value") or "0"),
    )


def node_label(address: str) -> str:
    if address in KNOWN_LABELS:
        return KNOWN_LABELS[address]
    for symbol, token in TOKENS.items():
        if address == token.lower():
            return f"{symbol} token"
    return short(address)


def fmt(value: float) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs_value >= 1_000:
        return f"{value / 1_000:.1f}K"
    if abs_value >= 1:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{value:.4g}"


def merge_ranges(edges: list[dict[str, Any]]) -> list[int]:
    ranges = [edge.get("block_range") for edge in edges if edge.get("block_range")]
    if not ranges:
        return [0, 0]
    return [min(item[0] for item in ranges), max(item[1] for item in ranges)]


def edge_samples(edges: list[dict[str, Any]], limit: int = 5) -> list[str]:
    samples: list[str] = []
    for edge in edges:
        for tx_hash in edge.get("sample_txs") or [edge.get("sample_tx")]:
            if tx_hash and tx_hash not in samples:
                samples.append(tx_hash)
            if len(samples) >= limit:
                return samples
    return samples


def summarize_assets(edges: list[dict[str, Any]]) -> str:
    totals: dict[str, float] = defaultdict(float)
    for edge in edges:
        totals[edge["asset"]] += edge["amount"]
    return " + ".join(f"{fmt(value)} {asset}" for asset, value in sorted(totals.items()))


def transfer_role(row: dict[str, Any], actors: set[str]) -> str | None:
    source = norm(row.get("from"))
    target = norm(row.get("to"))
    if source == ZERO:
        return "mint"
    if target == ZERO:
        return "burn"
    if source in actors and target in ROUTER_OR_SOLVER:
        return "swap_paid"
    if target in actors and source in ROUTER_OR_SOLVER:
        return "swap_received"
    if source in actors:
        return "actor_out"
    if target in actors:
        return "actor_in"
    return None


def router_routes(rows: list[dict[str, Any]], actors: set[str]) -> dict[str, str]:
    by_tx: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_tx[norm(row.get("hash"))].append(row)
    summaries: dict[str, str] = {}
    for tx_hash, tx_rows in by_tx.items():
        paid: list[str] = []
        got: list[str] = []
        routers: set[str] = set()
        for row in tx_rows:
            source = norm(row.get("from"))
            target = norm(row.get("to"))
            value = amount(row)
            if value <= 0:
                continue
            if source in ROUTER_OR_SOLVER:
                routers.add(source)
            if target in ROUTER_OR_SOLVER:
                routers.add(target)
            if source in actors:
                paid.append(f"{fmt(value)} {token_symbol(row)}")
            if target in actors:
                got.append(f"{fmt(value)} {token_symbol(row)}")
        if paid and got and routers:
            route = ", ".join(node_label(router) for router in sorted(routers))
            summaries[tx_hash] = f"actor paid {' + '.join(paid)}; got {' + '.join(got)} via {route}"
    return summaries


def call_semantic(row: dict[str, Any]) -> tuple[str, str] | None:
    target = norm(row.get("to"))
    function_name = str(row.get("functionName") or row.get("methodId") or "").lower()
    if not target or target == ZERO:
        return None
    if target in LENDING_PROTOCOLS:
        if "borrow" in function_name:
            return ("lending_borrow_call", "lending")
        if "supply" in function_name or "deposit" in function_name:
            return ("lending_supply_call", "lending")
        if "repay" in function_name:
            return ("lending_repay_call", "lending")
        if "withdraw" in function_name:
            return ("lending_withdraw_call", "lending")
    if target in BUNDLER_PROTOCOLS:
        return ("lending_bundler_call", "lending")
    if target in ROUTER_OR_SOLVER and (not function_name or any(name in function_name for name in ("swap", "execute", "settle")) or function_name.startswith("0x")):
        return ("router_call", "router")
    if target in VAULT_PROTOCOLS and any(name in function_name for name in ("processwithdrawals", "deposit", "withdraw", "redeem", "mint")):
        return ("vault_call", "vault")
    if target in {TOKENS["xUSD"].lower(), TOKENS["deUSD"].lower(), TOKENS["sdeUSD"].lower()} and any(
        name in function_name for name in ("mint", "redeem", "deposit", "withdraw", "processwithdrawals", "maxredeem")
    ):
        if "deposit" in function_name:
            return ("vault_deposit_call", "vault")
        if "redeem" in function_name or "withdraw" in function_name or "processwithdrawals" in function_name:
            return ("vault_redeem_call", "vault")
        return ("vault_call", "vault")
    return None


def build_call_edges(tx_rows: list[dict[str, Any]], actor_set: set[str]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in tx_rows:
        actor = norm(row.get("from"))
        target = norm(row.get("to"))
        if actor not in actor_set:
            continue
        semantic = call_semantic(row)
        if not semantic:
            continue
        role, category = semantic
        function_name = row.get("functionName") or row.get("methodId") or "call"
        key = (actor, target, role)
        edge = grouped.setdefault(key, {
            "id": f"{actor}->{target}:call:{role}",
            "source": actor,
            "target": target,
            "asset": "call",
            "token": "call",
            "amount": 0.0,
            "count": 0,
            "role": role,
            "category": category,
            "block_range": [int(row["blockNumber"]), int(row["blockNumber"])],
            "sample_tx": row.get("hash"),
            "sample_txs": [],
            "semantic_routes": [],
            "method_ids": [],
            "function_names": [],
            "in_cycle": False,
            "morpho": target == "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb",
            "mint_burn": False,
        })
        edge["count"] += 1
        edge["block_range"] = [
            min(edge["block_range"][0], int(row["blockNumber"])),
            max(edge["block_range"][1], int(row["blockNumber"])),
        ]
        tx_hash = row.get("hash")
        if tx_hash and len(edge["sample_txs"]) < 5 and tx_hash not in edge["sample_txs"]:
            edge["sample_txs"].append(tx_hash)
        method_id = row.get("methodId")
        if method_id and len(edge["method_ids"]) < 5 and method_id not in edge["method_ids"]:
            edge["method_ids"].append(method_id)
        if function_name and len(edge["function_names"]) < 5 and function_name not in edge["function_names"]:
            edge["function_names"].append(function_name)
        if len(edge["semantic_routes"]) < 5 and function_name not in edge["semantic_routes"]:
            edge["semantic_routes"].append(function_name)
    for edge in grouped.values():
        methods = " / ".join(edge["function_names"][:2]) or edge["role"]
        edge["label"] = f"[{edge['role']}] {methods} x{edge['count']}"
    return list(grouped.values())


def receipt_transfer_rows(tx_hashes: list[str], rpc_url: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tx_hash in tx_hashes:
        receipt = rpc("eth_getTransactionReceipt", [tx_hash], rpc_url)
        if not receipt:
            continue
        block_number = str(int(receipt.get("blockNumber", "0x0"), 16))
        for log in receipt.get("logs", []):
            token = norm(log.get("address"))
            meta = TOKEN_META.get(token)
            topics = log.get("topics") or []
            if not meta or len(topics) < 3 or norm(topics[0]) != TRANSFER_TOPIC:
                continue
            raw_value = str(int(log.get("data") or "0x0", 16))
            if raw_value == "0":
                continue
            rows.append({
                "blockNumber": block_number,
                "timeStamp": "",
                "hash": norm(receipt.get("transactionHash")) or tx_hash,
                "nonce": "",
                "blockHash": receipt.get("blockHash", ""),
                "from": topic_addr(topics[1]),
                "contractAddress": token,
                "to": topic_addr(topics[2]),
                "value": raw_value,
                "tokenName": meta["symbol"],
                "tokenSymbol": meta["symbol"],
                "tokenDecimal": str(meta["decimals"]),
                "transactionIndex": str(int(receipt.get("transactionIndex", "0x0"), 16)),
                "gas": "",
                "gasPrice": "",
                "gasUsed": "",
                "cumulativeGasUsed": "",
                "input": "",
                "confirmations": "",
                "logIndex": str(int(log.get("logIndex", "0x0"), 16)),
                "source": "eth_getTransactionReceipt",
            })
    return rows


def receipt_morpho_semantics(tx_hashes: list[str], rpc_url: str) -> dict[str, Any]:
    logs: list[dict[str, Any]] = []
    market_ids: set[str] = set()
    for tx_hash in tx_hashes:
        receipt = rpc("eth_getTransactionReceipt", [tx_hash], rpc_url)
        if not receipt:
            continue
        for log in receipt.get("logs", []):
            topics = log.get("topics") or []
            if norm(log.get("address")) != MORPHO_BLUE or not topics:
                continue
            if norm(topics[0]) not in MORPHO_BLUE_TOPICS:
                continue
            logs.append(log)
            if len(topics) > 1:
                market_ids.add(norm(topics[1]))
    market_meta = morpho_market_meta(market_ids)
    parsed = parse_morpho_blue_logs(logs, market_meta=market_meta, chain_id=1, source="eth_getTransactionReceipt")
    return {
        "logs": logs,
        "market_meta": market_meta,
        "events": parsed.get("events", []),
        "evidence": parsed.get("evidence", []),
        "gaps": parsed.get("gaps", []),
    }


def market_node_id(market_id: str) -> str:
    return f"market:morpho:{market_id.lower()}"


def market_label(market: dict[str, Any], market_id: str) -> str:
    loan = market.get("loanSymbol") or (market.get("loanAsset") or {}).get("symbol") or "loan"
    collateral = market.get("collateralSymbol") or (market.get("collateralAsset") or {}).get("symbol") or "uncollateralized"
    return f"Morpho {collateral}/{loan} {short(market_id)}"


def morpho_position_group_node_id(market_id: str, field: str) -> str:
    return f"{MORPHO_POSITION_GROUP_PREFIX}:{market_id.lower()}:{field}"


def morpho_position_group_label(market: dict[str, Any], market_id: str, field: str) -> str:
    suffix = {
        "supply": "top suppliers",
        "borrow": "other borrowers",
        "collateral": "other collateral accounts",
    }.get(field, "other accounts")
    return f"{market_label(market, market_id)} {suffix}"


def morpho_event_role(event: dict[str, Any]) -> str:
    semantic_type = event.get("type") or event.get("semanticType") or "event"
    position = event.get("position") or {}
    if semantic_type == "withdraw" and position.get("kind") == "collateral":
        return "morpho_withdraw_collateral"
    return f"morpho_{semantic_type}"


def morpho_event_endpoints(event: dict[str, Any], market_id: str) -> tuple[str | None, str | None]:
    on_behalf = norm(event.get("onBehalfOf") or event.get("user"))
    receiver = norm(event.get("receiver"))
    role = morpho_event_role(event)
    market = market_node_id(market_id)
    if role in {"morpho_supply", "morpho_collateralize", "morpho_repay"}:
        return on_behalf, market
    if role in {"morpho_borrow", "morpho_withdraw", "morpho_withdraw_collateral"}:
        return market, on_behalf or receiver
    if role == "morpho_liquidation":
        return on_behalf, market
    return on_behalf, market


def build_morpho_edges(
    events: list[dict[str, Any]],
    market_meta: dict[str, dict[str, Any]],
    actor_set: set[str],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for event in events:
        market_id = norm(event.get("marketId"))
        if not market_id:
            continue
        on_behalf = norm(event.get("onBehalfOf") or event.get("user"))
        caller = norm(event.get("caller"))
        receiver = norm(event.get("receiver"))
        if actor_set and not ({on_behalf, caller, receiver} & actor_set):
            continue
        source, target = morpho_event_endpoints(event, market_id)
        if not source or not target:
            continue
        token = event.get("token") or {}
        value = token.get("amount")
        amount_value = float(value) if isinstance(value, (int, float)) else 0.0
        symbol = token.get("symbol") or short(norm(token.get("tokenAddress")))
        role = morpho_event_role(event)
        key = (source, target, market_id, role, symbol)
        market = market_meta.get(market_id, {})
        edge = grouped.setdefault(key, {
            "id": f"{source}->{target}:{market_id}:{role}:{symbol}",
            "source": source,
            "target": target,
            "asset": symbol,
            "token": norm(token.get("tokenAddress")) or f"morpho:{market_id}",
            "amount": 0.0,
            "count": 0,
            "role": role,
            "category": "lending",
            "block_range": [int(event.get("blockNumber") or 0), int(event.get("blockNumber") or 0)],
            "sample_tx": event.get("txHash"),
            "sample_txs": [],
            "semantic_routes": [],
            "method_ids": [],
            "function_names": [],
            "in_cycle": False,
            "morpho": True,
            "mint_burn": False,
        })
        edge["amount"] += amount_value
        edge["count"] += 1
        block = int(event.get("blockNumber") or 0)
        if block:
            edge["block_range"] = [
                min(edge["block_range"][0] or block, block),
                max(edge["block_range"][1], block),
            ]
        tx_hash = event.get("txHash")
        if tx_hash and len(edge["sample_txs"]) < 5 and tx_hash not in edge["sample_txs"]:
            edge["sample_txs"].append(tx_hash)
        route = (
            f"Morpho Blue {role.replace('morpho_', '')}; "
            f"onBehalf={short(on_behalf) if on_behalf else '-'}; "
            f"caller={short(caller) if caller else '-'}; "
            f"receiver={short(receiver) if receiver else '-'}; "
            f"market={market_label(market, market_id)}"
        )
        if len(edge["semantic_routes"]) < 5 and route not in edge["semantic_routes"]:
            edge["semantic_routes"].append(route)
    for edge in grouped.values():
        edge["label"] = f"[{edge['role']}] {edge['asset']} {fmt(edge['amount'])} x{edge['count']}"
    return list(grouped.values())


def raw_amount_to_float(raw: Any, decimals: Any) -> float:
    if raw is None:
        return 0.0
    try:
        raw_int = int(raw)
        dec = int(decimals or 0)
    except (TypeError, ValueError):
        return 0.0
    return raw_int / (10 ** dec if dec else 1)


def position_amount(row: dict[str, Any], field: str) -> float:
    state = row.get("state") or {}
    market = row.get("market") or {}
    if field == "supply":
        decimals = ((market.get("loanAsset") or {}).get("decimals"))
        return raw_amount_to_float(state.get("supplyAssets"), decimals)
    if field == "borrow":
        decimals = ((market.get("loanAsset") or {}).get("decimals"))
        return raw_amount_to_float(state.get("borrowAssets"), decimals)
    if field == "collateral":
        decimals = ((market.get("collateralAsset") or {}).get("decimals"))
        return raw_amount_to_float(state.get("collateral"), decimals)
    return 0.0


def build_morpho_position_edges(rows: list[dict[str, Any]], min_usd: float = 1000.0) -> list[dict[str, Any]]:
    specs = {
        "SupplyShares": ("supply", "supplyAssetsUsd", "morpho_current_supply_snapshot"),
        "BorrowShares": ("borrow", "borrowAssetsUsd", "morpho_current_borrow_snapshot"),
        "Collateral": ("collateral", "collateralUsd", "morpho_current_collateral_snapshot"),
    }
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        order = row.get("positionOrder")
        if order not in specs:
            continue
        field, usd_key, role = specs[order]
        user = norm(((row.get("user") or {}).get("address")))
        market = row.get("market") or {}
        market_id = norm(market.get("marketId"))
        if not user or not market_id or user == ZERO:
            continue
        state = row.get("state") or {}
        usd = state.get(usd_key)
        usd_value = float(usd) if isinstance(usd, (int, float)) else 0.0
        if usd_value < min_usd:
            continue
        loan = market.get("loanAsset") or {}
        collateral = market.get("collateralAsset") or {}
        asset = collateral if field == "collateral" else loan
        symbol = asset.get("symbol") or "asset"
        amount_value = position_amount(row, field)
        market_node = market_node_id(market_id)
        is_visible_user = user in VISIBLE_MORPHO_POSITION_USERS
        source_label = None
        target_label = None
        if is_visible_user:
            source, target = (user, market_node) if field in {"supply", "collateral"} else (market_node, user)
            grouped_position = False
        else:
            group_node = morpho_position_group_node_id(market_id, field)
            group_label = morpho_position_group_label(market, market_id, field)
            source, target = (group_node, market_node) if field in {"supply", "collateral"} else (market_node, group_node)
            if source == group_node:
                source_label = group_label
            else:
                target_label = group_label
            grouped_position = True
        key = (source, target, market_id, role)
        edge = grouped.setdefault(key, {
            "id": f"{source}->{target}:{market_id}:{role}",
            "source": source,
            "target": target,
            "source_label": source_label,
            "target_label": target_label,
            "source_kind": "cluster" if source_label else None,
            "target_kind": "cluster" if target_label else None,
            "source_category": "morpho_position_group" if source_label else None,
            "target_category": "morpho_position_group" if target_label else None,
            "asset": symbol,
            "token": norm(asset.get("address")) or f"morpho:{market_id}",
            "amount": 0.0,
            "count": 0,
            "role": role,
            "category": "lending",
            "block_range": [0, 0],
            "sample_tx": None,
            "sample_txs": [],
            "semantic_routes": [],
            "method_ids": [],
            "function_names": [],
            "in_cycle": False,
            "morpho": True,
            "mint_burn": False,
            "usd": 0.0,
            "position_group": grouped_position,
            "position_users": [],
        })
        edge["amount"] += amount_value
        edge["usd"] += usd_value
        edge["count"] += 1
        if user not in edge["position_users"] and len(edge["position_users"]) < 25:
            edge["position_users"].append(user)
        route = (
            f"Morpho API current marketPositions; order={order}; "
            f"user={short(user)}; market={market_label(market, market_id)}; "
            f"usd={usd_value:.2f}; source={row.get('source')}"
        )
        if len(edge["semantic_routes"]) < 5 and route not in edge["semantic_routes"]:
            edge["semantic_routes"].append(route)
    for edge in grouped.values():
        edge["amount"] = round(edge["amount"], 6)
        edge["usd"] = round(edge["usd"], 2)
        if edge.get("position_group"):
            edge["label"] = (
                f"[{edge['role']}] {edge['asset']} {fmt(edge['amount'])} / "
                f"${fmt(edge['usd'])} across {len(edge.get('position_users') or [])} accounts"
            )
        else:
            edge["label"] = f"[{edge['role']}] {edge['asset']} {fmt(edge['amount'])} / ${fmt(edge['usd'])}"
    return list(grouped.values())


def tx_row_amount(row: dict[str, Any]) -> tuple[str, str, float]:
    tx_type = row.get("type")
    data = row.get("data") or {}
    market = row.get("market") or {}
    loan = market.get("loanAsset") or {}
    collateral = market.get("collateralAsset") or {}
    if tx_type in {"Supply", "Withdraw", "Borrow", "Repay"}:
        return norm(loan.get("address")), loan.get("symbol") or "loan", raw_amount_to_float(data.get("assets"), loan.get("decimals"))
    if tx_type in {"SupplyCollateral", "WithdrawCollateral"}:
        return norm(collateral.get("address")), collateral.get("symbol") or "collateral", raw_amount_to_float(data.get("assets"), collateral.get("decimals"))
    if tx_type == "Liquidation":
        return norm(loan.get("address")), loan.get("symbol") or "loan", raw_amount_to_float(data.get("repaidAssets"), loan.get("decimals"))
    return "", "asset", 0.0


def build_morpho_api_transaction_edges(rows: list[dict[str, Any]], frm: int, to: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        block = int(row.get("blockNumber") or 0)
        if block and (block < frm or block > to):
            continue
        user = norm(((row.get("user") or {}).get("address")))
        market = row.get("market") or {}
        market_id = norm(market.get("marketId"))
        if not user or not market_id:
            continue
        tx_type = str(row.get("type") or "transaction")
        role = f"morpho_api_{tx_type.lower()}"
        market_node = market_node_id(market_id)
        if tx_type in {"Supply", "SupplyCollateral", "Repay"}:
            source, target = user, market_node
        elif tx_type in {"Borrow", "Withdraw", "WithdrawCollateral"}:
            source, target = market_node, user
        elif tx_type == "Liquidation":
            source, target = user, market_node
        else:
            source, target = user, market_node
        token, symbol, amount_value = tx_row_amount(row)
        key = (source, target, market_id, role, symbol)
        edge = grouped.setdefault(key, {
            "id": f"{source}->{target}:{market_id}:{role}:{symbol}",
            "source": source,
            "target": target,
            "asset": symbol,
            "token": token or f"morpho:{market_id}",
            "amount": 0.0,
            "count": 0,
            "role": role,
            "category": "lending",
            "block_range": [block, block],
            "sample_tx": row.get("txHash"),
            "sample_txs": [],
            "semantic_routes": [],
            "method_ids": [],
            "function_names": [],
            "in_cycle": False,
            "morpho": True,
            "mint_burn": False,
        })
        edge["amount"] += amount_value
        edge["count"] += 1
        if block:
            edge["block_range"] = [
                min(edge["block_range"][0] or block, block),
                max(edge["block_range"][1], block),
            ]
        tx_hash = row.get("txHash")
        if tx_hash and len(edge["sample_txs"]) < 5 and tx_hash not in edge["sample_txs"]:
            edge["sample_txs"].append(tx_hash)
        route = (
            f"Morpho API marketTransactions; type={tx_type}; "
            f"user={short(user)}; market={market_label(market, market_id)}; "
            f"block={block}; source={row.get('source')}"
        )
        if len(edge["semantic_routes"]) < 5 and route not in edge["semantic_routes"]:
            edge["semantic_routes"].append(route)
    for edge in grouped.values():
        edge["amount"] = round(edge["amount"], 6)
        edge["label"] = f"[{edge['role']}] {edge['asset']} {fmt(edge['amount'])} x{edge['count']}"
    return list(grouped.values())


def build_morpho_market_discovery_edges(token_markets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for market_id, market in sorted(token_markets.items()):
        state = market.get("state") or {}
        supply_usd = float(state.get("supplyAssetsUsd") or 0)
        borrow_usd = float(state.get("borrowAssetsUsd") or 0)
        collateral_usd = float(state.get("collateralAssetsUsd") or 0)
        edge = {
            "id": f"{MORPHO_TOKEN_MARKETS}->{market_node_id(market_id)}:morpho_market_discovered",
            "source": MORPHO_TOKEN_MARKETS,
            "target": market_node_id(market_id),
            "asset": "USD",
            "token": "morpho_graphql_market",
            "amount": round(supply_usd, 2),
            "count": 1,
            "role": "morpho_market_discovered",
            "category": "lending",
            "block_range": [0, 0],
            "sample_tx": None,
            "sample_txs": [],
            "semantic_routes": [
                f"Morpho API markets asset discovery; market={market_label(market, market_id)}; "
                f"supplyUsd={supply_usd:.2f}; borrowUsd={borrow_usd:.2f}; collateralUsd={collateral_usd:.2f}; "
                f"source={market.get('source') or 'morpho_graphql:markets'}"
            ],
            "method_ids": [],
            "function_names": [],
            "in_cycle": False,
            "morpho": True,
            "mint_burn": False,
            "usd": round(supply_usd, 2),
        }
        edge["label"] = f"[morpho_market_discovered] TVL ${fmt(supply_usd)}"
        edges.append(edge)
    return edges


def build_group_transfer_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs = [
        (STREAM_RELATED_ACTORS, ELIXIR_RELATED_ACTORS, STREAM_OBSERVED_CLUSTER, ELIXIR_OBSERVED_CLUSTER, "stream_to_elixir_observed_transfer"),
        (ELIXIR_RELATED_ACTORS, STREAM_RELATED_ACTORS, ELIXIR_OBSERVED_CLUSTER, STREAM_OBSERVED_CLUSTER, "elixir_to_stream_observed_transfer"),
    ]
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for source_group, target_group, source_node, target_node, role in specs:
        for edge in edges:
            if edge.get("source") not in source_group or edge.get("target") not in target_group:
                continue
            if edge.get("mint_burn") or edge.get("amount", 0) <= 0:
                continue
            asset = edge.get("asset") or "asset"
            key = (source_node, target_node, role, asset)
            out = grouped.setdefault(key, {
                "id": f"{source_node}->{target_node}:{role}:{asset}",
                "source": source_node,
                "target": target_node,
                "asset": asset,
                "token": edge.get("token"),
                "amount": 0.0,
                "count": 0,
                "role": role,
                "category": "actor_cluster",
                "block_range": edge.get("block_range", [0, 0]),
                "sample_tx": edge.get("sample_tx"),
                "sample_txs": [],
                "semantic_routes": [],
                "method_ids": [],
                "function_names": [],
                "in_cycle": False,
                "morpho": False,
                "mint_burn": False,
            })
            out["amount"] += edge.get("amount", 0.0)
            out["count"] += edge.get("count", 0)
            out["block_range"] = merge_ranges([out, edge])
            for tx_hash in edge.get("sample_txs") or [edge.get("sample_tx")]:
                if tx_hash and len(out["sample_txs"]) < 5 and tx_hash not in out["sample_txs"]:
                    out["sample_txs"].append(tx_hash)
            route = (
                f"exact ERC20 Transfer aggregate; from={edge.get('source')} to={edge.get('target')}; "
                f"token={asset}; amount={fmt(edge.get('amount', 0.0))}; tx={edge.get('sample_tx')}"
            )
            if len(out["semantic_routes"]) < 5:
                out["semantic_routes"].append(route)
    for edge in grouped.values():
        edge["amount"] = round(edge["amount"], 6)
        edge["label"] = f"[{edge['role']}] {edge['asset']} {fmt(edge['amount'])} x{edge['count']}"
    return list(grouped.values())


def build_stream_findings(
    *,
    base_edges: list[dict[str, Any]],
    morpho_position_edges: list[dict[str, Any]],
    token_markets: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    stream_morpho_borrows = [
        edge for edge in morpho_position_edges
        if edge.get("role") == "morpho_current_borrow_snapshot"
        and edge.get("target") in STREAM_RELATED_ACTORS
        and edge.get("usd", 0) >= 1_000_000
    ]
    for edge in sorted(stream_morpho_borrows, key=lambda item: -item.get("usd", 0))[:5]:
        findings.append({
            "id": f"finding:{edge['id']}",
            "type": "morpho_current_borrow",
            "confidence": "morpho_api_snapshot",
            "message": f"{node_label(edge['target'])} current Morpho borrow snapshot: {edge['label']}",
            "edgeId": edge["id"],
            "source": "morpho_graphql:marketPositions",
        })
    xusd_usdc_markets = [
        market for market in token_markets.values()
        if (market.get("collateralSymbol") == "xUSD" and market.get("loanSymbol") == "USDC")
    ]
    if xusd_usdc_markets:
        total_supply = sum(float((market.get("state") or {}).get("supplyAssetsUsd") or 0) for market in xusd_usdc_markets)
        findings.append({
            "id": "finding:morpho:xusd-usdc-current-size",
            "type": "morpho_market_discovery",
            "confidence": "morpho_api_snapshot",
            "message": f"xUSD/USDC Morpho markets discovered, but current total supply is only ${total_supply:.2f}.",
            "marketIds": [market["marketId"] for market in xusd_usdc_markets],
            "source": "morpho_graphql:markets",
        })
    else:
        findings.append({
            "id": "finding:morpho:xusd-usdc-not-found",
            "type": "gap",
            "confidence": "not_observed",
            "message": "No xUSD/USDC Morpho market was returned by asset market discovery.",
            "source": "morpho_graphql:markets",
        })
    direct_group_edges = [
        edge for edge in base_edges
        if edge.get("source") in {STREAM_OBSERVED_CLUSTER, ELIXIR_OBSERVED_CLUSTER}
        and edge.get("target") in {STREAM_OBSERVED_CLUSTER, ELIXIR_OBSERVED_CLUSTER}
    ]
    if direct_group_edges:
        findings.append({
            "id": "finding:stream-elixir-direct-transfer",
            "type": "direct_transfer_observed",
            "confidence": "exact_transfer_rows",
            "message": "Direct token transfer edges between configured Stream/deUSD actors and Elixir actors were observed.",
            "edgeIds": [edge["id"] for edge in direct_group_edges],
            "source": "etherscan_v2_tokentx",
        })
    else:
        findings.append({
            "id": "finding:stream-elixir-direct-transfer-not-observed",
            "type": "gap",
            "confidence": "not_observed",
            "message": "No direct Stream/deUSD actor -> Elixir actor transfer edge was observed in the selected block window.",
            "source": "etherscan_v2_tokentx",
        })
    return findings


def build_payload(
    rows: list[dict[str, Any]],
    tx_rows: list[dict[str, Any]],
    actors: list[str],
    frm: int,
    to: int,
    min_amount: float,
    top_edges: int,
    morpho_events: list[dict[str, Any]] | None = None,
    morpho_market_meta_by_id: dict[str, dict[str, Any]] | None = None,
    morpho_position_rows: list[dict[str, Any]] | None = None,
    morpho_api_tx_rows: list[dict[str, Any]] | None = None,
    morpho_token_markets: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    actor_set = {actor.lower() for actor in actors}
    morpho_events = morpho_events or []
    morpho_market_meta_by_id = morpho_market_meta_by_id or {}
    morpho_position_rows = morpho_position_rows or []
    morpho_api_tx_rows = morpho_api_tx_rows or []
    morpho_token_markets = morpho_token_markets or {}
    all_morpho_market_meta = {**morpho_token_markets, **morpho_market_meta_by_id}
    rows = [row for row in rows if norm(row.get("contractAddress")) in {token.lower() for token in TOKENS.values()}]
    rows = [row for row in rows if amount(row) >= min_amount]
    routes = router_routes(rows, actor_set)
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str, str | None], dict[str, Any]] = {}

    def ensure_node(address: str, is_seed: bool = False) -> None:
        current = nodes.get(address)
        if current:
            current["data"]["is_seed"] = current["data"].get("is_seed") or is_seed
            return
        nodes[address] = {
            "id": address,
            "type": "address",
            "label": node_label(address),
            "data": {
                "kind": node_kind(address),
                "is_seed": is_seed,
                "in_cycle": False,
                "address": address,
            },
        }

    def ensure_semantic_node(node_id: str, label: str, kind: str, category: str) -> None:
        if node_id in nodes:
            return
        nodes[node_id] = {
            "id": node_id,
            "type": "semantic",
            "label": label,
            "data": {
                "kind": kind,
                "category": category,
                "is_seed": True,
                "in_cycle": False,
            },
        }

    for actor in actors:
        ensure_node(actor.lower(), True)
    ensure_node(TOKENS["xUSD"].lower(), True)
    for target in LENDING_PROTOCOLS:
        ensure_node(target)
    ensure_semantic_node(STREAM_OBSERVED_CLUSTER, "Stream/deUSD observed actors", "cluster", "actor_cluster")
    ensure_semantic_node(ELIXIR_OBSERVED_CLUSTER, "Elixir observed actors", "cluster", "actor_cluster")
    ensure_semantic_node(MORPHO_TOKEN_MARKETS, "Morpho xUSD/deUSD/sdeUSD markets", "protocol", "lending")
    for market_id, market in all_morpho_market_meta.items():
        ensure_semantic_node(market_node_id(market_id), market_label(market, market_id), "market", "lending")
    for row in rows:
        source = norm(row.get("from")) or ZERO
        target = norm(row.get("to")) or ZERO
        token = norm(row.get("contractAddress"))
        role = transfer_role(row, actor_set)
        ensure_node(source)
        ensure_node(target)
        key = (source, target, token, role)
        value = amount(row)
        edge = edges.setdefault(key, {
            "id": f"{source}->{target}:{token}:{role or 'transfer'}",
            "source": source,
            "target": target,
            "asset": token_symbol(row),
            "token": token,
            "suspicious": False,
            "amount": 0.0,
            "count": 0,
            "role": role,
            "block_range": [int(row["blockNumber"]), int(row["blockNumber"])],
            "sample_tx": row.get("hash"),
            "sample_txs": [],
            "semantic_routes": [],
            "method_ids": [],
            "function_names": [],
            "in_cycle": False,
            "morpho": source == "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb" or target == "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb",
            "mint_burn": source == ZERO or target == ZERO,
        })
        edge["amount"] += value
        edge["count"] += 1
        edge["block_range"] = [
            min(edge["block_range"][0], int(row["blockNumber"])),
            max(edge["block_range"][1], int(row["blockNumber"])),
        ]
        tx_hash = row.get("hash")
        if tx_hash and len(edge["sample_txs"]) < 5 and tx_hash not in edge["sample_txs"]:
            edge["sample_txs"].append(tx_hash)
        method_id = row.get("methodId")
        if method_id and len(edge["method_ids"]) < 5 and method_id not in edge["method_ids"]:
            edge["method_ids"].append(method_id)
        function_name = row.get("functionName")
        if function_name and len(edge["function_names"]) < 5 and function_name not in edge["function_names"]:
            edge["function_names"].append(function_name)
        route = routes.get(norm(tx_hash))
        if route and len(edge["semantic_routes"]) < 5 and route not in edge["semantic_routes"]:
            edge["semantic_routes"].append(route)

    semantic_edges: list[dict[str, Any]] = []
    ensure_semantic_node(STREAM_XUSD_MINT_SURFACE, "Stream xUSD minting surface", "protocol", "vault")
    for actor in actor_set:
        minted_edges = [
            edge for edge in edges.values()
            if edge["source"] == ZERO and edge["target"] == actor and edge["token"] == TOKENS["xUSD"].lower()
        ]
        stable_funding_edges = [
            edge for edge in edges.values()
            if edge["source"] == actor
            and edge["target"] in STREAM_CONTROLLED_SURFACES
            and edge["token"] in STABLE_TOKENS
        ]
        burn_edges = [
            edge for edge in edges.values()
            if edge["source"] == actor and edge["target"] == ZERO and edge["token"] == TOKENS["xUSD"].lower()
        ]
        if minted_edges:
            samples = edge_samples(minted_edges)
            semantic_edges.append({
                "id": f"{STREAM_XUSD_MINT_SURFACE}->{actor}:xusd_mint_to_actor",
                "source": STREAM_XUSD_MINT_SURFACE,
                "target": actor,
                "asset": "xUSD",
                "token": TOKENS["xUSD"].lower(),
                "amount": round(sum(edge["amount"] for edge in minted_edges), 6),
                "count": sum(edge["count"] for edge in minted_edges),
                "role": "xusd_mint_to_actor",
                "category": "vault",
                "block_range": merge_ranges(minted_edges),
                "sample_tx": samples[0] if samples else None,
                "sample_txs": samples,
                "semantic_routes": [
                    "exact xUSD Transfer mint to actor; caller/minter adapter still required for final vault attribution",
                    *[f"function {name}" for name in minted_edges[0].get("function_names", [])[:2]],
                ],
                "in_cycle": False,
                "morpho": False,
                "mint_burn": True,
            })
        if minted_edges and stable_funding_edges:
            samples = edge_samples(stable_funding_edges)
            semantic_edges.append({
                "id": f"{actor}->{STREAM_XUSD_MINT_SURFACE}:possible_self_mint_funding",
                "source": actor,
                "target": STREAM_XUSD_MINT_SURFACE,
                "asset": "USDC/USDT",
                "token": "multi:stablecoin",
                "amount": round(sum(edge["amount"] for edge in stable_funding_edges), 6),
                "count": sum(edge["count"] for edge in stable_funding_edges),
                "role": "possible_self_mint_funding",
                "category": "vault",
                "block_range": merge_ranges(stable_funding_edges + minted_edges),
                "sample_tx": samples[0] if samples else None,
                "sample_txs": samples,
                "semantic_routes": [
                    f"actor sent {summarize_assets(stable_funding_edges)} to Stream-controlled surface and received {summarize_assets(minted_edges)} mint in the same scan window",
                    "not same-tx-only; this is a cross-window self-mint pattern awaiting StreamVault function adapter",
                ],
                "in_cycle": False,
                "morpho": False,
                "mint_burn": False,
            })
        if burn_edges:
            samples = edge_samples(burn_edges)
            semantic_edges.append({
                "id": f"{actor}->{STREAM_XUSD_MINT_SURFACE}:xusd_burn_by_actor",
                "source": actor,
                "target": STREAM_XUSD_MINT_SURFACE,
                "asset": "xUSD",
                "token": TOKENS["xUSD"].lower(),
                "amount": round(sum(edge["amount"] for edge in burn_edges), 6),
                "count": sum(edge["count"] for edge in burn_edges),
                "role": "xusd_burn_by_actor",
                "category": "vault",
                "block_range": merge_ranges(burn_edges),
                "sample_tx": samples[0] if samples else None,
                "sample_txs": samples,
                "semantic_routes": ["exact xUSD Transfer burn by actor"],
                "in_cycle": False,
                "morpho": False,
                "mint_burn": True,
            })

    call_edges = build_call_edges(tx_rows, actor_set)
    for edge in call_edges:
        ensure_node(edge["source"])
        ensure_node(edge["target"])

    morpho_edges = build_morpho_edges(morpho_events, all_morpho_market_meta, actor_set)
    morpho_position_edges = build_morpho_position_edges(morpho_position_rows)
    morpho_api_edges = build_morpho_api_transaction_edges(morpho_api_tx_rows, frm, to)
    morpho_discovery_edges = build_morpho_market_discovery_edges(morpho_token_markets)
    cluster_transfer_edges = build_group_transfer_edges(list(edges.values()))
    for edge in morpho_edges + morpho_position_edges + morpho_api_edges + morpho_discovery_edges + cluster_transfer_edges:
        if edge["source"].startswith("market:morpho:"):
            market_id = edge["source"].split("market:morpho:", 1)[1]
            ensure_semantic_node(edge["source"], market_label(all_morpho_market_meta.get(market_id, {}), market_id), "market", "lending")
        elif edge["source"].startswith("semantic:"):
            ensure_semantic_node(
                edge["source"],
                edge.get("source_label") or edge["source"].replace("semantic:", "").replace("-", " "),
                edge.get("source_kind") or "cluster",
                edge.get("source_category") or "semantic",
            )
        else:
            ensure_node(edge["source"])
        if edge["target"].startswith("market:morpho:"):
            market_id = edge["target"].split("market:morpho:", 1)[1]
            ensure_semantic_node(edge["target"], market_label(all_morpho_market_meta.get(market_id, {}), market_id), "market", "lending")
        elif edge["target"].startswith("semantic:"):
            ensure_semantic_node(
                edge["target"],
                edge.get("target_label") or edge["target"].replace("semantic:", "").replace("-", " "),
                edge.get("target_kind") or "cluster",
                edge.get("target_category") or "semantic",
            )
        else:
            ensure_node(edge["target"])

    core_pair_edges = [
        edge for edge in edges.values()
        if edge["source"] in CORE_ADDRESSES and edge["target"] in CORE_ADDRESSES
    ]
    def relevant_xusd_edge(edge: dict[str, Any]) -> bool:
        if edge.get("token") != TOKENS["xUSD"].lower():
            return True
        return (
            edge["source"] in CORE_ADDRESSES
            or edge["target"] in CORE_ADDRESSES
            or edge["source"] == ZERO
            or edge["target"] == ZERO
            or edge.get("role") in {"mint", "burn", "actor_in", "actor_out"}
        )

    xusd_edges = sorted(
        [edge for edge in edges.values() if edge.get("token") == TOKENS["xUSD"].lower() and relevant_xusd_edge(edge)],
        key=lambda edge: -edge["amount"],
    )[:24]
    core_edges: list[dict[str, Any]] = core_pair_edges + xusd_edges
    for core in CORE_ADDRESSES:
        core_edges.extend(
            sorted(
                [edge for edge in edges.values() if edge["source"] == core or edge["target"] == core],
                key=lambda edge: -edge["amount"],
            )[:12]
        )
    pool_edges: list[dict[str, Any]] = []
    for pool in PINNED_POOL_ADDRESSES:
        pool_edges.extend(
            sorted(
                [edge for edge in edges.values() if edge["source"] == pool or edge["target"] == pool],
                key=lambda edge: -edge["amount"],
            )[:16]
        )
    pinned_edges: list[dict[str, Any]] = []
    pinned_seen: set[str] = set()
    for edge in semantic_edges + cluster_transfer_edges + morpho_edges + morpho_api_edges + morpho_position_edges + morpho_discovery_edges + call_edges + core_edges + pool_edges:
        if edge["id"] in pinned_seen:
            continue
        pinned_edges.append(edge)
        pinned_seen.add(edge["id"])
    pinned_ids = {edge["id"] for edge in pinned_edges}
    ranked_edges = [
        edge for edge in sorted(edges.values(), key=lambda edge: -edge["amount"])
        if edge["id"] not in pinned_ids and relevant_xusd_edge(edge)
    ]
    kept_edges = pinned_edges + ranked_edges[:max(0, top_edges - len(pinned_edges))]
    used = set(actor_set) | {TOKENS["xUSD"].lower(), STREAM_XUSD_MINT_SURFACE}
    for edge in kept_edges:
        used.add(edge["source"])
        used.add(edge["target"])
        edge["amount"] = round(edge["amount"], 6)
        if not edge.get("label"):
            prefix = f"[{edge['role']}] " if edge.get("role") else ""
            edge["label"] = f"{prefix}{edge['asset']} {fmt(edge['amount'])} x{edge['count']}"
    return {
        "mode": "flow",
        "nodes": [node for address, node in sorted(nodes.items()) if address in used],
        "edges": kept_edges,
        "metadata": {
            "seeds": [*actors, TOKENS["xUSD"].lower()],
            "from_block": frm,
            "to_block": to,
            "cycle_nodes": 0,
            "source": "feeder/stream_historical_flow.py (etherscan_v2_tokentx actor+token-contract scans)",
            "filters": {
                "tokens": TOKENS,
                "min_amount": min_amount,
                "top_edges": top_edges,
            },
            "semantic_adapters": [
                "router_receipt_transfer_pairing",
                "stream_xusd_cross_window_self_mint_pattern",
                "morpho_blue_receipt_events_with_graphql_market_metadata",
                "morpho_graphql_market_transactions",
                "morpho_graphql_market_positions",
                "stream_elixir_exact_transfer_cluster_summary",
            ],
            "findings": build_stream_findings(
                base_edges=kept_edges,
                morpho_position_edges=morpho_position_edges,
                token_markets=morpho_token_markets,
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor", action="append", default=[], help="Actor address to scan. Repeatable. Defaults to Stream/Elixir observed actors.")
    parser.add_argument("--scan-token", action="append", default=[], help="Token symbol/address to scan by contractaddress. Repeatable. Defaults to xUSD,deUSD,sdeUSD.")
    parser.add_argument("--from", dest="frm", type=int, default=23667000)
    parser.add_argument("--to", type=int, default=23750000)
    parser.add_argument("--min-amount", type=float, default=1000.0)
    parser.add_argument("--top-edges", type=int, default=220)
    parser.add_argument("--max-receipts", type=int, default=500, help="Maximum router/solver tx receipts to expand into same-tx Transfer logs.")
    parser.add_argument("--morpho-position-limit", type=int, default=10, help="Top Morpho positions per discovered market/order.")
    parser.add_argument("--morpho-tx-limit", type=int, default=1000, help="Morpho marketTransactions rows to request for observed actors.")
    parser.add_argument("--out", default=str(ROOT / "graphs" / "frontend" / "flow.stream.historical.json"))
    args = parser.parse_args()

    env = load_env()
    api_key = env.get("ETHERSCAN_API_KEY")
    if not api_key:
        raise SystemExit("ETHERSCAN_API_KEY missing")
    rpc_url = env.get("ETH_RPC")
    if not rpc_url:
        raise SystemExit("ETH_RPC missing")

    actors = [actor.lower() for actor in (args.actor or DEFAULT_ACTORS)]
    scan_tokens = [TOKENS.get(token, token).lower() for token in (args.scan_token or DEFAULT_SCAN_TOKENS)]
    block_params = {"startblock": str(args.frm), "endblock": str(args.to)}
    actor_rows: list[dict[str, Any]] = []
    actor_tx_rows: list[dict[str, Any]] = []
    for actor in actors:
        actor_rows.extend(etherscan_tokentx({"address": actor, **block_params}, api_key))
        actor_tx_rows.extend(etherscan_txlist(actor, block_params, api_key))
    token_rows: list[dict[str, Any]] = []
    for token in scan_tokens:
        token_rows.extend(etherscan_tokentx({"contractaddress": token, **block_params}, api_key))
    base_rows = actor_rows + token_rows
    receipt_protocol_targets = ROUTER_OR_SOLVER | LENDING_PROTOCOLS | BUNDLER_PROTOCOLS | VAULT_PROTOCOLS
    candidate_tx_blocks: dict[str, int] = {}
    for row in base_rows:
        tx_hash = norm(row.get("hash"))
        if not tx_hash or amount(row) < args.min_amount:
            continue
        if norm(row.get("from")) not in receipt_protocol_targets and norm(row.get("to")) not in receipt_protocol_targets:
            continue
        block = int(row.get("blockNumber") or 0)
        candidate_tx_blocks[tx_hash] = min(candidate_tx_blocks.get(tx_hash, block), block)
    for row in actor_tx_rows:
        tx_hash = norm(row.get("hash"))
        if not tx_hash:
            continue
        if norm(row.get("to")) not in receipt_protocol_targets and norm(row.get("from")) not in receipt_protocol_targets:
            continue
        block = int(row.get("blockNumber") or 0)
        candidate_tx_blocks[tx_hash] = min(candidate_tx_blocks.get(tx_hash, block), block)
    candidate_txs = [tx for tx, _block in sorted(candidate_tx_blocks.items(), key=lambda item: (item[1], item[0]))]
    expanded_txs = candidate_txs[:args.max_receipts]
    receipt_rows = receipt_transfer_rows(expanded_txs, rpc_url)
    morpho_output = receipt_morpho_semantics(expanded_txs, rpc_url)
    morpho_token_markets = discover_morpho_markets_for_assets(TOKEN_MARKET_ASSETS)
    morpho_position_rows = morpho_positions_for_markets(
        set(morpho_token_markets) | set(morpho_output["market_meta"]),
        limit=max(1, min(args.morpho_position_limit, 25)),
    )
    morpho_api_tx_rows = morpho_market_transactions_for_users(
        set(actors) | STREAM_RELATED_ACTORS | ELIXIR_RELATED_ACTORS,
        limit=max(1, min(args.morpho_tx_limit, 1000)),
    )
    rows_by_key = {row_key(row): row for row in base_rows + receipt_rows}
    payload = build_payload(
        list(rows_by_key.values()),
        actor_tx_rows,
        actors,
        args.frm,
        args.to,
        args.min_amount,
        args.top_edges,
        morpho_events=morpho_output["events"],
        morpho_market_meta_by_id=morpho_output["market_meta"],
        morpho_position_rows=morpho_position_rows,
        morpho_api_tx_rows=morpho_api_tx_rows,
        morpho_token_markets=morpho_token_markets,
    )
    payload["metadata"]["receipt_expansion"] = {
        "candidate_txs": len(candidate_txs),
        "expanded_txs": len(expanded_txs),
        "receipt_rows": len(receipt_rows),
        "morpho_logs": len(morpho_output["logs"]),
        "morpho_events": len(morpho_output["events"]),
        "morpho_markets": len(morpho_output["market_meta"]),
        "morpho_gaps": len(morpho_output["gaps"]),
        "morpho_token_markets": len(morpho_token_markets),
        "morpho_position_rows": len(morpho_position_rows),
        "morpho_api_tx_rows": len(morpho_api_tx_rows),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"actors={len(actors)} actor_rows={len(actor_rows)} actor_txs={len(actor_tx_rows)} token_rows={len(token_rows)} receipt_rows={len(receipt_rows)} nodes={len(payload['nodes'])} edges={len(payload['edges'])} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
