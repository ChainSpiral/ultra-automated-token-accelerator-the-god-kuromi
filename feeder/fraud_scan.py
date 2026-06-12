#!/usr/bin/env python3
"""
fraud_scan — Morpho 메인넷 전 마켓에 'BONDUSD 지문' 결정적 스캔 (사기/wash 후보 랭킹).

BONDUSD 전수조사에서 뽑아낸 측정 가능한 신호를 코드로 일반화:
  A. econ_impossible : 마켓 borrow > 대출토큰 총공급  (>1배 = phantom/불가능)
  B. self_deal       : util≈100% AND supply==borrow (단일주체 자기대출 지문)
  C. collat_unknown  : 담보가 정상셋 밖 (long-tail)
  D. collat_unpriced : collateralAssetsUsd=null (오라클이 USD로 못 매김 = bespoke)
  E. warnings        : Morpho 자체 경고(unrecognized_collateral / not_whitelisted)
  F. usd_inflation   : GraphQL borrowUsd 가 borrow×$1 대비 과대 (IRM phantom 누적)
점수 높을수록 BONDUSD 류. 1단계(결정적 그물) — 상위는 에이전트 딥다이브(작살)로.

usage: python3 feeder/fraud_scan.py [--min-borrow USD] [--top N]
"""
import json, os, sys, math, urllib.request, urllib.error, collections

API = "https://blue-api.morpho.org/graphql"
ENV = "/Users/link/podotree/.env"

def load_env():
    e = {}
    for ln in open(ENV):
        ln = ln.strip()
        if "=" in ln and not ln.startswith("#"):
            k, v = ln.split("=", 1); e[k.strip()] = v.strip()
    return e
RPC = load_env().get("ETH_RPC")

def gql(q):
    r = urllib.request.Request(API, data=json.dumps({"query": q}).encode(),
                               headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(r, timeout=60).read()).get("data") or {}
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"GQL {e.code}: {e.read()[:200].decode()}\n"); return {}

_TS = {}
def total_supply(token, dec):
    if token in _TS: return _TS[token]
    body = {"jsonrpc": "2.0", "id": 1, "method": "eth_call",
            "params": [{"to": token, "data": "0x18160ddd"}, "latest"]}
    try:
        r = urllib.request.Request(RPC, data=json.dumps(body).encode(),
                                   headers={"Content-Type": "application/json"})
        h = json.loads(urllib.request.urlopen(r, timeout=30).read()).get("result")
        v = (int(h, 16) / 10 ** dec) if h and h != "0x" else 0.0
    except Exception:
        v = 0.0
    _TS[token] = v; return v

KNOWN = {"WETH","wstETH","WBTC","cbBTC","USDC","USDT","DAI","stETH","weETH","ezETH","rsETH",
    "cbETH","sDAI","USDe","sUSDe","rETH","tBTC","LBTC","USDS","sUSDS","PYUSD","USD0","USD0++",
    "crvUSD","GHO","mETH","pufETH","ETHx","osETH","swETH","frxETH","sfrxETH","FRAX","wbETH",
    "rswETH","uniBTC","solvBTC","eBTC","pumpBTC","MKR","AAVE","UNI","LINK","COMP","RLUSD","AUSD",
    "USDtb","sUSDS","USR","wstUSR","deUSD","sdeUSD"}

# 풍부한 쿼리 시도 → 실패 시 최소 쿼리로 폴백 (스키마 변동 대비)
RICH = ('items{ lltv oracleAddress '
        'listed warnings{ type level } '
        'loanAsset{ symbol address decimals } collateralAsset{ symbol address decimals } '
        'state{ borrowAssets supplyAssets borrowAssetsUsd supplyAssetsUsd collateralAssetsUsd utilization } }')
MIN = ('items{ lltv oracleAddress '
       'loanAsset{ symbol address decimals } collateralAsset{ symbol address decimals } '
       'state{ borrowAssets supplyAssets borrowAssetsUsd supplyAssetsUsd collateralAssetsUsd utilization } }')

def pull():
    for fields in (RICH, MIN):
        items = []
        ok = True
        for skip in range(0, 1500, 300):
            q = ('{ markets(first:300, skip:%d, orderBy:SupplyAssetsUsd, orderDirection:Desc, '
                 'where:{chainId_in:[1]}){ %s } }') % (skip, fields)
            batch = (gql(q).get("markets") or {}).get("items")
            if batch is None: ok = False; break
            items += batch
            if len(batch) < 300: break
        if ok and items:
            return items, (fields is RICH)
    return [], False

