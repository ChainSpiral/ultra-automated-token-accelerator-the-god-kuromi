#!/usr/bin/env python3
"""
Deep reflexivity detector.

This is the assembly layer around the existing deterministic feeders:
  - Morpho GraphQL is used for seed discovery and vault-exposure metadata.
  - Morpho.market(), ERC20 supply/balance, asset()/underlying(), and crawl.py
    are used for block-pinned measurements.
  - flow_trace.py is reused for historical value-flow loops.

Structural verdicts are price-free. GraphQL USD fields are retained only as a
materiality hint and are never used in rho or fraud/not-fraud decisions.
"""
import argparse
import contextlib
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(ROOT, ".."))
GRAPH_DIR = os.path.join(REPO, "graphs")
sys.path.insert(0, ROOT)

import crawl as CR
import flow_trace as FT
import reflexivity_scan as RS

MORPHO = "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb"
MORPHO_GQL = "https://blue-api.morpho.org/graphql"
ZERO = "0x0000000000000000000000000000000000000000"
S_MARKET = "0x5c60e39a"  # market(bytes32)
S_TOTAL_ASSETS = "0x01e1d114"  # ERC4626 totalAssets()

CONTROLS = {
    "xUSD": {
        "address": "0xe2fc85bfb48c4cf147921fbe110cf92ef9f26f94",
        "kind": "historical-flow-positive",
        "flow": {
            "from_block": 23722236,
            "to_block": 23723236,
            "cached": os.path.join(GRAPH_DIR, "frontend", "flow.stream.json"),
            "tokens": "xUSD,deUSD,sdeUSD,USDC,USDT",
        },
    },
    "rsETH": {
        "address": "0xa1290d69c65a6fe4df752f95823fae25cb99e5a7",
        "kind": "negative-control",
    },
    "BONDUSD": {
        "address": "0x8413D2a624A9fA8b6D3eC7b22CF7F62E55D6Bc83",
        "kind": "trivial-positive",
    },
}

ANCHOR_SYMBOLS_HIGH = {
    "ETH", "WETH", "STETH", "WSTETH", "RETH", "CBETH",
    "BTC", "WBTC", "CBBTC", "TBTC", "LBTC",
}
ANCHOR_SYMBOLS_MEDIUM = {
    "USDC", "USDT", "DAI", "PYUSD", "USDS", "RLUSD", "USDTB", "AUSD",
    "USYC", "USDY", "BUIDL",
    "XAUT", "PAXG", "XAU", "GOLD",
}
DERIVED_HINTS = {
    "USDE", "SUSDE", "USD0", "USD0++", "DEUSD", "SDEUSD", "CRVUSD",
    "GHO", "SUSDS", "USR", "WSTUSR", "RLP", "SRUSD", "SIUSD",
}
TARGET_RE = re.compile(
    r"(USD|USR|RLP|PT-|YT-|WEETH|EZETH|RSETH|PUFETH|METH|OETH|ETH\\+|SUS|SDE|DEUSD|USDE|USD0|GHO|CRVUSD)",
    re.I,
)


def b32(x):
    return x.lower().replace("0x", "").rjust(64, "0")


def words(h):
    if not h or h == "0x":
        return []
    b = bytes.fromhex(h[2:])
    return [int.from_bytes(b[i:i + 32], "big") for i in range(0, len(b), 32)]


def _int(h):
    return int(h, 16) if h and h != "0x" else 0


def _safe_symbol(addr, block):
    try:
        return CR.read_symbol(addr.lower(), block) or addr[:10]
    except Exception:
        return addr[:10]


def _safe_decimals(addr, block):
    try:
        return CR.get_decimals(addr.lower(), block)
    except Exception:
        return 18


def _safe_supply(addr, block):
    try:
        dec = _safe_decimals(addr, block)
        raw = CR.total_supply(addr.lower(), block)
        return raw, raw / (10 ** dec), dec
    except Exception:
        return 0, 0.0, 18


def _is_token_like(addr, block):
    addr = addr.lower()
    try:
        if (CR.get_code(addr, block) or "0x") == "0x":
            return False
        return bool(CR.read_symbol(addr, block)) and CR.total_supply(addr, block) > 0
    except Exception:
        return False


def gql(query, variables=None):
    body = {"query": query}
    if variables is not None:
        body["variables"] = variables
    req = urllib.request.Request(
        MORPHO_GQL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        return json.loads(urllib.request.urlopen(req, timeout=90).read()).get("data") or {}
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"GraphQL {e.code}: {e.read()[:300].decode(errors='replace')}\n")
        return {}


def latest_block():
    return int(CR.rpc("eth_blockNumber", []), 16)


def morpho_market(mid, block):
    h = CR.eth_call(MORPHO, S_MARKET + b32(mid), block)
    w = words(h)
    if len(w) < 6:
        return None
    return {
        "totalSupplyAssets": w[0],
        "totalSupplyShares": w[1],
        "totalBorrowAssets": w[2],
        "totalBorrowShares": w[3],
        "lastUpdate": w[4],
        "fee": w[5],
    }


