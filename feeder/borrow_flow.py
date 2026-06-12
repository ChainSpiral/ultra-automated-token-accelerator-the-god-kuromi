#!/usr/bin/env python3
"""
Borrow-flow research helper.

This is intentionally event-first, not holder-snapshot-first:
  1. read current supply/borrow state for the selected loan assets
  2. collect recent Borrow events from Aave/Spark and Morpho Blue
  3. for the largest borrows, follow the borrowed token's first outbound hop

It reuses flow_trace.py for Alchemy asset-transfer pagination/caching.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict

from eth_utils import keccak

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache", "borrow_flow")
os.makedirs(CACHE, exist_ok=True)

sys.path.insert(0, ROOT)
import crawl as CR
import flow_trace as FT

ZERO = "0x0000000000000000000000000000000000000000"
MORPHO = "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb"
MORPHO_GQL = "https://blue-api.morpho.org/graphql"
ETHERSCAN_API_KEY = FT.E.get("ETHERSCAN_API_KEY", "")

TOKENS = {
    "USDC": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    "WETH": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
}

POOLS = [
    {"name": "Aave V3 Ethereum", "kind": "aave", "address": "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2"},
    {"name": "SparkLend", "kind": "aave", "address": "0xc13e21b648a5ee794902342038ff3adab66be987"},
    {"name": "Aave Lido", "kind": "aave", "address": "0x4e033931ad43597d96d6bcc25c280717730b58b1"},
]

GET_RESERVE_DATA = "0x35ea6a75"
MARKET = "0x5c60e39a"
BALANCE_OF = "0x70a08231"
TOTAL_SUPPLY = "0x18160ddd"
DECIMALS = "0x313ce567"

AAVE_BORROW_TOPIC = "0x" + keccak(text="Borrow(address,address,address,uint256,uint8,uint256,uint16)").hex()
MORPHO_BORROW_TOPIC = "0x" + keccak(text="Borrow(bytes32,address,address,address,uint256,uint256)").hex()
TRANSFER_TOPIC = "0x" + keccak(text="Transfer(address,address,uint256)").hex()

KNOWN_LABELS = {
    ZERO: "mint/burn",
    MORPHO: "Morpho Blue",
    "0x111111125421ca6dc452d289314280a0f8842a65": "1inch Aggregation Router V6",
    "0x1111111254eeb25477b68fb85ed929f73a960582": "1inch Aggregation Router V5",
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff": "0x Exchange Proxy",
    "0x9008d19f58aabd9ed0d60971565aa8510560ab41": "CoW Protocol GPv2Settlement",
    "0x000000000022d473030f116ddee9f6b43ac78ba3": "Uniswap Permit2",
    "0x66a9893cc07d91d95644aedd05d03f95e1dba8af": "Uniswap Universal Router",
    "0x0000000000001ff3684f28c67538d4d072c22734": "Uniswap Universal Router",
}


def cache_get(key):
    path = os.path.join(CACHE, key + ".json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def cache_put(key, value):
    with open(os.path.join(CACHE, key + ".json"), "w") as f:
        json.dump(value, f)


def topic_addr(addr):
    return "0x" + addr.lower().replace("0x", "").rjust(64, "0")


def word_addr(word):
    return "0x" + word[-40:].lower()


def split_words(data):
    if not data or data == "0x":
        return []
    s = data[2:]
    return ["0x" + s[i:i + 64] for i in range(0, len(s), 64)]


def call(to, data, block):
    tag = hex(block) if isinstance(block, int) else block
    return FT.rpc("eth_call", [{"to": to, "data": data}, tag])


def call_uint(to, selector, block):
    h = call(to, selector, block)
    return int(h, 16) if h and h != "0x" else 0


def erc20_decimals(token, block):
    try:
        return call_uint(token, DECIMALS, block)
    except Exception:
        return 18


def erc20_total_supply(token, block, decimals):
    if not token or token == ZERO:
        return 0.0
    try:
        return call_uint(token, TOTAL_SUPPLY, block) / (10 ** decimals)
    except Exception:
        return 0.0


def erc20_balance(token, holder, block, decimals):
    try:
        return call_uint(token, BALANCE_OF + topic_addr(holder)[2:], block) / (10 ** decimals)
    except Exception:
        return 0.0


def latest_block():
    return int(FT.rpc("eth_blockNumber", []), 16)


def etherscan_logs(address, topics, frm, to):
    if not ETHERSCAN_API_KEY:
        return None
    # Etherscan does not support JSON-RPC topic OR arrays in this endpoint.
    if any(isinstance(t, list) for t in topics if t is not None):
        return None
    params = {
        "chainid": "1",
        "module": "logs",
        "action": "getLogs",
        "fromBlock": str(frm),
        "toBlock": str(to),
        "address": address,
        "apikey": ETHERSCAN_API_KEY,
    }
    for i, topic in enumerate(topics):
        if topic:
            params[f"topic{i}"] = topic
    url = "https://api.etherscan.io/v2/api?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    raw = json.loads(urllib.request.urlopen(req, timeout=60).read())
    status = raw.get("status")
    msg = (raw.get("message") or "").lower()
    result = raw.get("result")
    if status == "1" and isinstance(result, list):
        # Etherscan can truncate large log result sets. Split if we hit the common cap.
        if len(result) >= 1000 and to > frm:
            mid = (frm + to) // 2
            left = etherscan_logs(address, topics, frm, mid) or []
            right = etherscan_logs(address, topics, mid + 1, to) or []
            return left + right
        time.sleep(0.22)
        return result
    if status == "0" and ("no records" in msg or result == []):
        time.sleep(0.22)
        return []
    if to > frm:
        mid = (frm + to) // 2
        left = etherscan_logs(address, topics, frm, mid) or []
        right = etherscan_logs(address, topics, mid + 1, to) or []
        return left + right
    raise RuntimeError(f"Etherscan getLogs failed: {raw}")


def get_logs(address, topics, frm, to, chunk=10):
    fp = f"{address}_{frm}_{to}_{'_'.join(json.dumps(t, sort_keys=True) for t in topics)}"
    key = "logs_" + hashlib.md5(fp.encode()).hexdigest()
    cached = cache_get(key)
    if cached is not None:
        return cached
    es = etherscan_logs(address, topics, frm, to)
    if es is not None:
        cache_put(key, es)
        return es
    out = []
    start = frm
    while start <= to:
        end = min(to, start + chunk - 1)
        params = {"address": address, "fromBlock": hex(start), "toBlock": hex(end), "topics": topics}
        for attempt in range(5):
            try:
                out.extend(FT.rpc("eth_getLogs", [params]))
                break
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(0.4 * (attempt + 1))
        start = end + 1
    cache_put(key, out)
    return out


def tx_receipt(txhash):
    key = "receipt_" + txhash
    cached = cache_get(key)
    if cached is not None:
        return cached
    r = FT.rpc("eth_getTransactionReceipt", [txhash])
    cache_put(key, r)
    return r


def tx_by_hash(txhash):
    key = "tx_" + txhash
    cached = cache_get(key)
    if cached is not None:
        return cached
    r = FT.rpc("eth_getTransactionByHash", [txhash])
    cache_put(key, r)
    return r


def is_contract(addr, block):
    key = f"code_{addr}_{block}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    code = FT.rpc("eth_getCode", [addr, hex(block) if isinstance(block, int) else block])
    out = bool(code and code != "0x")
    cache_put(key, out)
    return out


def label_address(addr, block):
    a = (addr or ZERO).lower()
    if a in KNOWN_LABELS:
        return KNOWN_LABELS[a]
    key = f"label_{a}_{block}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    label = ""
    try:
        c = CR.classify(a, block)
        label = c.get("label") or c.get("kind") or ""
    except Exception:
        label = ""
    if not label:
        try:
            label = CR.etherscan_name(a) or ""
        except Exception:
            label = ""
    if not label:
        label = "contract" if is_contract(a, block) else "EOA"
    cache_put(key, label)
    return label


def intent_for(addr, label, contract):
    s = f"{addr} {label}".lower()
    if not contract:
        return "eoa_or_wallet"
    if "aave" in s or "spark" in s or "atoken" in s or "morpho" in s or "compound" in s or "comet" in s:
        return "lending_redeposit_or_repay"
    if "uniswap" in s or "curve" in s or "balancer" in s or "1inch" in s or "0x exchange" in s or "cow protocol" in s:
        return "swap_route"
    if "bridge" in s or "stargate" in s or "across" in s or "hop" in s or "celer" in s or "synapse" in s:
        return "bridge"
    if "safe" in s or "gnosis" in s:
        return "safe_or_custody"
    return "contract_unknown"


def aave_reserve_state(pool, token, symbol, block):
    h = call(pool["address"], GET_RESERVE_DATA + topic_addr(token)[2:], block)
    words = split_words(h)
    if len(words) < 11:
        return None
    atoken = word_addr(words[8])
    stable_debt = word_addr(words[9])
    variable_debt = word_addr(words[10])
    if atoken == ZERO:
        return None
    dec = erc20_decimals(token, block)
    supply = erc20_total_supply(atoken, block, dec)
    liquidity = erc20_balance(token, atoken, block, dec)
    stable = erc20_total_supply(stable_debt, block, dec)
    variable = erc20_total_supply(variable_debt, block, dec)
    borrowed = stable + variable
    if supply <= 0 and borrowed <= 0 and liquidity <= 0:
        return None
    return {
        "venue": pool["name"],
        "kind": "aave_family",
        "token": symbol,
        "pool": pool["address"],
        "aToken": atoken,
        "stableDebtToken": stable_debt,
        "variableDebtToken": variable_debt,
        "supply": supply,
        "liquidity": liquidity,
        "borrowed": borrowed,
        "stableBorrowed": stable,
        "variableBorrowed": variable,
        "utilization": borrowed / supply if supply else None,
    }


def gql(query):
    req = urllib.request.Request(
        MORPHO_GQL,
        data=json.dumps({"query": query}).encode(),
        headers={"content-type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=60).read()).get("data") or {}


def morpho_markets_for_token(token):
    key = "morpho_markets_v2_" + token.lower()
    cached = cache_get(key)
    if cached is not None:
        return cached
    q = (
        '{ markets(first:1000, where:{chainId_in:[1], loanAssetAddress_in:["%s"]}){ items{ '
        'marketId state{ supplyAssets borrowAssets collateralAssets } '
        'loanAsset{symbol decimals address} collateralAsset{symbol decimals address} } } }'
    ) % token
    items = ((gql(q).get("markets") or {}).get("items") or [])
    cache_put(key, items)
    return items


def morpho_state(token, symbol, block):
    dec = erc20_decimals(token, block)
    scale = 10 ** dec
    rows = []
    total_supply = 0.0
    total_borrow = 0.0
    for m in morpho_markets_for_token(token):
        mid = m["marketId"].lower()
        st = m.get("state") or {}
        supply = float(st.get("supplyAssets") or 0) / scale
        borrow = float(st.get("borrowAssets") or 0) / scale
        if supply <= 0 and borrow <= 0:
            continue
        coll = (m.get("collateralAsset") or {})
        row = {
            "venue": "Morpho Blue",
            "kind": "morpho_market",
            "token": symbol,
            "marketId": mid,
            "collateral": coll.get("symbol") or "",
            "collateralAddress": (coll.get("address") or "").lower(),
            "supply": supply,
            "borrowed": borrow,
            "liquidity": max(supply - borrow, 0),
            "utilization": borrow / supply if supply else None,
        }
        rows.append(row)
        total_supply += supply
        total_borrow += borrow
    rows.sort(key=lambda x: -x["borrowed"])
    return {
        "venue": "Morpho Blue",
        "kind": "morpho_aggregate",
        "token": symbol,
        "supply": total_supply,
        "borrowed": total_borrow,
        "liquidity": max(total_supply - total_borrow, 0),
        "utilization": total_borrow / total_supply if total_supply else None,
        "stateSource": "morpho_graphql_current",
        "markets": rows,
    }


def collect_aave_borrows(pool, token, symbol, frm, to, decimals):
    logs = get_logs(pool["address"], [AAVE_BORROW_TOPIC, topic_addr(token)], frm, to)
    out = []
    for lg in logs:
        words = split_words(lg.get("data"))
        if len(words) < 4:
            continue
        receiver = word_addr(words[0])
        amount = int(words[1], 16) / (10 ** decimals)
        on_behalf = word_addr(lg["topics"][2]) if len(lg.get("topics", [])) > 2 else receiver
        out.append({
            "venue": pool["name"],
            "kind": "aave_borrow",
            "token": symbol,
            "tokenAddress": token,
            "block": int(lg["blockNumber"], 16),
            "tx": lg["transactionHash"],
            "txFrom": "",
            "receiver": receiver,
            "onBehalfOf": on_behalf,
            "amount": amount,
        })
    return out


def collect_morpho_borrows(token, symbol, frm, to, decimals):
    markets = morpho_markets_for_token(token)
    mids = [m["marketId"].lower() for m in markets]
    mid_set = set(mids)
    out = []
    if not mid_set:
        return out
    logs = get_logs(MORPHO, [MORPHO_BORROW_TOPIC], frm, to)
    for lg in logs:
        mid = lg["topics"][1].lower()
        if mid not in mid_set:
            continue
        words = split_words(lg.get("data"))
        if len(words) < 3:
            continue
        receiver = word_addr(lg["topics"][3])
        on_behalf = word_addr(lg["topics"][2])
        caller = word_addr(words[0])
        amount = int(words[1], 16) / (10 ** decimals)
        out.append({
            "venue": "Morpho Blue",
            "kind": "morpho_borrow",
            "token": symbol,
            "tokenAddress": token,
            "marketId": mid,
            "block": int(lg["blockNumber"], 16),
            "tx": lg["transactionHash"],
            "txFrom": "",
            "caller": caller,
            "receiver": receiver,
            "onBehalfOf": on_behalf,
            "amount": amount,
        })
    return out


def transfer_from_log(lg, token, decimals):
    if (lg.get("address") or "").lower() != token.lower():
        return None
    topics = lg.get("topics") or []
    if len(topics) < 3 or topics[0].lower() != TRANSFER_TOPIC:
        return None
    return {
        "from": word_addr(topics[1]),
        "to": word_addr(topics[2]),
        "amount": int(lg.get("data") or "0x0", 16) / (10 ** decimals),
    }


def same_tx_outflows(event, decimals):
    receipt = tx_receipt(event["tx"])
    out = []
    receiver = event["receiver"].lower()
    token = event["tokenAddress"].lower()
    for lg in receipt.get("logs", []):
        t = transfer_from_log(lg, token, decimals)
        if not t:
            continue
        if t["from"].lower() != receiver:
            continue
        # Exclude zero-value oddities; this is after the borrow transfer into receiver.
        if t["amount"] <= 0:
            continue
        out.append(t)
    return out


def later_outflows(event, decimals, lookahead):
    frm = event["block"]
    to = event["block"] + lookahead
    receiver = event["receiver"].lower()
    token = event["tokenAddress"].lower()
    rows = FT.asset_transfers("from", receiver, frm, to, [token])
    out = []
    for r in rows:
        if (r.get("hash") or "").lower() == event["tx"].lower():
            continue
        if ((r.get("rawContract") or {}).get("address") or "").lower() != token:
            continue
        f = (r.get("from") or ZERO).lower()
        if f != receiver:
            continue
        amount = float(r.get("value") or 0)
        if amount <= 0:
            continue
        out.append({
            "from": f,
            "to": (r.get("to") or ZERO).lower(),
            "amount": amount,
            "block": int(r["blockNum"], 16),
            "tx": r.get("hash"),
        })
    out.sort(key=lambda x: (x.get("block", frm), -x["amount"]))
    return out


def enrich_event(event, block, decimals, lookahead):
    event = dict(event)
    if not event.get("txFrom"):
        tx = tx_by_hash(event["tx"])
        event["txFrom"] = (tx.get("from") or "").lower()
    event["receiverIsContract"] = is_contract(event["receiver"], block)
    event["receiverLabel"] = label_address(event["receiver"], block)
    event["txFromIsContract"] = is_contract(event["txFrom"], block) if event.get("txFrom") else None
    event["txFromLabel"] = label_address(event["txFrom"], block) if event.get("txFrom") else ""
    flows = same_tx_outflows(event, decimals)
    source = "same_tx"
    if not flows:
        flows = later_outflows(event, decimals, lookahead)
        source = f"next_{lookahead}_blocks"
    enriched = []
    top_flows = flows[:5]
    total_flow = sum(f["amount"] for f in top_flows)
    scale = (event["amount"] / total_flow) if total_flow > event["amount"] > 0 else 1.0
    for f in top_flows:
        dest = f["to"].lower()
        contract = is_contract(dest, block)
        label = label_address(dest, block)
        attributed = f["amount"] * scale
        enriched.append({
            "source": source,
            "to": dest,
            "toLabel": label,
            "toIsContract": contract,
            "intent": intent_for(dest, label, contract),
            "amount": f["amount"],
            "attributedAmount": attributed,
            "fractionOfBorrow": attributed / event["amount"] if event["amount"] else None,
            "rawFractionOfBorrow": f["amount"] / event["amount"] if event["amount"] else None,
            "block": f.get("block", event["block"]),
            "tx": f.get("tx", event["tx"]),
        })
    event["firstHopOutflows"] = enriched
    if not enriched:
        event["firstHopOutflows"] = [{
            "source": "none_found",
            "to": event["receiver"],
            "toLabel": event["receiverLabel"],
            "toIsContract": event["receiverIsContract"],
            "intent": "held_or_untraced",
            "amount": 0,
            "attributedAmount": 0,
            "fractionOfBorrow": 0,
            "rawFractionOfBorrow": 0,
            "block": event["block"],
            "tx": event["tx"],
        }]
    return event


def aggregate_flows(events):
    agg = {}
    for ev in events:
        for hop in ev.get("firstHopOutflows", []):
            key = (ev["token"], ev["venue"], hop["to"], hop["intent"])
            row = agg.setdefault(key, {
                "token": ev["token"],
                "venue": ev["venue"],
                "to": hop["to"],
                "toLabel": hop["toLabel"],
                "intent": hop["intent"],
                "amount": 0.0,
                "borrowCount": 0,
                "exampleTx": hop["tx"],
            })
            row["amount"] += hop.get("attributedAmount", hop.get("amount", 0))
            row["borrowCount"] += 1
    return sorted(agg.values(), key=lambda x: -x["amount"])


def summarize_by_intent(events):
    agg = defaultdict(lambda: {"amount": 0.0, "count": 0})
    for ev in events:
        # Count only the largest hop for each borrow event to avoid double-counting router splits.
        hops = sorted(ev.get("firstHopOutflows", []), key=lambda h: -h.get("amount", 0))
        hop = hops[0] if hops else {"intent": "held_or_untraced", "amount": 0}
        key = (ev["token"], hop["intent"])
        agg[key]["amount"] += hop.get("attributedAmount", hop.get("amount", 0))
        agg[key]["count"] += 1
    return [
        {"token": k[0], "intent": k[1], "amount": v["amount"], "count": v["count"]}
        for k, v in sorted(agg.items(), key=lambda kv: (kv[0][0], -kv[1]["amount"]))
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokens", default="USDC,WETH")
    ap.add_argument("--from-block", type=int)
    ap.add_argument("--to-block", type=int)
    ap.add_argument("--window", type=int, default=50000)
    ap.add_argument("--lookahead", type=int, default=7200)
    ap.add_argument("--top-events", type=int, default=25)
    ap.add_argument("--out", default="graphs/borrow_flow_usdc_weth.json")
    args = ap.parse_args()

    to_block = args.to_block or latest_block()
    from_block = args.from_block or max(0, to_block - args.window)
    block = to_block
    selected = [(s.strip(), TOKENS.get(s.strip(), s.strip()).lower()) for s in args.tokens.split(",") if s.strip()]

    states = []
    all_events = []
    for symbol, token in selected:
        dec = erc20_decimals(token, block)
        for pool in POOLS:
            try:
                print(f"state/events: {pool['name']} {symbol}", file=sys.stderr)
                st = aave_reserve_state(pool, token, symbol, block)
                if st:
                    states.append(st)
                    all_events.extend(collect_aave_borrows(pool, token, symbol, from_block, to_block, dec))
            except Exception as ex:
                print(f"skip {pool['name']} {symbol}: {ex}", file=sys.stderr)
        try:
            print(f"state/events: Morpho Blue {symbol}", file=sys.stderr)
            mst = morpho_state(token, symbol, block)
            states.append(mst)
            all_events.extend(collect_morpho_borrows(token, symbol, from_block, to_block, dec))
        except Exception as ex:
            print(f"skip Morpho {symbol}: {ex}", file=sys.stderr)

    # Sample the largest borrow events per token while preserving cross-venue cases.
    sampled = []
    for symbol, _token in selected:
        rows = [e for e in all_events if e["token"] == symbol]
        rows.sort(key=lambda x: -x["amount"])
        sampled.extend(rows[:args.top_events])

    enriched = []
    for i, ev in enumerate(sampled, 1):
        print(f"[{i}/{len(sampled)}] {ev['token']} {ev['venue']} borrow {ev['amount']:.4f} @ {ev['block']}", file=sys.stderr)
        dec = erc20_decimals(ev["tokenAddress"], block)
        enriched.append(enrich_event(ev, block, dec, args.lookahead))

    result = {
        "metadata": {
            "block": block,
            "from_block": from_block,
            "to_block": to_block,
            "lookahead_blocks": args.lookahead,
            "top_events_per_token": args.top_events,
            "venues": [p["name"] for p in POOLS] + ["Morpho Blue"],
            "notes": [
                "Aave-family state is onchain at block.",
                "Morpho market ids and aggregate state come from the Morpho GraphQL current API.",
                "Flow sample follows largest borrow events, not every small borrow.",
            ],
        },
        "states": states,
        "borrow_event_count": len(all_events),
        "sampled_event_count": len(enriched),
        "sampled_events": enriched,
        "flow_aggregate": aggregate_flows(enriched),
        "intent_summary": summarize_by_intent(enriched),
    }

    out = args.out
    if not os.path.isabs(out):
        out = os.path.join(os.path.dirname(ROOT), out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