def main():
    min_borrow = float(sys.argv[sys.argv.index("--min-borrow")+1]) if "--min-borrow" in sys.argv else 50_000
    top = int(sys.argv[sys.argv.index("--top")+1]) if "--top" in sys.argv else 40
    items, rich = pull()
    print(f"# Morpho 메인넷 마켓 {len(items)}개 (rich={rich})\n")

    rows = []
    for m in items:
        c = m.get("collateralAsset") or {}; l = m.get("loanAsset") or {}; st = m.get("state") or {}
        csym = c.get("symbol"); lsym = l.get("symbol")
        if not csym or not lsym: continue
        ldec = l.get("decimals") or 18
        borrow = int(st.get("borrowAssets") or 0) / 10 ** ldec
        supply = int(st.get("supplyAssets") or 0) / 10 ** ldec
        borrowUsd = st.get("borrowAssetsUsd") or 0
        if borrowUsd < min_borrow and supply * 1 < 1_000_000:  # 의미없는 더스트 마켓 컷
            continue
        util = st.get("utilization") or 0
        lsup = total_supply(l["address"], ldec) if l.get("address") else 0

        sig = {}
        score = 0.0
        # A. econ_impossible
        if lsup > 0 and borrow > 0:
            ratio = borrow / lsup
            sig["borrow/loanSupply"] = round(ratio, 2)
            if ratio > 1.0: score += 4 + min(4, math.log10(ratio))
        # B. self_deal proxy
        if util and util > 0.99 and supply > 0 and abs(supply - borrow) / supply < 1e-4:
            score += 3; sig["self_deal(util≈1,supply==borrow)"] = True
        # C. collat unknown
        if csym not in KNOWN:
            score += 1; sig["collat_unknown"] = csym
        # D. collat unpriced (bespoke oracle)
        if st.get("collateralAssetsUsd") in (None, 0) and borrow > 0:
            score += 1.5; sig["collat_unpriced(USD=null)"] = True
        # E. warnings
        ws = [w.get("type") for w in (m.get("warnings") or []) if isinstance(w, dict)]
        flagw = [w for w in ws if w in ("unrecognized_collateral_asset", "not_whitelisted", "unrecognized_oracle")]
        if flagw:
            score += len(flagw); sig["warnings"] = flagw
        if m.get("listed") is False:
            score += 0.5; sig["listed"] = False
        # F. usd_inflation (borrowUsd 가 borrow 대비 비현실적 — 대출토큰 stable 가정 $1 근처)
        if borrow > 0 and borrowUsd / borrow > 3:   # $/token > 3 면 IRM phantom 의심(스테이블/달러류 대상)
            if any(k in lsym.lower() for k in ("usd", "dai", "usr", "dola")):
                score += 2; sig["usd_inflation($/tok=%.1f)" % (borrowUsd / borrow)] = True

        rows.append({"score": round(score, 2), "collat": csym, "loan": lsym,
                     "collat_addr": c.get("address"), "loan_addr": l.get("address"),
                     "oracle": m.get("oracleAddress"), "lltv": m.get("lltv"),
                     "borrowUsd": borrowUsd, "borrow": borrow, "loanSupply": lsup,
                     "util": util, "signals": sig})

    rows.sort(key=lambda r: -r["score"])
    print(f"{'SCORE':>5}  {'COLLATERAL':16}{'LOAN':10}{'borrowUsd':>14}  신호")
    print("-" * 110)
    for r in rows[:top]:
        if r["score"] < 2: break
        sigs = " ".join(f"{k}={v}" for k, v in r["signals"].items())
        print(f"{r['score']:5.1f}  {r['collat'][:15]:16}{r['loan'][:9]:10}{r['borrowUsd']:>14,.0f}  {sigs}")
    cands = [r for r in rows if r["score"] >= 2]
    out = os.path.join(os.path.dirname(__file__), "..", "graphs", "fraud_candidates.json")
    json.dump({"n_markets": len(rows), "candidates": cands}, open(out, "w"), indent=2)
    print(f"\n# 총 {len(rows)}개 마켓 채점, score≥2 후보 {len(cands)}개 → {os.path.abspath(out)}")

if __name__ == "__main__":
    main()