def discover_markets(max_markets):
    fields = (
        "marketId lltv oracleAddress listed "
        "warnings{ type level } "
        "loanAsset{ symbol address decimals } "
        "collateralAsset{ symbol address decimals } "
        "state{ borrowAssets supplyAssets borrowAssetsUsd supplyAssetsUsd "
        "collateralAssetsUsd utilization } "
        "supplyingVaults{ address name }"
    )
    out = []
    for skip in range(0, max_markets, 300):
        q = (
            "{ markets(first:300, skip:%d, orderBy:SupplyAssetsUsd, "
            "orderDirection:Desc, where:{chainId_in:[1]}){ items{ %s } } }"
        ) % (skip, fields)
        batch = (gql(q).get("markets") or {}).get("items") or []
        out.extend(batch)
        if len(batch) < 300:
            break
        time.sleep(0.05)
    return out[:max_markets]


def market_usd_hint(market):
    st = market.get("state") or {}
    return max(
        st.get("supplyAssetsUsd") or 0,
        st.get("borrowAssetsUsd") or 0,
        st.get("collateralAssetsUsd") or 0,
    )


def discovery_priority(token):
    sym = (token.get("symbol") or "").upper()
    roles = set(token.get("roles") or [])
    is_anchor = sym in ANCHOR_SYMBOLS_HIGH or sym in ANCHOR_SYMBOLS_MEDIUM
    is_target = bool(TARGET_RE.search(sym or ""))
    materiality = sum(m.get("materiality_usd_hint") or 0 for m in token.get("markets") or [])
    collateral_bonus = 3 if "collateral" in roles else 0
    target_bonus = 6 if is_target else 0
    anchor_penalty = 5 if is_anchor else 0
    loan_only_penalty = 2 if roles == {"loan"} else 0
    return (
        target_bonus + collateral_bonus - anchor_penalty - loan_only_penalty,
        materiality,
    )


def discover_seed_universe(block, max_markets, max_tokens, include_unlisted_controls=True, target_first=True):
    markets = discover_markets(max_markets)
    by_addr = {}
    included_markets = []
    for m in markets:
        vaults = m.get("supplyingVaults") or []
        if m.get("listed") is not True or not vaults:
            continue
        mm = morpho_market(m["marketId"], block)
        loan = (m.get("loanAsset") or {})
        ldec = loan.get("decimals") or _safe_decimals(loan.get("address", ""), block)
        supply_native = None
        borrow_native = None
        if mm and loan.get("address"):
            supply_native = mm["totalSupplyAssets"] / (10 ** ldec)
            borrow_native = mm["totalBorrowAssets"] / (10 ** ldec)
        rec = {
            "marketId": m["marketId"],
            "listed": m.get("listed"),
            "oracle": m.get("oracleAddress"),
            "lltv": m.get("lltv"),
            "vaults": vaults,
            "loan": loan,
            "collateral": m.get("collateralAsset") or {},
            "state_indexer": m.get("state") or {},
            "materiality_usd_hint": market_usd_hint(m),
            "onchain_supply_assets_native": supply_native,
            "onchain_borrow_assets_native": borrow_native,
            "warnings": m.get("warnings") or [],
        }
        included_markets.append(rec)
        for role in ("loan", "collateral"):
            a = (rec[role] or {}).get("address")
            if not a:
                continue
            al = a.lower()
            t = by_addr.setdefault(al, {
                "address": al,
                "symbol": (rec[role] or {}).get("symbol") or _safe_symbol(al, block),
                "markets": [],
                "roles": set(),
                "control": None,
            })
            t["markets"].append(rec)
            t["roles"].add(role)

    ranked = list(by_addr.values())
    for t in ranked:
        if isinstance(t.get("roles"), set):
            t["roles"] = sorted(t["roles"])
    if target_first:
        ranked.sort(key=lambda t: (-discovery_priority(t)[0], -discovery_priority(t)[1], t.get("symbol") or ""))
    else:
        ranked.sort(key=lambda t: -sum(m.get("materiality_usd_hint") or 0 for m in t["markets"]))
    if max_tokens:
        ranked = ranked[:max_tokens]
    tokens = {t["address"]: t for t in ranked}
    if include_unlisted_controls:
        for sym, c in CONTROLS.items():
            al = c["address"].lower()
            tokens.setdefault(al, {
                "address": al,
                "symbol": sym,
                "markets": [],
                "roles": set(),
                "control": c["kind"],
            })
            tokens[al]["control"] = c["kind"]
            tokens[al]["symbol"] = sym
    return tokens, included_markets


def markets_for_token(addr):
    q = (
        '{ markets(first:40, where:{collateralAssetAddress_in:["%s"]}){ items{ '
        'marketId lltv oracleAddress listed warnings{type level} '
        'loanAsset{symbol address decimals} collateralAsset{symbol address decimals} '
        'state{borrowAssets supplyAssets borrowAssetsUsd supplyAssetsUsd collateralAssetsUsd utilization} '
        'supplyingVaults{address name} } } }'
    ) % addr.lower()
    return (gql(q).get("markets") or {}).get("items") or []


def market_collateral_addr(market):
    c = market.get("collateral") or market.get("collateralAsset") or {}
    return (c.get("address") or "").lower()


