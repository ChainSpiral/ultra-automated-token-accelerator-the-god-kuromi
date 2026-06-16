#!/usr/bin/env python3
"""
EOA semantic timeline exporter.

Purpose:
  token Transfer logs show where tokens moved, but not why they moved.
  This helper turns EOA transaction history into chronological DeFi events:
    - lending: Aave/Spark supply/borrow/repay/withdraw
    - vaults: ERC4626 async request/redeem/deposit flows
    - bridge: CCTP/Linea/Optimism/Across style cross-chain calls
    - swaps: ParaSwap/Odos/1inch/Kyber/Pendle
    - Yield Basis: LT deposit, gauge claim/stake, migration

Output is intentionally graph-ready:
  {
    "events": [... chronological semantic events ...],
    "graph": {"nodes": [...address nodes...], "edges": [...call/transfer edges...]},
    "addresses": {"0x...": {"summary": ...}}
  }

Examples:
  python3 feeder/eoa_timeline.py \
    --addresses 0x325228217e02e31529bf4bc6e32db695ea525669 \
    --from-block 23990000 \
    --out graphs/frontend/eoa.timeline.json

  python3 feeder/eoa_timeline.py \
    --graph graphs/frontend/weETH.sim.json \
    --from-block 23990000 \
    --max-addresses 25 \
    --out graphs/frontend/eoa.timeline.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html as html_lib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, getcontext
from typing import Any, Dict, Iterable, List, Optional, Tuple

getcontext().prec = 80

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)
CACHE = os.path.join(ROOT, "cache", "eoa_timeline")
os.makedirs(CACHE, exist_ok=True)

DEFAULT_ENV = "/Users/link/podotree/.env"
ZERO = "0x0000000000000000000000000000000000000000"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
MIN_DFS_NATIVE_WEI = 10**15

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def norm_addr(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if not value.startswith("0x"):
        value = "0x" + value
    return value.lower()


def is_addr(value: str) -> bool:
    return bool(ADDRESS_RE.match(value or ""))


def norm_token(value: str) -> str:
    value = (value or "").strip().lower()
    if value == "native:eth":
        return value
    return norm_addr(value)


def short_addr(addr: str) -> str:
    a = norm_addr(addr)
    return a[:6] + "..." + a[-4:] if len(a) == 42 else addr


def load_env(path: str = DEFAULT_ENV) -> Dict[str, str]:
    env = dict(os.environ)
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


ENV = load_env()
ETHERSCAN_API_KEY = ENV.get("ETHERSCAN_API_KEY", "")
ALCHEMY_API_KEY = ENV.get("ALCHEMY_API_KEY", "")
RPC_URL = ENV.get("ETH_RPC") or ENV.get("ALCHEMY_RPC") or ENV.get("RPC_URL") or ""
ALCHEMY_URL = ENV.get("ALCHEMY_URL") or (f"https://eth-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}" if ALCHEMY_API_KEY else "")
ALCHEMY_TRANSFER_MAX_PAGES = int(ENV.get("EOA_FLOW_ALCHEMY_MAX_PAGES", "2") or "2")


def cache_path(key: str) -> str:
    digest = hashlib.sha256(key.encode()).hexdigest()
    return os.path.join(CACHE, digest + ".json")


def cache_get(key: str) -> Optional[Any]:
    path = cache_path(key)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def cache_put(key: str, value: Any) -> None:
    with open(cache_path(key), "w") as f:
        json.dump(value, f, ensure_ascii=False)


def http_json(url: str, body: Optional[dict] = None, *, timeout: int = 60) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "content-type": "application/json",
            "user-agent": "defi-dagggg-eoa-timeline",
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
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


def http_text(url: str, *, timeout: int = 60) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "user-agent": "Mozilla/5.0 defi-dagggg-eoa-timeline",
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "ignore")
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


def rpc(method: str, params: list) -> Any:
    if not RPC_URL:
        raise RuntimeError("ETH_RPC/ALCHEMY_RPC/RPC_URL is not configured")
    key = "rpc:" + method + ":" + json.dumps(params, sort_keys=True)
    cached = cache_get(key)
    if cached is not None:
        return cached
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    result = http_json(RPC_URL, payload, timeout=90)
    if "error" in result:
        raise RuntimeError(f"{method}: {result['error']}")
    cache_put(key, result["result"])
    return result["result"]


def alchemy_rpc(method: str, params: list) -> Any:
    if not ALCHEMY_URL:
        raise RuntimeError("ALCHEMY_API_KEY/ALCHEMY_URL is not configured")
    key = "alchemy:" + method + ":" + json.dumps(params, sort_keys=True)
    cached = cache_get(key)
    if cached is not None:
        return cached
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    result = http_json(ALCHEMY_URL, payload, timeout=90)
    if "error" in result:
        raise RuntimeError(f"{method}: {result['error']}")
    cache_put(key, result["result"])
    return result["result"]


def latest_block() -> int:
    return int(rpc("eth_blockNumber", []), 16)


def etherscan_account(
    action: str,
    address: str,
    start_block: int,
    end_block: int,
    *,
    offset: int = 10000,
) -> List[dict]:
    if not ETHERSCAN_API_KEY:
        raise RuntimeError("ETHERSCAN_API_KEY is not configured")
    address = norm_addr(address)
    key = f"etherscan:{action}:{address}:{start_block}:{end_block}:{offset}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    out: List[dict] = []
    page = 1
    while True:
        params = {
            "chainid": "1",
            "module": "account",
            "action": action,
            "address": address,
            "startblock": str(start_block),
            "endblock": str(end_block),
            "page": str(page),
            "offset": str(offset),
            "sort": "asc",
            "apikey": ETHERSCAN_API_KEY,
        }
        url = "https://api.etherscan.io/v2/api?" + urllib.parse.urlencode(params)
        raw = http_json(url, timeout=90)
        result = raw.get("result")
        message = str(raw.get("message") or "").lower()
        if raw.get("status") == "0" and ("no transactions" in message or result == []):
            break
        if not isinstance(result, list):
            raise RuntimeError(f"Etherscan {action} failed for {address}: {raw}")
        out.extend(result)
        if len(result) < offset:
            break
        page += 1
        time.sleep(0.22)
    cache_put(key, out)
    return out


def etherscan_contract_name(address: str) -> str:
    if not ETHERSCAN_API_KEY:
        return ""
    address = norm_addr(address)
    if not is_addr(address) or address == ZERO:
        return ""
    key = "contract-name:" + address
    cached = cache_get(key)
    if cached is not None:
        return cached
    params = {
        "chainid": "1",
        "module": "contract",
        "action": "getsourcecode",
        "address": address,
        "apikey": ETHERSCAN_API_KEY,
    }
    url = "https://api.etherscan.io/v2/api?" + urllib.parse.urlencode(params)
    try:
        raw = http_json(url, timeout=60)
        row = (raw.get("result") or [{}])[0]
        name = row.get("ContractName") or ""
        impl = norm_addr(row.get("Implementation") or "")
        if row.get("Proxy") == "1" and is_addr(impl):
            impl_name = etherscan_contract_name(impl)
            if impl_name and impl_name != name:
                name = f"{name}->{impl_name}" if name else impl_name
    except Exception:
        name = ""
    cache_put(key, name)
    time.sleep(0.22)
    return name


def tx_receipt(tx_hash: str) -> Optional[dict]:
    if not RPC_URL:
        return None
    tx_hash = tx_hash.lower()
    key = "receipt:" + tx_hash
    cached = cache_get(key)
    if cached is not None:
        return cached
    try:
        receipt = rpc("eth_getTransactionReceipt", [tx_hash])
    except Exception:
        return None
    cache_put(key, receipt)
    return receipt


def contract_code(address: str) -> str:
    address = norm_addr(address)
    if not is_addr(address):
        return "0x"
    key = "code:" + address
    cached = cache_get(key)
    if cached is not None:
        return cached
    try:
        code = rpc("eth_getCode", [address, "latest"]) or "0x"
    except Exception:
        code = "0x"
    cache_put(key, code)
    return code


def wallet_kind(address: str, *, resolve_safe_name: bool = True) -> str:
    address = norm_addr(address)
    if not is_addr(address) or address == ZERO:
        return "other"
    key = f"wallet-kind:v3:{'full' if resolve_safe_name else 'fast'}:{address}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    code = contract_code(address)
    if code in ("0x", "0x0", ""):
        cache_put(key, "EOA")
        return "EOA"
    if not resolve_safe_name:
        cache_put(key, "contract")
        return "contract"
    name = etherscan_contract_name(address).lower()
    if "safe" in name or "gnosis" in name or "multisig" in name:
        cache_put(key, "safe")
        return "safe"
    cache_put(key, "contract")
    return "contract"


def topic_to_addr(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def hex_to_int(value: str) -> int:
    if not value or value == "0x":
        return 0
    return int(value, 16)


def decimal_amount(raw: str, decimals: int) -> str:
    try:
        scale = Decimal(10) ** Decimal(decimals)
        val = Decimal(raw) / scale
        return format(val.normalize(), "f")
    except (InvalidOperation, ValueError):
        return raw


def maybe_float(amount: str) -> Optional[float]:
    try:
        return float(Decimal(amount))
    except Exception:
        return None


KNOWN_LABELS = {
    ZERO: "mint/burn",
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf".lower(): "cbBTC",
    "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2": "Aave V3 Pool",
    "0xc13e21b648a5ee794902342038ff3adab66be987": "Spark Pool",
    "0x888888888889758f76e7103c6cbf23abbf58f946": "Pendle Router V4",
    "0x6a000f20005980200259b80c5102003040001068": "ParaSwap AugustusV6",
    "0xcf5540fffcdc3d510b18bfca6d2b9987b0772559": "Odos Router V2",
    "0x111111125421ca6dc452d289314280a0f8842a65": "1inch AggregationRouterV6",
    "0x6131b5fae19ea4f9d964eac0408e4408b66337b5": "Kyber MetaAggregationRouterV2",
    "0xac0cfa7742069a8af0c63e14ffd0fe6b3e1bf8d2": "Yield Basis old yb-cbBTC LT",
    "0x722fc3640ba007c3e9867ccdb0dca59f2e2f29f9": "Yield Basis new yb-cbBTC LT",
    "0xf3081a2eb8927c0462864ec3fdbe927c842a0893": "Yield Basis old yb-cbBTC Gauge",
    "0xf8764cbcdb15a9e4c7ca1b0b8a578d9ebeec1b6f": "Yield Basis new yb-cbBTC Gauge",
    "0xdfd6fe3a540f68601002e889e33117a7e8a0669d": "Yield Basis LTMigrator",
    "0xd19d4b5d358258f05d7b411e21a1460d11b0876f": "Linea Rollup",
    "0x81d40f21f12a8f0e3252bccb954d722d4c464b64": "CCTP MessageTransmitterV2",
    "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d": "CCTP TokenMessengerV2",
    "0x88ff1e5b602916615391f55854588efcbb7663f0": "Optimism StandardBridge",
    "0x03d1ec0d01b659b89a87eabb56e4af5cb6e14bfc": "9Summits flagship USDC",
    "0xdcd0f5ab30856f28385f641580bbd85f88349124": "alUSD vault/token",
    "0xfe6eb3b609a7c8352a241f7f3a21cea4e9209b8f": "Spark ETH vault/receipt",
    "0xb753366082466c4b5984312f0c4bb97554be067e": "f(x) / fxUSD router",
}

DFS_TOKEN_ALLOWLIST = {
    # Native / canonical majors and assets this graph is meant to follow.
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
    "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
    "0xdc035d45d973e3ec169d2276ddab16f1e407384f": "USDS",
    "0x4c9edd5852cd905f086c759e8383e09bff1e68b3": "USDe",
    "0x9d39a5de30e57443bff2a8307a4256c8797a3497": "sUSDe",
    "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0": "wstETH",
    "0xae7ab96520de3a18e5e111b5eaab095312d7fe84": "stETH",
    "0xcd5fe23c85820f7b72d0926fc9b05b43e359b7ee": "weETH",
    "0xa1290d69c65a6fe4df752f95823fae25cb99e5a7": "rsETH",
    "0xbf5495efe5db9ce00f80364c8b423567e58d2110": "ezETH",
    "0xae78736cd615f374d3085123a210448e74fc6393": "rETH",
    "0xbe9895146f7af43049ca1c1ae358b0541ea49704": "cbETH",
    "0xa35b1b31ce002fbf2058d22f30f95d405200a15b": "ETHx",
    "0xf1c9acdc66974dfb6decb12aa385b9cd01190e38": "osETH",
    "0xd9a442856c234a39a81a089c06451ebaa4306a72": "pufETH",
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "WBTC",
    "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf": "cbBTC",
    "0x8236a87084f8b84306f72007f36f2618a5634494": "LBTC",
    "0x657e8c867d8b37dcc18fa4caead9c45eb088c642": "eBTC",
    "0x18084fba666a33d37592fa2633fd49a74dd93a88": "tBTC",
    # Lending receipt/debt tokens relevant to exploit unwinds can be followed as
    # details, but only when explicitly known.
    "0x2d62109243b87c4ba3ee7ba1d91b0dd0a074d7b1": "aEthrsETH",
}

TOKEN_REPUTATION_ALLOW = {"ok", "neutral"}
TOKEN_REPUTATION_BLOCK_TERMS = {
    "fake",
    "phishing",
    "scam",
    "spam",
    "suspicious",
    "unsafe",
    "malicious",
    "impersonat",
}


def is_low_signal_token_symbol(symbol: str) -> bool:
    s = (symbol or "").strip()
    if not s:
        return True
    if not all(32 <= ord(ch) <= 126 for ch in s):
        return True
    normalized = re.sub(r"[\s_\-]+", " ", s.lower()).strip()
    return normalized in {
        "token",
        "tkn",
        "erc20",
        "unknown",
        "unknown token",
        "claim",
        "airdrop",
        "reward",
        "rewards",
        "voucher",
    }


def etherscan_token_reputation(token: str) -> Dict[str, Any]:
    token = norm_addr(token)
    if not is_addr(token):
        return {"reputation": "", "holders": None, "suspicious": True, "reason": "invalid_token"}
    key = "etherscan-token-reputation:v2:" + token
    cached = cache_get(key)
    if cached is not None:
        return cached

    out: Dict[str, Any] = {
        "reputation": "",
        "holders": None,
        "suspicious": False,
        "reason": "",
        "title": "",
        "description": "",
    }
    try:
        page = http_text(f"https://etherscan.io/token/{token}", timeout=45)
    except Exception as exc:
        out.update(reason=f"etherscan_page_error:{type(exc).__name__}")
        cache_put(key, out)
        return out

    desc_match = re.search(
        r"<meta\s+name=[\"']Description[\"']\s+content=[\"']([^\"']*)",
        page,
        re.IGNORECASE,
    )
    if desc_match:
        out["description"] = html_lib.unescape(desc_match.group(1)).strip()

    title_match = re.search(
        r"id=[\"']ContentPlaceHolder1_spanReputation[\"'].*?title=([\"'])(.*?)\1",
        page,
        re.IGNORECASE | re.DOTALL,
    )
    if title_match:
        title = re.sub(r"<[^>]+>", " ", title_match.group(2))
        out["title"] = html_lib.unescape(re.sub(r"\s+", " ", title)).strip()

    text = " | ".join(str(out.get(k) or "") for k in ("description", "title"))
    rep_match = re.search(r"Token Rep:\s*([^|<]+)", text, re.IGNORECASE)
    if not rep_match:
        rep_match = re.search(r"Reputation\s+([A-Za-z _-]+)\s*:", text, re.IGNORECASE)
    if rep_match:
        out["reputation"] = re.sub(r"\s+", " ", rep_match.group(1)).strip().upper()

    holders_match = re.search(r"Holders:\s*([0-9,]+)", text, re.IGNORECASE)
    if holders_match:
        try:
            out["holders"] = int(holders_match.group(1).replace(",", ""))
        except ValueError:
            out["holders"] = None

    lowered = text.lower()
    hit = next((term for term in TOKEN_REPUTATION_BLOCK_TERMS if term in lowered), "")
    if hit:
        out.update(suspicious=True, reason=f"etherscan_reputation:{hit}")

    cache_put(key, out)
    time.sleep(0.18)
    return out


def dfs_token_allowed(token: str, symbol: str = "", name: str = "") -> bool:
    token = norm_addr(token)
    if token in DFS_TOKEN_ALLOWLIST:
        return True
    if not is_addr(token):
        return False
    if is_low_signal_token_symbol(symbol) or ((name or "").strip() and is_low_signal_token_symbol(name)):
        return False

    reputation = etherscan_token_reputation(token)
    if reputation.get("suspicious"):
        return False

    rep = str(reputation.get("reputation") or "").strip().lower()
    if rep in TOKEN_REPUTATION_ALLOW:
        return True

    holders = reputation.get("holders")
    contract_name = etherscan_contract_name(token)
    if rep == "unknown" and isinstance(holders, int) and holders >= 1000 and contract_name:
        return True

    return False


def label_address(address: str) -> str:
    address = norm_addr(address)
    if not address:
        return ""
    if address in KNOWN_LABELS:
        return KNOWN_LABELS[address]
    name = etherscan_contract_name(address)
    return name or short_addr(address)


def cheap_label_address(address: str) -> str:
    address = norm_addr(address)
    if not address:
        return ""
    return KNOWN_LABELS.get(address) or short_addr(address)


SELECTOR_NAMES = {
    "0x617ba037": "supply(address,uint256,address,uint16)",
    "0xa415bcad": "borrow(address,uint256,uint256,uint16,address)",
    "0x573ade81": "repay(address,uint256,uint256,address)",
    "0x69328dec": "withdraw(address,uint256,address)",
    "0x474cf53d": "depositETH(address,address,uint16)",
    "0x85b77f45": "requestDeposit(uint256,address,address)",
    "0x5cfe2fe4": "claimSharesAndRequestRedeem(uint256)",
    "0xba087652": "redeem(uint256,address,address)",
    "0x2e2d2984": "deposit(uint256,address,address)",
    "0x9b8d6d38": "deposit(uint256,address,uint16)",
    "0xb460af94": "withdraw(uint256,address,address)",
    "0x00aeef8a": "deposit(uint256,uint256,uint256)",
    "0x6e553f65": "deposit(uint256,address)",
    "0x21c0b342": "claim(address,address)",
    "0x70ac14c6": "migrate_staked(address,address,uint256,uint256)",
    "0xc81f847a": "swapExactTokenForPt(...)",
    "0xf06a07a0": "exitPostExpToToken(...)",
    "0x594a88cc": "swapExactPtForToken(...)",
    "0xe3ead59e": "swapExactAmountIn(...)",
    "0x987e7d8e": "swapExactAmountInOutOnMakerPSM(...)",
    "0x1a01c532": "swapExactAmountInOnCurveV1(...)",
    "0xe37ed256": "swapExactAmountInOnCurveV2(...)",
    "0x876a02f6": "swapExactAmountInOnUniswapV3(...)",
    "0xda35bb0d": "swapOnAugustusRFQTryBatchFill(...)",
    "0x83bd37f9": "swapCompact()",
    "0x07ed2379": "swap(...)",
    "0xe21fd0e9": "swap(tuple)",
    "0x9f3ce55a": "sendMessage(address,uint256,bytes)",
    "0x6463fb2a": "claimMessageWithProof(tuple)",
    "0x57ecfd28": "receiveMessage(bytes,bytes)",
    "0x8e0250ee": "depositForBurn(uint256,uint32,bytes32,address,bytes32,uint256,uint32)",
    "0xe11013dd": "bridgeETHTo(address,uint32,bytes)",
    "0x609ea081": "depositNative(...)",
    "0x216d5108": "borrowFromLong(...)",
    "0x0d8aea82": "repayToLong(...)",
    "0xbf4e5936": "repayToLongAndZapOut(...)",
    "0xd0e30db0": "deposit()",
    "0x2e1a7d4d": "withdraw(uint256)",
    "0xa9059cbb": "transfer(address,uint256)",
    "0x095ea7b3": "approve(address,uint256)",
}


AAVE_SPARK_POOLS = {
    "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2": "Aave V3",
    "0xc13e21b648a5ee794902342038ff3adab66be987": "Spark",
    "0x4e033931ad43597d96d6bcc25c280717730b58b1": "Aave Lido",
}

AGGREGATORS = {
    "0x6a000f20005980200259b80c5102003040001068": "ParaSwap",
    "0xcf5540fffcdc3d510b18bfca6d2b9987b0772559": "Odos",
    "0x111111125421ca6dc452d289314280a0f8842a65": "1inch",
    "0x6131b5fae19ea4f9d964eac0408e4408b66337b5": "Kyber",
}

BRIDGE_TARGETS = {
    "0xd19d4b5d358258f05d7b411e21a1460d11b0876f": "Linea",
    "0x81d40f21f12a8f0e3252bccb954d722d4c464b64": "CCTP",
    "0x28b5a0e9c621a5badaa536219b3a228c8168cf5d": "CCTP",
    "0x88ff1e5b602916615391f55854588efcbb7663f0": "Optimism",
    "0x470458c91978d2d929704489ad730dc3e3001113": "Optimism",
    "0xd5ec14a83b7d95be1e2ac12523e2dee12cbeea6c": "Optimism",
    "0x10d8b8daa26d307489803e10477de69c0492b610": "Across",
}

YIELD_BASIS_TARGETS = {
    "0xac0cfa7742069a8af0c63e14ffd0fe6b3e1bf8d2",
    "0x722fc3640ba007c3e9867ccdb0dca59f2e2f29f9",
    "0xf3081a2eb8927c0462864ec3fdbe927c842a0893",
    "0xf8764cbcdb15a9e4c7ca1b0b8a578d9ebeec1b6f",
    "0xdfd6fe3a540f68601002e889e33117a7e8a0669d",
}

VAULT_TARGETS = {
    "0x03d1ec0d01b659b89a87eabb56e4af5cb6e14bfc": "9SUSDC",
    "0xdcd0f5ab30856f28385f641580bbd85f88349124": "alUSD",
    "0xfe6eb3b609a7c8352a241f7f3a21cea4e9209b8f": "Spark ETH vault",
}


def classify_call(to_addr: str, method_id: str, function_name: str = "") -> Dict[str, Any]:
    to_addr = norm_addr(to_addr)
    method_id = (method_id or "0x").lower()
    fn = function_name or SELECTOR_NAMES.get(method_id, "")

    out = {
        "category": "other_call",
        "protocol": cheap_label_address(to_addr) if to_addr else "",
        "action": SELECTOR_NAMES.get(method_id) or (fn.split("(")[0] if fn else method_id),
        "priority": 90,
        "needs_receipt": False,
        "notes": [],
    }

    if not to_addr:
        out.update(category="contract_creation", action="contract_creation", priority=80)
        return out

    if to_addr in AAVE_SPARK_POOLS:
        venue = AAVE_SPARK_POOLS[to_addr]
        actions = {
            "0x617ba037": "supply",
            "0xa415bcad": "borrow",
            "0x573ade81": "repay",
            "0x69328dec": "withdraw",
        }
        out.update(
            category="lending",
            protocol=venue,
            action=actions.get(method_id, SELECTOR_NAMES.get(method_id, "pool_call")),
            priority=10,
            needs_receipt=True,
        )
        return out

    if method_id == "0x474cf53d":
        out.update(category="lending", protocol="Aave/Spark WETH Gateway", action="depositETH", priority=10, needs_receipt=True)
        return out

    if to_addr in YIELD_BASIS_TARGETS:
        actions = {
            "0x00aeef8a": "lt_deposit",
            "0x6e553f65": "gauge_deposit",
            "0x21c0b342": "gauge_claim",
            "0x70ac14c6": "migrate_staked",
            "0xba087652": "gauge_redeem",
            "0x095ea7b3": "approve",
        }
        out.update(
            category="yield_basis",
            protocol="Yield Basis",
            action=actions.get(method_id, SELECTOR_NAMES.get(method_id, "yield_basis_call")),
            priority=20,
            needs_receipt=True,
        )
        return out

    if to_addr in VAULT_TARGETS or method_id in {"0x85b77f45", "0x5cfe2fe4", "0xba087652", "0x2e2d2984", "0x9b8d6d38", "0xb460af94"}:
        out.update(
            category="vault",
            protocol=VAULT_TARGETS.get(to_addr) or label_address(to_addr),
            action=SELECTOR_NAMES.get(method_id, fn.split("(")[0] if fn else method_id),
            priority=25,
            needs_receipt=True,
        )
        return out

    if to_addr == "0x888888888889758f76e7103c6cbf23abbf58f946":
        out.update(category="pendle", protocol="Pendle", action=SELECTOR_NAMES.get(method_id, "pendle_call"), priority=30, needs_receipt=True)
        return out

    if to_addr in AGGREGATORS or method_id in {"0xe3ead59e", "0x987e7d8e", "0x1a01c532", "0xe37ed256", "0x876a02f6", "0xda35bb0d", "0x83bd37f9", "0x07ed2379", "0xe21fd0e9"}:
        out.update(
            category="swap",
            protocol=AGGREGATORS.get(to_addr) or label_address(to_addr),
            action=SELECTOR_NAMES.get(method_id, "swap"),
            priority=35,
            needs_receipt=True,
        )
        return out

    if to_addr in BRIDGE_TARGETS or method_id in {"0x9f3ce55a", "0x6463fb2a", "0x57ecfd28", "0x8e0250ee", "0xe11013dd", "0x609ea081"}:
        out.update(
            category="bridge",
            protocol=BRIDGE_TARGETS.get(to_addr) or label_address(to_addr),
            action=SELECTOR_NAMES.get(method_id, "bridge_call"),
            priority=40,
            needs_receipt=True,
        )
        return out

    if to_addr == "0xb753366082466c4b5984312f0c4bb97554be067e" or method_id in {"0x216d5108", "0x0d8aea82", "0xbf4e5936"}:
        out.update(
            category="fx_long",
            protocol="f(x) / fxUSD",
            action=SELECTOR_NAMES.get(method_id, "fx_call"),
            priority=45,
            needs_receipt=True,
        )
        return out

    if to_addr == "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2":
        actions = {
            "0xd0e30db0": "wrap_eth",
            "0x2e1a7d4d": "unwrap_weth",
            "0xa9059cbb": "transfer_weth",
            "0x095ea7b3": "approve_weth",
        }
        out.update(category="weth", protocol="WETH", action=actions.get(method_id, "weth_call"), priority=70)
        return out

    if method_id == "0x095ea7b3":
        out.update(category="approval", action="approve", priority=85)
        return out

    if method_id == "0xa9059cbb":
        out.update(category="token_call", action="transfer", priority=75)
        return out

    return out


def token_transfer_from_row(row: dict, eoa: str) -> Dict[str, Any]:
    decimals = int(row.get("tokenDecimal") or 0)
    raw_value = row.get("value") or "0"
    amount = decimal_amount(raw_value, decimals)
    from_addr = norm_addr(row.get("from") or ZERO)
    to_addr = norm_addr(row.get("to") or ZERO)
    eoa = norm_addr(eoa)
    direction = "in" if to_addr == eoa else "out" if from_addr == eoa else "internal"
    return {
        "token": norm_addr(row.get("contractAddress") or ""),
        "symbol": row.get("tokenSymbol") or "",
        "name": row.get("tokenName") or "",
        "decimals": decimals,
        "value_raw": raw_value,
        "amount": amount,
        "amount_float": maybe_float(amount),
        "from": from_addr,
        "to": to_addr,
        "direction": direction,
    }


def event_category_from_transfers(transfers: List[dict]) -> Tuple[str, str]:
    if not transfers:
        return "unknown", "no_token_transfer"
    dirs = {t["direction"] for t in transfers}
    if dirs == {"in"}:
        if any(t["from"] == ZERO for t in transfers):
            return "token_mint", "mint"
        return "token_receive", "receive"
    if dirs == {"out"}:
        if any(t["to"] == ZERO for t in transfers):
            return "token_burn", "burn"
        return "token_send", "send"
    return "token_rebalance", "mixed_transfer"


def receipt_transfer_logs(tx_hash: str, token_meta: Dict[str, dict]) -> List[dict]:
    receipt = tx_receipt(tx_hash)
    if not receipt:
        return []
    out: List[dict] = []
    for log in receipt.get("logs", []):
        topics = log.get("topics") or []
        if len(topics) < 3 or topics[0].lower() != TRANSFER_TOPIC:
            continue
        token = norm_addr(log.get("address") or "")
        meta = token_meta.get(token, {})
        decimals = int(meta.get("decimals", 0) or 0)
        raw_int = hex_to_int(log.get("data") or "0x0")
        if raw_int <= 0:
            continue
        raw = str(raw_int)
        amount = decimal_amount(raw, decimals) if decimals else raw
        out.append(
            {
                "token": token,
                "symbol": meta.get("symbol", ""),
                "decimals": decimals,
                "value_raw": raw,
                "amount": amount,
                "amount_float": maybe_float(amount) if decimals else None,
                "from": topic_to_addr(topics[1]),
                "to": topic_to_addr(topics[2]),
                "log_index": int(log.get("logIndex", "0x0"), 16),
            }
        )
    return out


def event_time(timestamp: int) -> str:
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_eoa_timeline(
    address: str,
    start_block: int,
    end_block: int,
    *,
    receipt_mode: str = "important",
    max_receipts: int = 200,
) -> Dict[str, Any]:
    address = norm_addr(address)
    normal_txs = etherscan_account("txlist", address, start_block, end_block)
    token_txs = etherscan_account("tokentx", address, start_block, end_block)

    token_meta: Dict[str, dict] = {}
    for row in token_txs:
        token = norm_addr(row.get("contractAddress") or "")
        if not token:
            continue
        token_meta[token] = {
            "symbol": row.get("tokenSymbol") or "",
            "name": row.get("tokenName") or "",
            "decimals": int(row.get("tokenDecimal") or 0),
        }

    grouped: Dict[str, Dict[str, Any]] = {}

    def ensure_event(tx_hash: str, block: int, timestamp: int, tx_index: int) -> Dict[str, Any]:
        ev = grouped.setdefault(
            tx_hash,
            {
                "address": address,
                "tx_hash": tx_hash,
                "block_number": block,
                "timestamp": timestamp,
                "datetime_utc": event_time(timestamp),
                "transaction_index": tx_index,
                "call": None,
                "transfers": [],
                "receipt_transfers": [],
            },
        )
        ev["block_number"] = min(ev["block_number"], block)
        ev["timestamp"] = min(ev["timestamp"], timestamp)
        ev["datetime_utc"] = event_time(ev["timestamp"])
        ev["transaction_index"] = min(ev["transaction_index"], tx_index)
        return ev

    for tx in normal_txs:
        tx_hash = (tx.get("hash") or "").lower()
        if not tx_hash:
            continue
        block = int(tx.get("blockNumber") or 0)
        timestamp = int(tx.get("timeStamp") or 0)
        tx_index = int(tx.get("transactionIndex") or 0)
        ev = ensure_event(tx_hash, block, timestamp, tx_index)
        if norm_addr(tx.get("from") or "") == address:
            method_id = (tx.get("methodId") or "0x").lower()
            to_addr = norm_addr(tx.get("to") or "")
            semantic = classify_call(to_addr, method_id, tx.get("functionName") or "")
            ev["call"] = {
                "from": address,
                "to": to_addr,
                "target_label": label_address(to_addr) if to_addr else "",
                "method_id": method_id,
                "function_name": tx.get("functionName") or SELECTOR_NAMES.get(method_id, ""),
                "value_wei": tx.get("value") or "0",
                "gas_used": int(tx.get("gasUsed") or 0),
                "is_error": tx.get("isError") == "1" or tx.get("txreceipt_status") == "0",
                "semantic": semantic,
            }

    for row in token_txs:
        tx_hash = (row.get("hash") or "").lower()
        if not tx_hash:
            continue
        try:
            if int(row.get("value") or "0") <= 0:
                continue
        except (TypeError, ValueError):
            continue
        block = int(row.get("blockNumber") or 0)
        timestamp = int(row.get("timeStamp") or 0)
        tx_index = int(row.get("transactionIndex") or 0)
        ev = ensure_event(tx_hash, block, timestamp, tx_index)
        ev["transfers"].append(token_transfer_from_row(row, address))

    receipt_budget = max_receipts
    for ev in grouped.values():
        semantic = ((ev.get("call") or {}).get("semantic") or {})
        should_fetch = False
        if receipt_mode == "all":
            should_fetch = True
        elif receipt_mode == "important":
            should_fetch = bool(semantic.get("needs_receipt"))
        if should_fetch and receipt_budget > 0:
            ev["receipt_transfers"] = receipt_transfer_logs(ev["tx_hash"], token_meta)
            receipt_budget -= 1

    events: List[dict] = []
    for idx, ev in enumerate(sorted(grouped.values(), key=lambda e: (e["block_number"], e["transaction_index"], e["tx_hash"]))):
        call_sem = ((ev.get("call") or {}).get("semantic") or {})
        if call_sem:
            category = call_sem["category"]
            action = call_sem["action"]
            priority = call_sem["priority"]
            protocol = call_sem["protocol"]
        else:
            category, action = event_category_from_transfers(ev["transfers"])
            priority = 65 if category.startswith("token_") else 90
            protocol = ""
        ev["event_id"] = f"{address}:{ev['block_number']}:{ev['transaction_index']}:{idx}"
        ev["category"] = category
        ev["action"] = action
        ev["priority"] = priority
        ev["protocol"] = protocol
        ev["transfer_count"] = len(ev["transfers"])
        ev["receipt_transfer_count"] = len(ev["receipt_transfers"])
        events.append(ev)

    summary = {
        "address": address,
        "tx_count": len(normal_txs),
        "token_transfer_count": len(token_txs),
        "event_count": len(events),
        "category_counts": dict(Counter(e["category"] for e in events)),
        "first_block": events[0]["block_number"] if events else None,
        "last_block": events[-1]["block_number"] if events else None,
        "first_seen_utc": events[0]["datetime_utc"] if events else None,
        "last_seen_utc": events[-1]["datetime_utc"] if events else None,
    }
    return {"summary": summary, "events": events}


def node_type_for_category(category: str) -> str:
    if category in {"lending"}:
        return "lending_protocol"
    if category in {"swap", "pendle"}:
        return "dex_or_router"
    if category in {"vault", "yield_basis"}:
        return "vault_or_strategy"
    if category in {"bridge"}:
        return "bridge"
    if category in {"fx_long"}:
        return "cdp_or_leverage"
    return "address"


def add_node(nodes: Dict[str, dict], address: str, *, label: Optional[str] = None, kind: str = "address") -> None:
    address = norm_addr(address)
    if not is_addr(address):
        return
    existing = nodes.setdefault(
        address,
        {
            "id": address,
            "type": kind,
            "label": label or label_address(address),
            "data": {"address": address, "kind": kind},
        },
    )
    if existing["type"] == "address" and kind != "address":
        existing["type"] = kind
        existing["data"]["kind"] = kind
    if label and existing["label"] == short_addr(address):
        existing["label"] = label


def build_graph(address_payloads: Dict[str, dict], *, include_receipt_edges: bool) -> Dict[str, Any]:
    nodes: Dict[str, dict] = {}
    edges: List[dict] = []
    edge_counter = 0

    for address, payload in address_payloads.items():
        add_node(nodes, address, label=f"EOA {short_addr(address)}", kind="EOA")
        for ev in payload["events"]:
            call = ev.get("call")
            if call and is_addr(call.get("to", "")):
                target = norm_addr(call["to"])
                add_node(
                    nodes,
                    target,
                    label=call.get("target_label") or ev.get("protocol") or label_address(target),
                    kind=node_type_for_category(ev["category"]),
                )
                edges.append(
                    {
                        "id": f"eoa-call-{edge_counter}",
                        "source": address,
                        "target": target,
                        "edge_type": "call",
                        "category": ev["category"],
                        "action": ev["action"],
                        "protocol": ev.get("protocol", ""),
                        "tx_hash": ev["tx_hash"],
                        "block_number": ev["block_number"],
                        "timestamp": ev["timestamp"],
                        "event_id": ev["event_id"],
                    }
                )
                edge_counter += 1
            for tr in ev.get("transfers", []):
                src = norm_addr(tr["from"])
                dst = norm_addr(tr["to"])
                add_node(nodes, src, kind="address")
                add_node(nodes, dst, kind="address")
                edges.append(
                    {
                        "id": f"eoa-transfer-{edge_counter}",
                        "source": src,
                        "target": dst,
                        "edge_type": "token_transfer",
                        "category": ev["category"],
                        "action": ev["action"],
                        "token": tr["token"],
                        "symbol": tr.get("symbol", ""),
                        "amount": tr.get("amount"),
                        "amount_float": tr.get("amount_float"),
                        "value_raw": tr.get("value_raw"),
                        "direction": tr.get("direction"),
                        "tx_hash": ev["tx_hash"],
                        "block_number": ev["block_number"],
                        "timestamp": ev["timestamp"],
                        "event_id": ev["event_id"],
                    }
                )
                edge_counter += 1
            if include_receipt_edges:
                for tr in ev.get("receipt_transfers", []):
                    src = norm_addr(tr["from"])
                    dst = norm_addr(tr["to"])
                    add_node(nodes, src, kind="address")
                    add_node(nodes, dst, kind="address")
                    edges.append(
                        {
                            "id": f"eoa-receipt-transfer-{edge_counter}",
                            "source": src,
                            "target": dst,
                            "edge_type": "receipt_transfer",
                            "category": ev["category"],
                            "action": ev["action"],
                            "token": tr["token"],
                            "symbol": tr.get("symbol", ""),
                            "amount": tr.get("amount"),
                            "amount_float": tr.get("amount_float"),
                            "value_raw": tr.get("value_raw"),
                            "log_index": tr.get("log_index"),
                            "tx_hash": ev["tx_hash"],
                            "block_number": ev["block_number"],
                            "timestamp": ev["timestamp"],
                            "event_id": ev["event_id"],
                        }
                    )
                    edge_counter += 1

    return {"nodes": list(nodes.values()), "edges": edges}


def parse_alchemy_decimal(value: Any) -> int:
    if value is None:
        return 18
    if isinstance(value, int):
        return value
    text = str(value)
    try:
        return int(text, 16) if text.startswith("0x") else int(text)
    except ValueError:
        return 18


def parse_alchemy_block(value: Any) -> int:
    text = str(value or "0")
    try:
        return int(text, 16) if text.startswith("0x") else int(text)
    except ValueError:
        return 0


def parse_alchemy_timestamp(value: Any) -> int:
    if not value:
        return 0
    text = str(value)
    try:
        return int(dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def alchemy_asset_transfers(direction: str, address: str, start_block: int, end_block: int) -> List[dict]:
    if direction not in ("from", "to"):
        raise ValueError("direction must be from or to")
    address = norm_addr(address)
    contracts = sorted(addr for addr in DFS_TOKEN_ALLOWLIST if is_addr(addr))
    contracts_fp = hashlib.sha256(",".join(contracts).encode()).hexdigest()[:10]
    key = f"alchemy-asset-transfers:v3:{direction}:{address}:{start_block}:{end_block}:p{ALCHEMY_TRANSFER_MAX_PAGES}:{contracts_fp}"
    cached = cache_get(key)
    if cached is not None:
        return cached

    out: List[dict] = []
    for category, contract_filter in (("external", None), ("erc20", contracts)):
        page_key = None
        page_count = 0
        base = {
            "fromBlock": hex(start_block),
            "toBlock": hex(end_block),
            "category": [category],
            "withMetadata": True,
            "excludeZeroValue": True,
            "order": "asc",
            "maxCount": hex(1000),
            "fromAddress" if direction == "from" else "toAddress": address,
        }
        if contract_filter:
            base["contractAddresses"] = contract_filter
        while True:
            params = dict(base)
            if page_key:
                params["pageKey"] = page_key
            result = alchemy_rpc("alchemy_getAssetTransfers", [params])
            out.extend(result.get("transfers") or [])
            page_key = result.get("pageKey")
            page_count += 1
            if not page_key or page_count >= ALCHEMY_TRANSFER_MAX_PAGES:
                break
            time.sleep(0.03)

    cache_put(key, out)
    return out


def alchemy_transfer_to_neighbor_row(row: dict, seed: str, relation: str) -> Optional[dict]:
    seed = norm_addr(seed)
    src = norm_addr(row.get("from") or "")
    dst = norm_addr(row.get("to") or "")
    if not src or not dst or src == dst:
        return None
    if relation == "out" and src != seed:
        return None
    if relation == "in" and dst != seed:
        return None

    category = str(row.get("category") or "").lower()
    raw_contract = row.get("rawContract") or {}
    token = norm_addr(raw_contract.get("address") or "")
    symbol = row.get("asset") or "token"
    decimals = parse_alchemy_decimal(raw_contract.get("decimal"))
    raw_value = raw_contract.get("value")
    amount_float = row.get("value") if isinstance(row.get("value"), (int, float)) else None

    if category == "external":
        token = "native:eth"
        symbol = "ETH"
        decimals = 18
    elif not is_addr(token):
        return None

    if raw_value:
        raw_value_text = str(int(raw_value, 16)) if isinstance(raw_value, str) and raw_value.startswith("0x") else str(raw_value)
        amount = decimal_amount(raw_value_text, decimals) if decimals else raw_value_text
        amount_float = maybe_float(amount)
    elif amount_float is not None:
        amount = str(amount_float)
        raw_value_text = ""
    else:
        return None

    if amount_float is not None and amount_float <= 0:
        return None

    timestamp = parse_alchemy_timestamp((row.get("metadata") or {}).get("blockTimestamp"))
    return {
        "tx_hash": (row.get("hash") or "").lower(),
        "block_number": parse_alchemy_block(row.get("blockNum")),
        "timestamp": timestamp,
        "datetime_utc": event_time(timestamp) if timestamp else None,
        "token": token,
        "symbol": symbol,
        "decimals": decimals,
        "value_raw": raw_value_text,
        "amount": amount,
        "amount_float": amount_float,
        "from": src,
        "to": dst,
        "direction": relation,
    }


def discover_wallet_neighbors_alchemy(
    address: str,
    start_block: int,
    end_block: int,
    *,
    directions: str,
    max_neighbors: int,
) -> List[dict]:
    if not ALCHEMY_URL:
        raise RuntimeError("alchemy transfer scan unavailable")
    address = norm_addr(address)
    raw: Dict[Tuple[str, str], dict] = {}
    wanted: List[Tuple[str, str]] = []
    if directions in ("both", "children"):
        wanted.append(("from", "out"))
    if directions in ("both", "parents"):
        wanted.append(("to", "in"))

    for alchemy_direction, relation in wanted:
        for transfer in alchemy_asset_transfers(alchemy_direction, address, start_block, end_block):
            row = alchemy_transfer_to_neighbor_row(transfer, address, relation)
            if not row:
                continue
            token = norm_token(row.get("token") or "")
            symbol = row.get("symbol") or "token"
            if token != "native:eth" and not dfs_token_allowed(token, symbol):
                continue
            neighbor = norm_addr(row.get("to") if relation == "out" else row.get("from"))
            if not neighbor or neighbor == address or neighbor == ZERO:
                continue
            key = (neighbor, relation)
            item = raw.setdefault(
                key,
                {
                    "address": neighbor,
                    "relation": relation,
                    "transfer_count": 0,
                    "first_block": None,
                    "last_block": None,
                    "symbols": set(),
                    "sample_tx": row.get("tx_hash") or "",
                    "transfers": [],
                },
            )
            block = int(row.get("block_number") or 0)
            item["transfer_count"] += 1
            item["first_block"] = block if item["first_block"] is None else min(item["first_block"], block)
            item["last_block"] = block if item["last_block"] is None else max(item["last_block"], block)
            item["symbols"].add(symbol)
            item["transfers"].append(row)
            if block == item["last_block"]:
                item["sample_tx"] = row.get("tx_hash") or item["sample_tx"]

    out = []
    candidates = sorted(
        raw.values(),
        key=lambda x: (-(x["transfer_count"] or 0), -(x["last_block"] or 0), x["address"]),
    )
    for item in candidates:
        kind = wallet_kind(item["address"], resolve_safe_name=False)
        if kind not in ("EOA", "safe"):
            continue
        item["kind"] = kind
        item["symbols"] = sorted(item["symbols"])
        item["transfers"] = sorted(item.get("transfers") or [], key=lambda x: (x.get("block_number") or 0, x.get("tx_hash") or ""))
        out.append(item)
        if max_neighbors > 0 and len(out) >= max_neighbors:
            break
    return sorted(out, key=lambda x: (x["first_block"] or 0, x["address"]))


def discover_wallet_neighbors(
    address: str,
    start_block: int,
    end_block: int,
    *,
    directions: str,
    max_neighbors: int,
) -> List[dict]:
    address = norm_addr(address)
    if ALCHEMY_URL:
        try:
            return discover_wallet_neighbors_alchemy(
                address,
                start_block,
                end_block,
                directions=directions,
                max_neighbors=max_neighbors,
            )
        except Exception as exc:
            print(f"# alchemy transfer scan fallback for {short_addr(address)}: {exc}", file=sys.stderr)
    token_txs = etherscan_account("tokentx", address, start_block, end_block)
    normal_txs = etherscan_account("txlist", address, start_block, end_block)
    raw: Dict[Tuple[str, str], dict] = {}
    include_parents = directions in ("both", "parents")
    include_children = directions in ("both", "children")

    for row in token_txs:
        try:
            if int(row.get("value") or "0") <= 0:
                continue
        except (TypeError, ValueError):
            continue
        src = norm_addr(row.get("from") or "")
        dst = norm_addr(row.get("to") or "")
        if not src or not dst or src == dst:
            continue
        relation = ""
        neighbor = ""
        if include_children and src == address and dst != ZERO:
            relation, neighbor = "out", dst
        elif include_parents and dst == address and src != ZERO:
            relation, neighbor = "in", src
        if not neighbor or neighbor == address:
            continue

        token = norm_addr(row.get("contractAddress") or "")
        symbol = row.get("tokenSymbol") or "token"
        name = row.get("tokenName") or ""
        if not dfs_token_allowed(token, symbol, name):
            continue
        decimals = int(row.get("tokenDecimal") or 0)
        raw_value = row.get("value") or "0"
        amount = decimal_amount(raw_value, decimals) if decimals else raw_value
        timestamp = int(row.get("timeStamp") or 0)
        tx_hash = (row.get("hash") or "").lower()
        key = (neighbor, relation)
        item = raw.setdefault(
            key,
            {
                "address": neighbor,
                "relation": relation,
                "transfer_count": 0,
                "first_block": None,
                "last_block": None,
                "symbols": set(),
                "sample_tx": tx_hash,
                "transfers": [],
            },
        )
        block = int(row.get("blockNumber") or 0)
        item["transfer_count"] += 1
        item["first_block"] = block if item["first_block"] is None else min(item["first_block"], block)
        item["last_block"] = block if item["last_block"] is None else max(item["last_block"], block)
        item["symbols"].add(symbol)
        item["transfers"].append(
            {
                "tx_hash": tx_hash,
                "block_number": block,
                "timestamp": timestamp,
                "datetime_utc": event_time(timestamp) if timestamp else None,
                "token": token,
                "symbol": symbol,
                "decimals": decimals,
                "value_raw": raw_value,
                "amount": amount,
                "amount_float": maybe_float(amount),
                "from": src,
                "to": dst,
                "direction": "out" if src == address else "in",
            }
        )
        if block == item["last_block"]:
            item["sample_tx"] = tx_hash or item["sample_tx"]

    for row in normal_txs:
        try:
            raw_wei = int(row.get("value") or "0")
        except (TypeError, ValueError):
            continue
        if raw_wei < MIN_DFS_NATIVE_WEI:
            continue
        if row.get("isError") == "1" or row.get("txreceipt_status") == "0":
            continue
        src = norm_addr(row.get("from") or "")
        dst = norm_addr(row.get("to") or "")
        if not src or not dst or src == dst:
            continue
        relation = ""
        neighbor = ""
        if include_children and src == address and dst != ZERO:
            relation, neighbor = "out", dst
        elif include_parents and dst == address and src != ZERO:
            relation, neighbor = "in", src
        if not neighbor or neighbor == address:
            continue

        amount = decimal_amount(str(raw_wei), 18)
        timestamp = int(row.get("timeStamp") or 0)
        tx_hash = (row.get("hash") or "").lower()
        key = (neighbor, relation)
        item = raw.setdefault(
            key,
            {
                "address": neighbor,
                "relation": relation,
                "transfer_count": 0,
                "first_block": None,
                "last_block": None,
                "symbols": set(),
                "sample_tx": tx_hash,
                "transfers": [],
            },
        )
        block = int(row.get("blockNumber") or 0)
        item["transfer_count"] += 1
        item["first_block"] = block if item["first_block"] is None else min(item["first_block"], block)
        item["last_block"] = block if item["last_block"] is None else max(item["last_block"], block)
        item["symbols"].add("ETH")
        item["transfers"].append(
            {
                "tx_hash": tx_hash,
                "block_number": block,
                "timestamp": timestamp,
                "datetime_utc": event_time(timestamp) if timestamp else None,
                "token": "native:eth",
                "symbol": "ETH",
                "decimals": 18,
                "value_raw": str(raw_wei),
                "amount": amount,
                "amount_float": maybe_float(amount),
                "from": src,
                "to": dst,
                "direction": "out" if src == address else "in",
            }
        )
        if block == item["last_block"]:
            item["sample_tx"] = tx_hash or item["sample_tx"]

    out = []
    candidates = sorted(
        raw.values(),
        key=lambda x: (-(x["transfer_count"] or 0), -(x["last_block"] or 0), x["address"]),
    )
    for item in candidates:
        kind = wallet_kind(item["address"], resolve_safe_name=False)
        if kind not in ("EOA", "safe"):
            continue
        item["kind"] = kind
        item["symbols"] = sorted(item["symbols"])
        item["transfers"] = sorted(item.get("transfers") or [], key=lambda x: (x.get("block_number") or 0, x.get("tx_hash") or ""))
        out.append(item)
        if max_neighbors > 0 and len(out) >= max_neighbors:
            break
    return sorted(out, key=lambda x: (x["first_block"] or 0, x["address"]))


def discover_wallet_dfs(
    seeds: List[str],
    start_block: int,
    end_block: int,
    *,
    max_depth: int,
    max_addresses: int,
    max_neighbors: int,
    directions: str,
) -> Dict[str, Any]:
    nodes: Dict[str, dict] = {}
    edges: List[dict] = []
    stack: List[Tuple[str, int, str]] = [(seed, 0, "seed") for seed in reversed(seeds)]

    while stack and (max_addresses <= 0 or len(nodes) < max_addresses):
        address, depth, discovered_by = stack.pop()
        address = norm_addr(address)
        if not is_addr(address):
            continue
        existing = nodes.get(address)
        if existing and existing["depth"] <= depth:
            continue
        kind = wallet_kind(address)
        if kind not in ("EOA", "safe"):
            continue
        nodes[address] = {"address": address, "kind": kind, "depth": depth, "discovered_by": discovered_by}
        if depth >= max_depth:
            continue

        neighbors = discover_wallet_neighbors(
            address,
            start_block,
            end_block,
            directions=directions,
            max_neighbors=max_neighbors,
        )
        for nb in reversed(neighbors):
            if max_addresses > 0 and len(nodes) + len(stack) >= max_addresses and nb["address"] not in nodes:
                continue
            source = nb["address"] if nb["relation"] == "in" else address
            target = address if nb["relation"] == "in" else nb["address"]
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "relation": nb["relation"],
                    "symbols": nb["symbols"],
                    "transfer_count": nb["transfer_count"],
                    "first_block": nb["first_block"],
                    "last_block": nb["last_block"],
                    "sample_tx": nb["sample_tx"],
                    "transfers": nb.get("transfers") or [],
                }
            )
            if nb["address"] not in nodes:
                stack.append((nb["address"], depth + 1, nb["relation"]))

    ordered_nodes = sorted(nodes.values(), key=lambda x: (x["depth"], x["address"]))
    return {
        "nodes": ordered_nodes,
        "edges": edges,
        "seeds": seeds,
        "max_depth": max_depth,
        "directions": directions,
    }


def fmt_num(value: Optional[float]) -> str:
    if value is None:
        return ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.2f}k"
    if value >= 10:
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if value >= 0.01:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return f"{value:.6g}"


def token_key(tr: dict) -> str:
    token = norm_token(tr.get("token") or "")
    symbol = tr.get("symbol") or token[:10] or "token"
    return f"{symbol}|{token}"


def aggregate_transfers(transfers: List[dict]) -> List[dict]:
    grouped: Dict[Tuple[str, str], dict] = {}
    for tr in transfers:
        direction = tr.get("direction") or "internal"
        key = (direction, token_key(tr))
        amount = tr.get("amount_float")
        bucket = grouped.setdefault(
            key,
            {
                "direction": direction,
                "token": norm_token(tr.get("token") or ""),
                "symbol": tr.get("symbol") or "token",
                "amount": 0.0,
                "count": 0,
            },
        )
        src = norm_addr(tr.get("from") or "")
        dst = norm_addr(tr.get("to") or "")
        if src:
            bucket["from"] = src if not bucket.get("from") else bucket["from"] if bucket["from"] == src else "multiple"
        if dst:
            bucket["to"] = dst if not bucket.get("to") else bucket["to"] if bucket["to"] == dst else "multiple"
        if isinstance(amount, (int, float)):
            bucket["amount"] += amount
        bucket["count"] += 1
    return sorted(
        grouped.values(),
        key=lambda x: ({"out": 0, "in": 1, "internal": 2}.get(x["direction"], 9), -(x["amount"] or 0), x["symbol"]),
    )


def compact_transfer_label(transfers: List[dict], limit: int = 3) -> str:
    parts = []
    for tr in aggregate_transfers(transfers)[:limit]:
        sign = "-" if tr["direction"] == "out" else "+" if tr["direction"] == "in" else "~"
        amount = fmt_num(tr.get("amount")) if tr.get("amount") else f"{tr['count']}x"
        parts.append(f"{sign}{amount} {tr['symbol']}")
    if len(aggregate_transfers(transfers)) > limit:
        parts.append("...")
    return " · ".join(parts)


def event_short_label(ev: dict) -> str:
    day = str(ev.get("datetime_utc") or "")[:10]
    protocol = ev.get("protocol") or ev.get("category") or "event"
    action = ev.get("action") or ""
    flow = compact_transfer_label(ev.get("transfers") or [])
    lines = [day, f"{protocol}", action]
    if flow:
        lines.append(flow)
    return "\n".join(x for x in lines if x)


def event_detail(ev: dict, address: str, transfers: List[dict]) -> dict:
    return {
        "event_id": ev.get("event_id"),
        "address": address,
        "tx_hash": ev.get("tx_hash"),
        "datetime_utc": ev.get("datetime_utc"),
        "block_number": ev.get("block_number"),
        "category": ev.get("category") or "unknown",
        "protocol": ev.get("protocol") or "",
        "action": ev.get("action") or "",
        "transfers": transfers,
    }


def edge_label_from_details(details: List[dict], fallback: str = "flow") -> str:
    if not details:
        return fallback
    actions = Counter((d.get("action") or d.get("category") or fallback) for d in details)
    action_label = "/".join(k for k, _ in actions.most_common(2))
    transfer_parts = []
    transfer_totals: Dict[Tuple[str, str], dict] = {}
    for d in details:
        for tr in d.get("transfers") or []:
            direction = tr.get("direction") or "internal"
            symbol = tr.get("symbol") or "token"
            key = (direction, symbol)
            bucket = transfer_totals.setdefault(key, {"direction": direction, "symbol": symbol, "amount": 0.0, "count": 0})
            amount = tr.get("amount")
            if isinstance(amount, (int, float)):
                bucket["amount"] += amount
            bucket["count"] += 1
    for tr in sorted(transfer_totals.values(), key=lambda x: ({"out": 0, "in": 1}.get(x["direction"], 9), -x["amount"]))[:2]:
        sign = "-" if tr["direction"] == "out" else "+" if tr["direction"] == "in" else "~"
        amount = fmt_num(tr["amount"]) if tr["amount"] else f"{tr['count']}x"
        transfer_parts.append(f"{sign}{amount} {tr['symbol']}")
    flow = " / ".join(transfer_parts)
    if flow:
        return f"{len(details)} tx | {action_label} | {flow}"
    return f"{len(details)} tx | {action_label}"


def build_eoa_flow_view(
    address_payloads: Dict[str, dict],
    *,
    max_events_per_address: int = 80,
    discovery: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    nodes: Dict[str, dict] = {}
    edge_buckets: Dict[Tuple[str, str, str, str], dict] = {}
    compact_events: List[dict] = []

    addresses = list(address_payloads.keys())
    wallet_addresses = set(addresses)
    discovered_by_addr = {}
    if discovery:
        discovered_by_addr = {
            norm_addr(n.get("address") or ""): n for n in discovery.get("nodes", []) if is_addr(norm_addr(n.get("address") or ""))
        }
    category_counts: Counter[str] = Counter()

    def add_flow_node(node: dict) -> None:
        nodes.setdefault(node["id"], node)

    def add_flow_edge(source: str, target: str, edge_type: str, category: str, detail: Optional[dict] = None, label: Optional[str] = None, tx_hash: Optional[str] = None) -> None:
        key = (source, target, edge_type, category)
        edge = edge_buckets.setdefault(
            key,
            {
                "source": source,
                "target": target,
                "edge_type": edge_type,
                "category": category,
                "label": label or category,
                "tx_hash": tx_hash,
                "details": [],
            },
        )
        if detail:
            edge["details"].append(detail)
            edge["tx_hash"] = detail.get("tx_hash") or edge.get("tx_hash")

    for lane, address in enumerate(addresses):
        payload = address_payloads[address]
        events = payload.get("events") or []
        if max_events_per_address > 0:
            events = events[:max_events_per_address]
        summary = payload.get("summary") or {}
        discovered = discovered_by_addr.get(address, {})
        kind = str(discovered.get("kind") or "EOA")
        wallet_label = "Safe" if kind.lower() == "safe" else "EOA"
        eoa_id = f"eoa:{address}"
        add_flow_node(
            {
                "id": eoa_id,
                "type": "eoa",
                "label": f"{wallet_label} {short_addr(address)}",
                "data": {
                    "kind": "safe" if kind.lower() == "safe" else "eoa",
                    "address": address,
                    "lane": lane,
                    "step": -1,
                    "dfs_depth": discovered.get("depth"),
                    "discovered_by": discovered.get("discovered_by"),
                    "event_count": summary.get("event_count", len(events)),
                    "first_seen_utc": summary.get("first_seen_utc"),
                    "last_seen_utc": summary.get("last_seen_utc"),
                    "category_counts": summary.get("category_counts") or {},
                },
            }
        )
        for ev in events:
            category = ev.get("category") or "unknown"
            category_counts[category] += 1
            call = ev.get("call") or {}
            call_to = norm_addr(call.get("to") or "")
            event_transfers = aggregate_transfers(ev.get("transfers") or [])
            detail = event_detail(ev, address, event_transfers)

            for tr in ev.get("transfers") or []:
                src = norm_addr(tr.get("from") or "")
                dst = norm_addr(tr.get("to") or "")
                if src not in wallet_addresses or dst not in wallet_addresses or src == dst:
                    continue
                token = norm_token(tr.get("token") or "")
                symbol = tr.get("symbol") or "token"
                if not dfs_token_allowed(token, symbol):
                    continue
                amount = maybe_float(tr.get("amount") or "")
                label = f"{fmt_num(amount)} {symbol}" if amount is not None else symbol
                wallet_detail = dict(detail)
                wallet_detail["transfers"] = [
                    {
                        "direction": "out" if src == address else "in",
                        "token": token,
                        "symbol": symbol,
                        "amount": amount,
                        "count": 1,
                    }
                ]
                add_flow_edge(
                    f"eoa:{src}",
                    f"eoa:{dst}",
                    "wallet_move",
                    "wallet_flow",
                    wallet_detail,
                    label=label,
                    tx_hash=ev.get("tx_hash"),
                )

            if call_to:
                protocol_id = f"protocol:{call_to}"
                add_flow_node(
                    {
                        "id": protocol_id,
                        "type": "protocol",
                        "label": call.get("target_label") or ev.get("protocol") or cheap_label_address(call_to),
                        "data": {
                            "kind": "protocol",
                            "category": category,
                            "address": call_to,
                        },
                    }
                )
                add_flow_edge(
                    eoa_id,
                    protocol_id,
                    "protocol_flow",
                    category,
                    detail,
                    label=ev.get("action") or category,
                    tx_hash=ev.get("tx_hash"),
                )
            compact_events.append(
                detail
            )

    if discovery:
        for dnode in discovery.get("nodes", []):
            addr = norm_addr(dnode.get("address") or "")
            if not is_addr(addr):
                continue
            eoa_id = f"eoa:{addr}"
            if eoa_id not in nodes:
                add_flow_node(
                    {
                        "id": eoa_id,
                        "type": "eoa",
                        "label": f"{dnode.get('kind', 'EOA')} {short_addr(addr)}",
                        "data": {
                            "kind": "eoa",
                            "address": addr,
                            "lane": len(nodes),
                            "step": -1,
                            "event_count": 0,
                            "dfs_depth": dnode.get("depth"),
                        },
                    }
                )
        for i, dedge in enumerate(discovery.get("edges", [])):
            src = norm_addr(dedge.get("source") or "")
            dst = norm_addr(dedge.get("target") or "")
            if src not in wallet_addresses or dst not in wallet_addresses:
                continue
            symbols = ",".join(dedge.get("symbols") or [])
            add_flow_edge(
                f"eoa:{src}",
                f"eoa:{dst}",
                "wallet_move",
                "wallet_flow",
                None,
                label=f"{dedge.get('transfer_count', 0)} tx {symbols}".strip(),
                tx_hash=dedge.get("sample_tx"),
            )

    edges = []
    for idx, edge in enumerate(edge_buckets.values()):
        details = sorted(edge.get("details") or [], key=lambda e: (e.get("block_number") or 0, e.get("event_id") or ""))
        edge["details"] = details
        if details:
            edge["label"] = edge_label_from_details(details, edge.get("label") or edge.get("category") or "flow")
        edge["event_count"] = len(details)
        edge["id"] = f"eoa-flow-edge-{idx}"
        edges.append(edge)

    compact_events.sort(key=lambda e: (e.get("block_number") or 0, e.get("event_id") or ""))
    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "events": compact_events,
        "metadata": {
            "source": "feeder/eoa_timeline.py --frontend-flow",
            "view": "eoa_flow",
            "format_version": 2,
            "address_count": len(addresses),
            "event_count": len(compact_events),
            "category_counts": dict(category_counts),
            "max_events_per_address": max_events_per_address,
            "discovery": discovery,
        },
    }


def build_eoa_discovery_flow_view(discovery: Dict[str, Any], *, max_events_per_address: int = 0) -> Dict[str, Any]:
    nodes: Dict[str, dict] = {}
    edges: List[dict] = []
    category_counts: Counter[str] = Counter()

    for lane, dnode in enumerate(discovery.get("nodes", [])):
        addr = norm_addr(dnode.get("address") or "")
        if not is_addr(addr):
            continue
        kind = str(dnode.get("kind") or "EOA").lower()
        wallet_kind = "safe" if kind == "safe" else "eoa"
        label_kind = "Safe" if wallet_kind == "safe" else "EOA"
        nodes[f"eoa:{addr}"] = {
            "id": f"eoa:{addr}",
            "type": "eoa",
            "label": f"{label_kind} {short_addr(addr)}",
            "data": {
                "kind": wallet_kind,
                "address": addr,
                "lane": lane,
                "step": -1,
                "dfs_depth": dnode.get("depth"),
                "discovered_by": dnode.get("discovered_by"),
                "event_count": 0,
                "category_counts": {},
            },
        }

    for idx, dedge in enumerate(discovery.get("edges", [])):
        src = norm_addr(dedge.get("source") or "")
        dst = norm_addr(dedge.get("target") or "")
        if not is_addr(src) or not is_addr(dst):
            continue
        if f"eoa:{src}" not in nodes or f"eoa:{dst}" not in nodes:
            continue
        symbols = sorted(dedge.get("symbols") or [])
        category_counts["wallet_flow"] += int(dedge.get("transfer_count") or 0)
        details = []
        for transfer_idx, tr in enumerate(dedge.get("transfers") or []):
            tx_hash = tr.get("tx_hash")
            direction = "out" if norm_addr(tr.get("from") or "") == src else "in"
            details.append({
                "event_id": f"{src}:{dst}:{tr.get('block_number') or 0}:{transfer_idx}:{tx_hash or ''}",
                "address": src,
                "tx_hash": tx_hash,
                "datetime_utc": tr.get("datetime_utc"),
                "block_number": tr.get("block_number"),
                "category": "wallet_flow",
                "protocol": "EOA/Safe transfer",
                "action": "send" if direction == "out" else "receive",
                "transfers": [{
                    "direction": direction,
                    "token": norm_token(tr.get("token") or ""),
                    "symbol": tr.get("symbol") or "token",
                    "amount": tr.get("amount_float"),
                    "count": 1,
                }],
            })
        edges.append({
            "id": f"eoa-discovery-edge-{idx}",
            "source": f"eoa:{src}",
            "target": f"eoa:{dst}",
            "edge_type": "wallet_move",
            "category": "wallet_flow",
            "label": f"{dedge.get('transfer_count', 0)} tx" + (f" | {','.join(symbols[:4])}" if symbols else ""),
            "tx_hash": dedge.get("sample_tx"),
            "event_count": int(dedge.get("transfer_count") or 0),
            "details": details,
        })

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "events": [],
        "metadata": {
            "source": "feeder/eoa_timeline.py --frontend-flow --dfs-only",
            "view": "eoa_flow",
            "format_version": 2,
            "address_count": len(nodes),
            "event_count": 0,
            "category_counts": dict(category_counts),
            "max_events_per_address": max_events_per_address,
            "discovery": discovery,
        },
    }


def event_touches_wallet_peer(ev: dict, wallet_addresses: set[str]) -> bool:
    for tr in ev.get("transfers") or []:
        src = norm_addr(tr.get("from") or "")
        dst = norm_addr(tr.get("to") or "")
        if src in wallet_addresses and dst in wallet_addresses and src != dst:
            return True
    return False


def extract_eoas_from_graph(path: str) -> List[str]:
    data = json.load(open(path))
    out: List[str] = []

    for node in data.get("nodes", []):
        addr = norm_addr(node.get("id") or node.get("address") or "")
        meta = node.get("data") or node.get("metadata") or {}
        kind = str(meta.get("kind") or meta.get("category") or node.get("kind") or "").lower()
        label = str(node.get("label") or meta.get("label") or "").lower()
        if is_addr(addr) and (kind == "eoa" or label.startswith("eoa ")):
            out.append(addr)

    for edge in data.get("edges", []):
        kind = str(edge.get("kind") or "").lower()
        holder = norm_addr(edge.get("holder") or "")
        if kind == "eoa" and is_addr(holder):
            out.append(holder)

    deduped: List[str] = []
    seen = set()
    for addr in out:
        if addr not in seen:
            deduped.append(addr)
            seen.add(addr)
    return deduped


def parse_addresses(addresses: str, address_file: Optional[str], graph: Optional[str], max_addresses: int) -> List[str]:
    out: List[str] = []
    if addresses:
        out.extend(norm_addr(x) for x in re.split(r"[\s,]+", addresses) if x.strip())
    if address_file:
        with open(address_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    out.append(norm_addr(line.split()[0]))
    if graph:
        out.extend(extract_eoas_from_graph(graph))
    deduped = []
    seen = set()
    for addr in out:
        if is_addr(addr) and addr not in seen:
            deduped.append(addr)
            seen.add(addr)
    return deduped[:max_addresses]


def main() -> int:
    ap = argparse.ArgumentParser(description="Build chronological semantic timelines for EOA DeFi activity.")
    ap.add_argument("--addresses", default="", help="Comma/space separated EOA addresses.")
    ap.add_argument("--address-file", help="File with one EOA address per line.")
    ap.add_argument("--graph", help="crawl/sim JSON file; EOA nodes will be extracted.")
    ap.add_argument("--from-block", type=int, default=0)
    ap.add_argument("--to-block", type=int, default=99999999)
    ap.add_argument("--max-addresses", type=int, default=50)
    ap.add_argument(
        "--receipt-transfers",
        choices=("none", "important", "all"),
        default="none",
        help="Add all ERC20 Transfer logs from tx receipts. Use 'important' to recover same-tx second hops for lending/vault/swap/bridge/YB txs.",
    )
    ap.add_argument("--max-receipts-per-address", type=int, default=200)
    ap.add_argument("--important-only", action="store_true", help="Keep only semantic DeFi events, dropping plain token sends/approvals.")
    ap.add_argument("--keep-token-flows", action="store_true", help="With --important-only, also keep token transfer events between discovered wallet addresses.")
    ap.add_argument("--dfs-wallets", action="store_true", help="Expand seed addresses across EOA/Safe token-transfer parents/children before building timelines.")
    ap.add_argument("--dfs-depth", type=int, default=1)
    ap.add_argument("--dfs-directions", choices=("both", "parents", "children"), default="both")
    ap.add_argument("--max-neighbors-per-address", type=int, default=12)
    ap.add_argument("--dfs-only", action="store_true", help="With --frontend-flow, output only the wallet DFS discovery graph without per-address timeline scans.")
    ap.add_argument("--frontend-flow", action="store_true", help="Write a React Flow friendly EOA timeline graph instead of the raw timeline payload.")
    ap.add_argument("--max-events-per-address", type=int, default=80, help="Limit event nodes per EOA in --frontend-flow output. 0 means no limit.")
    ap.add_argument("--out", default=os.path.join(REPO, "graphs", "frontend", "eoa.timeline.json"))
    args = ap.parse_args()

    addresses = parse_addresses(args.addresses, args.address_file, args.graph, args.max_addresses)
    if not addresses:
        ap.error("no EOA addresses provided; use --addresses, --address-file, or --graph")

    if args.to_block in (0, -1):
        args.to_block = latest_block()

    discovery = None
    if args.dfs_wallets:
        discovery = discover_wallet_dfs(
            addresses,
            args.from_block,
            args.to_block,
            max_depth=args.dfs_depth,
            max_addresses=args.max_addresses,
            max_neighbors=args.max_neighbors_per_address,
            directions=args.dfs_directions,
        )
        addresses = [node["address"] for node in discovery["nodes"]]

    if args.frontend_flow and args.dfs_only:
        if not discovery:
            discovery = {
                "nodes": [{"address": addr, "kind": wallet_kind(addr), "depth": 0, "discovered_by": "seed"} for addr in addresses],
                "edges": [],
                "seeds": addresses,
                "max_depth": 0,
                "directions": args.dfs_directions,
            }
        output = build_eoa_discovery_flow_view(discovery, max_events_per_address=args.max_events_per_address)
        output["metadata"].update({
            "source": "feeder/eoa_timeline.py --frontend-flow --dfs-only",
            "chain": "ethereum",
            "chain_id": 1,
            "from_block": args.from_block,
            "to_block": args.to_block,
            "address_count": len(addresses),
            "receipt_transfers": args.receipt_transfers,
            "important_only": args.important_only,
            "generated_at_utc": event_time(int(time.time())),
            "dfs": {
                "seed_addresses": discovery.get("seeds", []),
                "depth": args.dfs_depth,
                "directions": args.dfs_directions,
                "discovered_addresses": len(addresses),
                "discovery_edges": len(discovery.get("edges", [])),
            },
        })
        seed_direct_events: List[dict] = []
        seed_set = set(discovery.get("seeds", []) or addresses[:1])
        for seed in list(seed_set)[:3]:
            try:
                payload = build_eoa_timeline(
                    seed,
                    args.from_block,
                    args.to_block,
                    receipt_mode=args.receipt_transfers,
                    max_receipts=args.max_receipts_per_address,
                )
            except Exception as exc:
                output["metadata"].setdefault("data_gaps", []).append(f"seed_direct_events_failed:{seed}:{exc}")
                continue
            for ev in payload.get("events") or []:
                if ev.get("category") not in {"token_receive", "token_mint"}:
                    continue
                seed_direct_events.append(event_detail(ev, seed, aggregate_transfers(ev.get("transfers") or [])))
        if seed_direct_events:
            output["events"] = sorted(
                seed_direct_events,
                key=lambda e: (e.get("block_number") or 0, e.get("tx_hash") or ""),
            )
            output["metadata"]["event_count"] = len(seed_direct_events)
            output["metadata"]["category_counts"] = dict(Counter(e.get("category") or "unknown" for e in seed_direct_events))
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"saved {args.out}")
        print(f"addresses {len(addresses)} | events 0 | nodes {len(output['nodes'])} | edges {len(output['edges'])}")
        print("categories", output["metadata"].get("category_counts", {}))
        return 0

    wallet_addresses = set(addresses)
    address_payloads: Dict[str, dict] = {}
    flat_events: List[dict] = []
    for i, addr in enumerate(addresses, 1):
        print(f"[{i}/{len(addresses)}] tracing {addr}", file=sys.stderr)
        payload = build_eoa_timeline(
            addr,
            args.from_block,
            args.to_block,
            receipt_mode=args.receipt_transfers,
            max_receipts=args.max_receipts_per_address,
        )
        if args.important_only:
            keep = []
            for ev in payload["events"]:
                if ev["priority"] <= 60 and ev["category"] != "approval":
                    keep.append(ev)
                elif args.keep_token_flows and ev["category"].startswith("token_") and event_touches_wallet_peer(ev, wallet_addresses):
                    keep.append(ev)
            payload["events"] = keep
            payload["summary"]["event_count"] = len(keep)
            payload["summary"]["category_counts"] = dict(Counter(e["category"] for e in keep))
        address_payloads[addr] = payload
        flat_events.extend(payload["events"])

    flat_events.sort(key=lambda e: (e["block_number"], e["transaction_index"], e["tx_hash"], e["address"]))
    raw_metadata = {
            "source": "feeder/eoa_timeline.py",
            "chain": "ethereum",
            "chain_id": 1,
            "from_block": args.from_block,
            "to_block": args.to_block,
            "address_count": len(addresses),
            "receipt_transfers": args.receipt_transfers,
            "important_only": args.important_only,
            "generated_at_utc": event_time(int(time.time())),
    }
    if args.frontend_flow:
        output = build_eoa_flow_view(
            address_payloads,
            max_events_per_address=args.max_events_per_address,
            discovery=discovery,
        )
        output["metadata"].update(raw_metadata)
        output["metadata"]["source"] = "feeder/eoa_timeline.py --frontend-flow"
        output["metadata"]["category_counts"] = dict(Counter(e["category"] for e in flat_events))
        if discovery:
            output["metadata"]["dfs"] = {
                "seed_addresses": discovery.get("seeds", []),
                "depth": args.dfs_depth,
                "directions": args.dfs_directions,
                "discovered_addresses": len(addresses),
                "discovery_edges": len(discovery.get("edges", [])),
            }
    else:
        output = {
            "metadata": raw_metadata,
            "addresses": {addr: {"summary": payload["summary"]} for addr, payload in address_payloads.items()},
            "events": flat_events,
            "graph": build_graph(address_payloads, include_receipt_edges=args.receipt_transfers != "none"),
        }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"saved {args.out}")
    if args.frontend_flow:
        print(f"addresses {len(addresses)} | events {len(flat_events)} | nodes {len(output['nodes'])} | edges {len(output['edges'])}")
    else:
        print(f"addresses {len(addresses)} | events {len(flat_events)} | graph nodes {len(output['graph']['nodes'])} | graph edges {len(output['graph']['edges'])}")
    print("categories", dict(Counter(e["category"] for e in flat_events)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
