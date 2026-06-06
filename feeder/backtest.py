#!/usr/bin/env python3
"""
역사적 백테스트 — "사고가 터지기 전에 reflexivity 스캐너가 미리 경고했는가?"
큐레이터/퀀트 셀링포인트: precision 증명.

방법: 전부 온체인 + block 고정(GQL=live 라 안 씀 → 진짜 과거 재현).
  사고 토큰의 알려진 Morpho 마켓을 사고 N일 전 블록에서 읽어:
   - idToMarketParams → 오라클/담보/대출 (immutable)
   - reflexivity_scan.oracle_introspect 로 분류 (그 블록 기준)
   - market() → 당시 차입 규모
  → reflexive 오라클(bespoke/NAV·self-NAV)로 분류됐으면 = 그때 이미 flag 가능했음.

usage: python3 feeder/backtest.py
"""
import sys, os
ROOT = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, ROOT)
import crawl as CR
import reflexivity_scan as RS

S_IDP = "0x2c3c9157"; S_MKT = "0x5c60e39a"
def words(h):
    if not h or h == "0x": return []
    b = bytes.fromhex(h[2:]); return [int.from_bytes(b[i:i + 32], "big") for i in range(0, len(b), 32)]
def b32(x): return x.lower().replace("0x", "").rjust(64, "0")
def aa(w): return "0x" + hex(w)[2:].rjust(64, "0")[-40:]

# 토큰 단위(여러 마켓 中 하나라도 reflexive 면 flag — 스캐너가 top-market 만 보던 한계도 보완)
INCIDENTS = [
    {"name": "USD0++ depeg", "incident": "2025-01-10", "iblock": 21592744,
     "token": "0x35d8949372d46b7a3d5a56006ae77b215fc69bc0",
     "pre": [("2024-12-01", 21303934), ("incident-3d", 21592744 - 21600)]},
    {"name": "xUSD (Stream)", "incident": "2025-11-04", "iblock": 23722236,
     "token": "0xe2fc85bfb48c4cf147921fbe110cf92ef9f26f94",
     "pre": [("2025-10-01", 23479244), ("incident-3d", 23722236 - 21600)]},
    {"name": "sdeUSD/deUSD (Stream)", "incident": "2025-11-04", "iblock": 23722236,
     "token": "0x5c5b196abe0d54485975d1ec29617d42d9198326",
     "pre": [("2025-10-01", 23479244), ("incident-3d", 23722236 - 21600)]},
]
CONTROLS = [
    {"name": "weETH (정상)", "block": 23479244, "token": "0xcd5fe23c85820f7b72d0926fc9b05b43e359b7ee"},
    {"name": "wstETH (정상)", "block": 23479244, "token": "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0"},
]

import urllib.request
def market_ids(token):
    q = ('{ markets(first:40, where:{collateralAssetAddress_in:["%s"]}){ items{ marketId } } }') % token
    r = urllib.request.Request("https://blue-api.morpho.org/graphql",
        data=__import__("json").dumps({"query": q}).encode(), headers={"content-type": "application/json"})
    d = __import__("json").loads(urllib.request.urlopen(r, timeout=40).read()).get("data", {})
    return [m["marketId"] for m in (d.get("markets") or {}).get("items", [])]

SEV = {"bespoke/NAV": 3, "self-NAV": 2, "ext-feed?": 1, "market-feed": 0, "anchored": 0, "other": 0, "none": -1}
def assess_token(token, block):
    """토큰의 모든 마켓을 block 시점에 평가 → 가장 reflexive 한 결과 반환 (없으면 None)."""
    best = None
    for mid in market_ids(token):
        r = assess(mid, block)
        if not r: continue
        if best is None or SEV.get(r["cls"], 0) > SEV.get(best["cls"], 0):
            best = {**r, "mid": mid}
    return best

def assess(mid, block):
    RS.BLOCK = block  # introspection 을 이 블록 기준으로 (모듈 전역 재설정)
    p = words(CR.eth_call(RS.MORPHO, S_IDP + b32(mid), block))
    if len(p) < 5 or int(p[2]) == 0:
        return None
    loan, collat, oracle = aa(p[0]), aa(p[1]), aa(p[2])
    csym = CR.read_symbol(collat, block) or collat[:8]
    r = RS.oracle_introspect(oracle, collat, csym, CR.etherscan_name(oracle))
    m = words(CR.eth_call(RS.MORPHO, S_MKT + b32(mid), block))
    ldec = CR.get_decimals(loan, block)
    borrow = (m[2] / 10 ** ldec) if len(m) > 2 else 0   # 대출토큰 decimals 반영
    flagged = r["cls"] in ("bespoke/NAV", "self-NAV")
    return {"cls": r["cls"], "sees": r["sees"], "borrow": borrow,
            "collat": csym, "loan": CR.read_symbol(loan, block) or loan[:8], "flagged": flagged}

def main():
    print("# REFLEXIVITY 백테스트 — 사고 전 사전탐지 검증 (on-chain, block-pinned)\n")
    hit = tot = 0
    for inc in INCIDENTS:
        print(f"=== {inc['name']} (사고 {inc['incident']}, block {inc['iblock']}) ===")
        any_flag = False
        for label, blk in inc["pre"]:
            days = (inc["iblock"] - blk) * 12 // 86400
            r = assess_token(inc["token"], blk)
            if not r:
                print(f"  {label} (사고 {days}일 전, blk {blk}): 시장/오라클 미생성")
                continue
            mark = "✅ FLAGGED" if r["flagged"] else "❌ missed"
            any_flag = any_flag or r["flagged"]
            print(f"  {label} (사고 ~{days}일 전): {mark} — 오라클[{r['cls']}] "
                  f"{r['collat']}→{r['loan']} 차입 ${r['borrow']:,.0f}  (mkt {r['mid'][:10]})")
            print(f"       {r['sees']}")
        tot += 1; hit += 1 if any_flag else 0
        print(f"  → {inc['name']}: {'사고 전 탐지 성공' if any_flag else '미탐지'}\n")
    # 대조군: 정상 토큰이 같은 시점에 안 걸려야 함(false-positive 체크)
    print("=== 정상 대조군 (false-positive 체크) ===")
    fp = 0
    for c in CONTROLS:
        r = assess_token(c["token"], c["block"])
        if not r:
            print(f"  {c['name']}: 시장 없음"); continue
        clean = not r["flagged"]
        if not clean: fp += 1
        print(f"  {c['name']}: 최악마켓 오라클[{r['cls']}] {r['collat']}→{r['loan']} → "
              f"{'clean(정상)' if clean else 'FALSE POSITIVE'}")
    print(f"\n=== 결과: 사고 {hit}/{tot} 건을 사고 전에 reflexive 오라클로 탐지 / 대조군 false-positive {fp}/{len(CONTROLS)} ===")

if __name__ == "__main__":
    main()