def oracle_introspect_deep(oracle, collat, collat_sym, block):
    RS.BLOCK = block
    base = RS.oracle_introspect(oracle, collat, collat_sym, CR.etherscan_name(oracle))
    cls = base.get("cls", "none")
    sees = base.get("sees", "")
    feeds = []
    for sig in ("BASE_FEED_1()", "BASE_FEED_2()"):
        try:
            f = RS._caddr(oracle, sig)
            if f:
                feeds.append((f.lower(), RS._desc(f) or ""))
        except Exception:
            pass

    def wordset(s):
        return {w for w in re.split(r"[^A-Za-z0-9]+", (s or "").upper()) if w}

    desc_words = set()
    unknown_desc = False
    for _, desc in feeds:
        if not desc or desc == "?":
            unknown_desc = True
        desc_words |= wordset(desc)

    collat_words = wordset(collat_sym)
    for sel in (CR.SEL["asset"], CR.SEL["underlying"]):
        try:
            u = CR.read_addr(collat, sel, block)
            if u:
                collat_words |= wordset(_safe_symbol(u, block))
        except Exception:
            pass

    symu = (collat_sym or "").upper()
    real_collat = symu in ANCHOR_SYMBOLS_HIGH or symu in ANCHOR_SYMBOLS_MEDIUM
    feed_mentions_collat = bool(collat_words & desc_words)
    if cls == "anchored" and feeds and not unknown_desc and not real_collat and not feed_mentions_collat:
        cls = "oracle-mismatch"
        sees = sees + " | feed asset does not match collateral symbol/underlying"
    return {**base, "cls": cls, "sees": sees, "feeds": [{"address": f, "description": d} for f, d in feeds]}


def classify_pricing(addr, token, block):
    sym = (token.get("symbol") or _safe_symbol(addr, block)).upper()
    if sym in ANCHOR_SYMBOLS_HIGH:
        return {
            "partition": "R",
            "class": "anchor-real-crypto",
            "confidence": "HIGH",
            "evidence": f"{sym} treated as exogenous real-asset anchor",
        }
    if sym in ANCHOR_SYMBOLS_MEDIUM:
        return {
            "partition": "R",
            "class": "anchor-attestation",
            "confidence": "MEDIUM",
            "evidence": f"{sym} treated as off-chain/attestation anchor boundary",
        }

    markets = [m for m in (token.get("markets") or []) if market_collateral_addr(m) == addr.lower()]
    if not markets:
        markets = [m for m in (token.get("all_markets") or []) if market_collateral_addr(m) == addr.lower()]
    if not markets and token.get("control"):
        markets = markets_for_token(addr)
    oracle_reads = []
    severity = {"oracle-mismatch": 4, "bespoke/NAV": 3, "self-NAV": 3,
                "hardcoded": 3, "ext-feed?": 1, "market-feed": 0,
                "anchored": 0, "other": 1, "none": -1}
    for m in markets[:12]:
        oracle = m.get("oracleAddress") or m.get("oracle")
        if not oracle:
            continue
        oracle_reads.append({
            "marketId": m.get("marketId"),
            "loan": ((m.get("loanAsset") or m.get("loan") or {}).get("symbol")
                     if isinstance(m.get("loanAsset") or m.get("loan"), dict) else None),
            "oracle": oracle.lower(),
            **oracle_introspect_deep(oracle.lower(), addr, sym, block),
        })
    if oracle_reads:
        bad = [r for r in oracle_reads if r.get("cls") in ("oracle-mismatch", "bespoke/NAV", "self-NAV", "hardcoded")]
        good = [r for r in oracle_reads if r.get("cls") in ("anchored", "market-feed")]
        if bad:
            worst = max(bad, key=lambda r: severity.get(r.get("cls"), 0))
        elif good:
            worst = good[0]
        else:
            worst = max(oracle_reads, key=lambda r: severity.get(r.get("cls"), 0))
        cls = worst["cls"]
        if cls in ("anchored", "market-feed"):
            part = "R"
            conf = "HIGH"
        elif cls in ("oracle-mismatch", "bespoke/NAV", "self-NAV", "hardcoded"):
            part = "D"
            conf = "HIGH" if cls == "oracle-mismatch" else "MEDIUM"
        else:
            part = "O"
            conf = "LOW"
        return {
            "partition": part,
            "class": cls,
            "confidence": conf,
            "evidence": worst.get("sees") or "",
            "oracle_reads": oracle_reads,
        }

    if sym in DERIVED_HINTS:
        return {
            "partition": "D",
            "class": "derived-no-market-oracle",
            "confidence": "LOW",
            "evidence": "symbol is in derived-token hint set but no collateral oracle was found",
        }
    return {
        "partition": "O",
        "class": "opaque-no-pricing-source",
        "confidence": "LOW",
        "evidence": "no Morpho collateral oracle and not a configured anchor",
    }


def classify_pricing_fast(addr, token, block):
    sym = (token.get("symbol") or _safe_symbol(addr, block)).upper()
    if sym in ANCHOR_SYMBOLS_HIGH:
        return {
            "partition": "R",
            "class": "anchor-real-crypto",
            "confidence": "HIGH",
            "evidence": f"{sym} treated as exogenous real-asset anchor",
            "fast": True,
        }
    if sym in ANCHOR_SYMBOLS_MEDIUM:
        return {
            "partition": "R",
            "class": "anchor-attestation",
            "confidence": "MEDIUM",
            "evidence": f"{sym} treated as off-chain/attestation anchor boundary",
            "fast": True,
        }
    collateral_markets = [
        m for m in (token.get("markets") or [])
        if market_collateral_addr(m) == addr.lower()
    ]
    if collateral_markets or TARGET_RE.search(sym or ""):
        return {
            "partition": "D",
            "class": "target-needs-deep-pricing",
            "confidence": "LOW",
            "evidence": "fast discovery mode: vault-exposed synthetic/LRT candidate; rerun without --fast-pricing for oracle introspection",
            "fast": True,
        }
    return {
        "partition": "O",
        "class": "opaque-fast",
        "confidence": "LOW",
        "evidence": "fast discovery mode: no deep pricing introspection",
        "fast": True,
    }


def crawl_token(addr, block, depth, k, min_gfrac, crawl_mode="cached", quiet=True):
    p = os.path.join(GRAPH_DIR, f"crawl.{addr.lower()}.{block}.json")
    if crawl_mode in ("cached", "live") and os.path.exists(p):
        try:
            return json.load(open(p)), p, True
        except Exception:
            pass
    if crawl_mode in ("cached", "off"):
        return {"root": addr.lower(), "block": block, "edges": []}, None, False
    edges = []
    old_depth, old_gmin = CR.MAXDEPTH, CR.GMINFRAC
    CR.MAXDEPTH = depth
    CR.GMINFRAC = min_gfrac
    try:
        sink = io.StringIO()
        cm = contextlib.redirect_stdout(sink) if quiet else contextlib.nullcontext()
        with cm:
            CR.visit_token(addr.lower(), block, 0, k, min_gfrac, {addr.lower()}, edges)
    finally:
        CR.MAXDEPTH, CR.GMINFRAC = old_depth, old_gmin
    data = {"root": addr.lower(), "block": block, "edges": edges}
    return data, None, False


def erc4626_total_assets(token, block):
    try:
        return _int(CR.eth_call(token, S_TOTAL_ASSETS, block))
    except Exception:
        return 0


def add_edge(edge_map, src, dst, weight, reason, evidence, graph_type="stock"):
    if not src or not dst or weight <= 0:
        return
    src = src.lower()
    dst = dst.lower()
    k = (src, dst)
    cur = edge_map.get(k)
    rec = {
        "from": src,
        "to": dst,
        "weight": float(weight),
        "reason": reason,
        "evidence": evidence,
        "graph": graph_type,
    }
    if cur is None or rec["weight"] > cur["weight"]:
        edge_map[k] = rec


def direct_backing_edges(tokens, block, reserve_scan=True):
    addrs = list(tokens)
    edge_map = {}
    for src in addrs:
        src_sym = tokens[src]["symbol"]
        for sel, why in ((CR.SEL["asset"], "asset()"), (CR.SEL["underlying"], "underlying()")):
            dst = CR.read_addr(src, sel, block)
            if not dst:
                continue
            dst = dst.lower()
            raw_supply, supply_native, dec = _safe_supply(dst, block)
            if raw_supply <= 0:
                continue
            amt = erc4626_total_assets(src, block) if why == "asset()" else 0
            if amt <= 0:
                amt = CR.balanceof(dst, src, block)
            if amt <= 0 and dst == src:
                continue
            weight = amt / raw_supply
            add_edge(edge_map, src, dst, weight, why, {
                "amount_raw": amt,
                "supply_raw": raw_supply,
                "amount_native": amt / (10 ** dec),
                "supply_native": supply_native,
                "src_symbol": src_sym,
                "dst_symbol": _safe_symbol(dst, block),
            })

        if not reserve_scan:
            continue
        for dst in addrs:
            if dst == src:
                continue
            raw_supply, supply_native, dec = _safe_supply(dst, block)
            if raw_supply <= 0:
                continue
            try:
                bal = CR.balanceof(dst, src, block)
            except Exception:
                bal = 0
            if bal <= 0:
                continue
            weight = bal / raw_supply
            add_edge(edge_map, src, dst, weight, "reserve-balanceOf", {
                "amount_raw": bal,
                "supply_raw": raw_supply,
                "amount_native": bal / (10 ** dec),
                "supply_native": supply_native,
                "src_symbol": src_sym,
                "dst_symbol": _safe_symbol(dst, block),
            })
    return list(edge_map.values())


def crawl_backing_edges(tokens, block, depth, k, min_gfrac, max_workers, crawl_mode):
    out = []
    if crawl_mode == "off":
        return out
    token_like_cache = {}

    def is_token(a):
        if a not in token_like_cache:
            token_like_cache[a] = _is_token_like(a, block)
        return token_like_cache[a]

    def one(addr):
        data, path, cached = crawl_token(addr, block, depth, k, min_gfrac, crawl_mode)
        edges = []
        opaque = []
        for e in data.get("edges", []):
            holder = (e.get("holder") or "").lower()
            from_token = (e.get("from_token") or "").lower()
            if not holder or not from_token:
                continue
            if e.get("resolved") is False or e.get("kind") == "opaque":
                opaque.append(e)
            if holder == from_token:
                continue
            if is_token(holder):
                # Holder token owns from_token. Therefore holder is backed by
                # from_token with coefficient balance(from_token, holder)/S_from_token.
                add = {
                    "from": holder,
                    "to": from_token,
                    "weight": float(e.get("frac") or 0),
                    "reason": "crawl-holder-reversed",
                    "graph": "stock",
                    "evidence": {
                        "crawl_root": addr,
                        "cached_path": path,
                        "cached": cached,
                        "holder_kind": e.get("kind"),
                        "holder_label": e.get("label"),
                        "amount_root_native": e.get("amount"),
                        "frac_of_backing_supply": e.get("frac"),
                        "gfrac_root": e.get("gfrac"),
                        "depth": e.get("depth"),
                    },
                }
                if add["weight"] > 0:
                    edges.append(add)
        return edges, opaque

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for edges, opaque in ex.map(one, list(tokens)):
            out.extend(edges)
            for e in opaque:
                ft = e.get("from_token", "").lower()
                if ft in tokens:
                    tokens[ft].setdefault("opaque_edges", []).append(e)
    return out


def add_trivial_unbacked_edges(tokens, stock_edges):
    outgoing = defaultdict(float)
    for e in stock_edges:
        outgoing[e["from"].lower()] += e["weight"]
    edge_map = {(e["from"].lower(), e["to"].lower(), e["reason"]): e for e in stock_edges}
    for addr, t in tokens.items():
        pricing = t.get("pricing") or {}
        markets = t.get("all_markets") or [m for m in (t.get("markets") or []) if market_collateral_addr(m) == addr]
        has_vault = any(m.get("supplyingVaults") or m.get("vaults") for m in markets)
        listed = any(m.get("listed") is True for m in markets)
        cls = pricing.get("class")
        is_control_trivial = t.get("control") == "trivial-positive"
        should_mark = is_control_trivial or (
            cls == "oracle-mismatch" and not listed and not has_vault
        )
        if should_mark and outgoing.get(addr, 0) == 0:
            key = (addr, addr, "trivial-unbacked-oracle-mismatch")
            edge_map[key] = {
                "from": addr,
                "to": addr,
                "weight": 1.0,
                "reason": "trivial-unbacked-oracle-mismatch" if not is_control_trivial else "trivial-control-unbacked",
                "graph": "stock",
                "evidence": {
                    "pricing": pricing,
                    "listed": listed,
                    "has_supplying_vaults": has_vault,
                    "classification": "TRIVIAL/depth-1/no-victims" if not has_vault else "depth-1",
                },
            }
    return list(edge_map.values())


def tarjan(graph):
    idx = {}
    low = {}
    stack = []
    on = set()
    out = []
    counter = [0]
    sys.setrecursionlimit(10000)

    def strong(v):
        idx[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph.get(v, ()):
            if w not in idx:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            comp = []
            while True:
                w = stack.pop()
                on.remove(w)
                comp.append(w)
                if w == v:
                    break
            out.append(comp)

    for v in list(graph):
        if v not in idx:
            strong(v)
    return out


def spectral_radius(nodes, edges):
    if not nodes:
        return 0.0, []
    pos = {n: i for i, n in enumerate(nodes)}
    mat = np.zeros((len(nodes), len(nodes)), dtype=float)
    for e in edges:
        i = pos.get(e["from"])
        j = pos.get(e["to"])
        if i is not None and j is not None:
            mat[i, j] += e["weight"]
    vals = np.linalg.eigvals(mat) if len(nodes) else np.array([])
    rho = float(max((abs(v) for v in vals), default=0.0))
    return rho, mat.tolist()


def find_cycle_path(nodes, edges):
    adj = defaultdict(list)
    for e in edges:
        adj[e["from"]].append(e["to"])
    node_set = set(nodes)
    for start in nodes:
        stack = [(start, [start])]
        while stack:
            v, path = stack.pop()
            for w in adj.get(v, []):
                if w == start:
                    return path + [start]
                if w in node_set and w not in path:
                    stack.append((w, path + [w]))
    return []


def solve_stock(tokens, stock_edges):
    d_nodes = [a for a, t in tokens.items() if (t.get("pricing") or {}).get("partition") == "D"]
    d_set = set(d_nodes)
    dd_edges = [e for e in stock_edges if e["from"] in d_set and e["to"] in d_set]
    rho, mat = spectral_radius(d_nodes, dd_edges)
    graph = defaultdict(set)
    self_loop = set()
    for e in dd_edges:
        graph[e["from"]].add(e["to"])
        if e["from"] == e["to"]:
            self_loop.add(e["from"])
    comps = []
    for c in tarjan(graph):
        c_edges = [e for e in dd_edges if e["from"] in c and e["to"] in c]
        if len(c) > 1 or any(n in self_loop for n in c):
            crho, _ = spectral_radius(c, c_edges)
            path = find_cycle_path(c, c_edges)
            comps.append({
                "nodes": c,
                "rho": crho,
                "cycle_path": path,
                "depth": max(0, len(path) - 1),
                "edges": c_edges,
            })
    comps.sort(key=lambda c: (-c["rho"], -c["depth"]))
    return {"rho": rho, "matrix_nodes": d_nodes, "matrix": mat, "cycles": comps}


def stock_for_token(addr, stock_result):
    cycles = [c for c in stock_result.get("cycles", []) if addr in set(c.get("nodes", []))]
    rho = max([c.get("rho", 0.0) for c in cycles] + [0.0])
    return {
        "rho": rho,
        "cycles": cycles,
        "global_rho": stock_result.get("rho", 0.0),
    }


def load_cached_flow(path):
    if path and os.path.exists(path):
        return json.load(open(path)), path
    return None, None


def flow_edges_from_json(flow_json):
    edges = {}
    nodes = set()
    for e in flow_json.get("edges", []):
        f = e.get("source", "").lower()
        t = e.get("target", "").lower()
        a = (e.get("token") or e.get("asset") or "?").lower()
        if not f or not t:
            continue
        nodes.add(f)
        nodes.add(t)
        edges[(f, t, a)] = {
            "amount": e.get("amount") or 0.0,
            "count": e.get("count") or 1,
            "minblk": (e.get("block_range") or [None, None])[0],
            "maxblk": (e.get("block_range") or [None, None])[1],
            "tx": e.get("sample_tx"),
            "in_cycle": bool(e.get("in_cycle")),
        }
    return nodes, edges


def address_sccs_from_edges(edges):
    graph = defaultdict(set)
    for f, t, _a in edges:
        if f != ZERO and t != ZERO:
            graph[f].add(t)
    return tarjan(graph)


def analyze_flow_for_token(addr, token, block, args):
    ctrl = CONTROLS.get(token.get("symbol"), {})
    fcfg = ctrl.get("flow") or {}
    frm = args.flow_from or fcfg.get("from_block")
    to = args.flow_to or fcfg.get("to_block")
    if not frm or not to:
        return {"rho": 0.0, "status": "not-run", "reason": "no flow window configured"}

    cached_json, cached_path = load_cached_flow(fcfg.get("cached") if args.use_cached_flow else None)
    if cached_json:
        nodes, edges = flow_edges_from_json(cached_json)
        seeds = cached_json.get("metadata", {}).get("seeds", [])
        source = cached_path
    else:
        contracts = [addr]
        token_filter = args.flow_tokens or fcfg.get("tokens")
        if token_filter:
            contracts = [FT.TOKENS.get(s, s).lower() for s in token_filter.split(",")]
        seeds = FT.discover_seeds(addr, frm, to, args.flow_seeds)
        nodes, edges, _explored = FT.trace(seeds, frm, to, args.flow_depth, args.flow_maxnodes, contracts)
        source = "feeder/flow_trace.py live"

    addr = addr.lower()
    sccs = address_sccs_from_edges(edges)
    scc_for = {}
    for i, comp in enumerate(sccs):
        for n in comp:
            scc_for[n] = i

    root_cycle_edges = []
    issuer_edges_out = []
    issuer_edges_in = []
    for (f, t, asset), e in edges.items():
        if asset == addr:
            if e.get("in_cycle"):
                root_cycle_edges.append({"from": f, "to": t, "asset": asset, **e})
            if f in seeds:
                issuer_edges_out.append({"from": f, "to": t, "asset": asset, **e})
            if t in seeds:
                issuer_edges_in.append({"from": f, "to": t, "asset": asset, **e})

    issued = sum(e["amount"] for e in issuer_edges_out)
    returned = sum(e["amount"] for e in issuer_edges_in)
    loop_gain = (returned / issued) if issued else 0.0
    pathological = bool(root_cycle_edges)
    rho = 1.0 if pathological else 0.0
    if pathological and loop_gain > 1:
        rho = loop_gain
    elif pathological and loop_gain > 0:
        # Flow SCCs are address-control systems, not token reserves. A closed
        # recycled-claim loop is a rho>=1 structural positive even when the
        # sampled issuer in/out edge ratio is clipped by the window.
        rho = 1.0
    return {
        "rho": rho,
        "status": "positive" if rho >= 1 else "negative",
        "from_block": frm,
        "to_block": to,
        "source": source,
        "seeds": seeds,
        "cycle_depth": 2 if root_cycle_edges else 0,
        "issued_claim_out_native": issued,
        "returned_claim_in_native": returned,
        "sample_window_loop_gain": loop_gain,
        "root_cycle_edges": root_cycle_edges[:12],
        "address_scc_count": len(sccs),
        "notes": "rho is set from closed recycled-claim flow cycles; amounts are token-native.",
    }


def materiality_for_token(token):
    markets = token.get("markets") or []
    return {
        "vault_count": sum(len(m.get("vaults") or m.get("supplyingVaults") or []) for m in markets),
        "usd_hint": sum(m.get("materiality_usd_hint") or market_usd_hint(m) for m in markets),
        "onchain_supply_assets": [
            {
                "marketId": m.get("marketId"),
                "loan_symbol": (m.get("loan") or m.get("loanAsset") or {}).get("symbol"),
                "supply_assets_native": m.get("onchain_supply_assets_native"),
                "borrow_assets_native": m.get("onchain_borrow_assets_native"),
            }
            for m in markets
        ],
    }


def rank_candidate(token, stock, flow):
    mat = materiality_for_token(token)
    rho_stock = stock.get("rho", 0.0)
    rho_flow = flow.get("rho", 0.0)
    max_rho = max(rho_stock, rho_flow)
    cycles = stock.get("cycles") or []
    depth = max([c.get("depth", 0) for c in cycles] + [flow.get("cycle_depth", 0)])
    vault_bonus = 1 if mat["vault_count"] else 0
    depth_bonus = min(depth, 4) / 4
    rho_bonus = 3 if max_rho >= 1 else (max_rho / max(1e-9, 1 - max_rho) if max_rho < 1 else 0)
    materiality_bonus = math.log10((mat["usd_hint"] or 0) + 1) / 4
    trivial_penalty = 3 if token.get("control") == "trivial-positive" or not mat["vault_count"] else 0
    return rho_bonus + depth_bonus + vault_bonus + materiality_bonus - trivial_penalty


def token_report_record(addr, token, stock_result, flow_result, stock_edges):
    pricing = token.get("pricing") or {}
    cycles = stock_result.get("cycles") or []
    cycle = cycles[0] if cycles else {}
    rho_stock = stock_result.get("rho", 0.0)
    rho_flow = flow_result.get("rho", 0.0)
    max_rho = max(rho_stock, rho_flow)
    inflation = None if max_rho >= 1 else (1 / (1 - max_rho) if max_rho < 1 else None)
    token_edges = [e for e in stock_edges if e["from"] == addr or e["to"] == addr]
    materiality = materiality_for_token(token)
    verdict = "POSITIVE" if max_rho >= 1 else "NEGATIVE"
    if token.get("control") == "trivial-positive" or (
        verdict == "POSITIVE"
        and rho_flow < 1
        and not materiality["vault_count"]
        and (cycle.get("depth") or 1) <= 1
    ):
        verdict = "TRIVIAL_POSITIVE"
    if not token.get("control"):
        if pricing.get("fast") and pricing.get("class") == "target-needs-deep-pricing":
            verdict = "NEEDS_DEEP_SCAN"
        elif verdict == "NEGATIVE" and flow_result.get("status") == "not-run":
            verdict = "STOCK_NEGATIVE_FLOW_UNTESTED"
    confidence = pricing.get("confidence", "LOW")
    if any((e.get("evidence") or {}).get("classification") == "TRIVIAL/depth-1/no-victims" for e in token_edges):
        confidence = "HIGH"
    return {
        "token": addr,
        "symbol": token.get("symbol"),
        "control": token.get("control"),
        "verdict": verdict,
        "rho_stock": rho_stock,
        "rho_stock_global": stock_result.get("global_rho", rho_stock),
        "rho_flow": rho_flow,
        "inflation_factor": "infinite" if max_rho >= 1 else inflation,
        "cycle_path": cycle.get("cycle_path") or [],
        "cycle_depth": cycle.get("depth", flow_result.get("cycle_depth", 0)),
        "pricing_partition": pricing,
        "materiality": materiality,
        "confidence": confidence,
        "stock_edges": token_edges[:20],
        "flow": flow_result,
        "opaque": token.get("opaque_edges", [])[:20],
        "rank_score": None,
    }


def write_report(path, result):
    def fmt_rho(x):
        return f"{x:.4f}" if isinstance(x, (int, float)) else str(x)

    lines = []
    lines.append("# Deep Reflexivity Report")
    lines.append("")
    lines.append(f"Snapshot block: `{result['meta']['block']}`")
    lines.append("")
    lines.append("## Ranked Candidates")
    lines.append("")
    for r in result["ranked"]:
        mat = r["materiality"]
        lines.append(
            f"- **{r['symbol']}** `{r['token']}`: {r['verdict']} | "
            f"rho(stock)={fmt_rho(r['rho_stock'])}, rho(flow)={fmt_rho(r['rho_flow'])}, "
            f"inflation={r['inflation_factor']}, depth={r['cycle_depth']}, "
            f"vaults={mat['vault_count']}, usd_hint={mat['usd_hint']:.0f}, "
            f"flow_status={r.get('flow', {}).get('status')}, confidence={r['confidence']}"
        )
        if r["cycle_path"]:
            labels = [result["labels"].get(a, a[:10]) for a in r["cycle_path"]]
            lines.append(f"  - cycle: {' -> '.join(labels)}")
        lines.append(f"  - R/D: {r['pricing_partition'].get('partition')} / {r['pricing_partition'].get('class')} ({r['pricing_partition'].get('evidence')})")
        if r["flow"].get("status") != "not-run":
            lines.append(
                f"  - flow evidence: {r['flow'].get('status')} blocks "
                f"{r['flow'].get('from_block')}..{r['flow'].get('to_block')} "
                f"source={r['flow'].get('source')}"
            )
    lines.append("")
    lines.append("## Not Resolvable")
    opaque = []
    for r in result["ranked"]:
        for e in r.get("opaque") or []:
            opaque.append((r["symbol"], e))
    if result.get("meta", {}).get("crawl_mode") == "off":
        lines.append("- Multi-hop crawl expansion was disabled in this saved run; rerun with `--crawl-mode cached` or `--crawl-mode live` to resolve holder/ledger paths for discovered non-control tokens.")
    if not opaque:
        lines.append("- No opaque crawl edges were emitted by the enabled paths.")
    else:
        for sym, e in opaque[:40]:
            lines.append(
                f"- {sym}: `{e.get('holder')}` kind={e.get('kind')} "
                f"label={e.get('label')} reason=adapter unresolved or opaque leaf"
            )
    open(path, "w").write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--block", type=int, help="snapshot block for stock/on-chain reads")
    ap.add_argument("--max-markets", type=int, default=350)
    ap.add_argument("--max-tokens", type=int, default=40)
    ap.add_argument("--materiality-first", action="store_true",
                    help="rank discovery by raw materiality instead of target synthetic/LRT priority")
    ap.add_argument("--symbols",
                    help="comma-separated discovered symbols to keep after discovery, case-insensitive")
    ap.add_argument("--no-controls", action="store_true",
                    help="do not force-include xUSD/BONDUSD/rsETH controls")
    ap.add_argument("--crawl-depth", type=int, default=3)
    ap.add_argument("--crawl-k", type=int, default=12)
    ap.add_argument("--min-gfrac", type=float, default=0.005)
    ap.add_argument("--crawl-mode", choices=("cached", "live", "off"), default="cached",
                    help="cached uses existing graphs/crawl.* files only; live may run Dune")
    ap.add_argument("--fast-pricing", action="store_true",
                    help="coarse R/D labels for discovery artifacts; controls still use deep pricing")
    ap.add_argument("--no-reserve-scan", action="store_true",
                    help="skip pairwise balanceOf reserve scan; keep asset()/underlying() unwraps")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--no-discovery", action="store_true", help="scan controls only")
    ap.add_argument("--no-flow", action="store_true")
    ap.add_argument("--use-cached-flow", action="store_true", default=True)
    ap.add_argument("--flow-from", type=int)
    ap.add_argument("--flow-to", type=int)
    ap.add_argument("--flow-depth", type=int, default=2)
    ap.add_argument("--flow-maxnodes", type=int, default=120)
    ap.add_argument("--flow-seeds", type=int, default=4)
    ap.add_argument("--flow-tokens")
    ap.add_argument("--out", default=os.path.join(GRAPH_DIR, "reflexivity_deep.json"))
    ap.add_argument("--report", default=os.path.join(GRAPH_DIR, "reflexivity_deep_report.md"))
    args = ap.parse_args()

    block = args.block or latest_block()
    tokens, markets = ({}, [])
    if not args.no_discovery:
        tokens, markets = discover_seed_universe(
            block,
            args.max_markets,
            args.max_tokens,
            include_unlisted_controls=not args.no_controls,
            target_first=not args.materiality_first,
        )
    else:
        for sym, c in CONTROLS.items():
            tokens[c["address"].lower()] = {
                "address": c["address"].lower(),
                "symbol": sym,
                "markets": [],
                "roles": [],
                "control": c["kind"],
            }
    if args.symbols:
        wanted = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
        tokens = {
            a: t for a, t in tokens.items()
            if (t.get("symbol") or "").upper() in wanted or t.get("control")
        }

    for addr, t in list(tokens.items()):
        t["symbol"] = t.get("symbol") or _safe_symbol(addr, block)
        raw, native, dec = _safe_supply(addr, block)
        t["total_supply_raw"] = raw
        t["total_supply_native"] = native
        t["decimals"] = dec
        t["all_markets"] = markets_for_token(addr) if (t.get("control") or not t.get("markets")) else []

    addr2sym = {a: t["symbol"] for a, t in tokens.items()}
    RS.TOKENS = {t["symbol"]: a for a, t in tokens.items()}
    RS.ADDR2SYM = addr2sym.copy()
    RS.SET = set(tokens)
    RS.BLOCK = block

    for addr, t in tokens.items():
        if args.fast_pricing and not t.get("control"):
            t["pricing"] = classify_pricing_fast(addr, t, block)
        else:
            t["pricing"] = classify_pricing(addr, t, block)

    stock_edges = []
    stock_edges.extend(direct_backing_edges(tokens, block, reserve_scan=not args.no_reserve_scan))
    stock_edges.extend(crawl_backing_edges(
        tokens, block, args.crawl_depth, args.crawl_k, args.min_gfrac, args.workers, args.crawl_mode
    ))
    stock_edges = add_trivial_unbacked_edges(tokens, stock_edges)
    stock_result = solve_stock(tokens, stock_edges)

    labels = {a: t["symbol"] for a, t in tokens.items()}
    results = []
    for addr, t in tokens.items():
        flow = {"rho": 0.0, "status": "not-run", "reason": "disabled"}
        if not args.no_flow and (t.get("control") == "historical-flow-positive" or args.flow_from):
            flow = analyze_flow_for_token(addr, t, block, args)
        tstock = stock_for_token(addr, stock_result)
        rec = token_report_record(addr, t, tstock, flow, stock_edges)
        rec["rank_score"] = rank_candidate(t, tstock, flow)
        results.append(rec)

    results.sort(key=lambda r: (-(r["rank_score"] or 0), r["symbol"] or ""))
    out = {
        "meta": {
            "block": block,
            "generated_at": int(time.time()),
            "source": "feeder/reflexivity_deep.py",
            "price_free_verdict": True,
            "usd_fields_are_materiality_hints_only": True,
            "seed_markets": len(markets),
            "tokens": len(tokens),
            "crawl_mode": args.crawl_mode,
            "fast_pricing": args.fast_pricing,
            "reserve_scan": not args.no_reserve_scan,
        },
        "labels": labels,
        "stock": stock_result,
        "ranked": results,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(out, open(args.out, "w"), indent=2)
    write_report(args.report, out)
    print(f"saved {args.out}")
    print(f"saved {args.report}")
    for r in results[:10]:
        print(
            f"{r['symbol']:10} {r['verdict']:16} "
            f"rho_stock={r['rho_stock']:.4f} rho_flow={r['rho_flow']:.4f} "
            f"depth={r['cycle_depth']} vaults={r['materiality']['vault_count']} "
            f"score={r['rank_score']:.2f}"
        )


if __name__ == "__main__":
    main()
