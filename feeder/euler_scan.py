#!/usr/bin/env python3
"""
Euler v2 reflexivity 스캐너 (reflexivity_scan 의 Euler 버전 = Morpho 너머 확장 1).

Euler v2 = 퍼미션리스 모듈러 대출(EVK vault). 담보는 "다른 vault 의 지분"으로 들고,
가격은 vault.oracle()=EulerRouter 가 매김. 리플렉시브 합성자산이 상장되기 쉬운 곳.

축A(오라클): 각 borrowable vault 의 담보토큰에 대해 EulerRouter 가 쓰는 어댑터를
  getConfiguredOracle(asset, uoa) 로 얻고, name()+CrossAdapter 재귀로 leaf 피드까지 내려가
  독립 실물피드(ETH/BTC/major)에 앵커되나 vs 합성 전용/NAV(reflexive) 인지 판정.

데이터: 전부 온체인(Lens 불필요, EVK/Router getter 직접). BLOCK 고정 → 재현.
usage: python3 feeder/euler_scan.py [block] [--top N]
"""
import sys, os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from eth_utils import keccak

ROOT = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, ROOT)
import crawl as CR
from reflexivity_scan import REAL_CRYPTO, STABLE, REAL_RWA   # 앵커 자산 세트 재사용

_top_i = sys.argv.index("--top") if "--top" in sys.argv else -1
BLOCK = next((int(a) for i, a in enumerate(sys.argv)
              if i >= 1 and a.isdigit() and i != _top_i + 1), 25248315)
TOP = int(sys.argv[_top_i + 1]) if _top_i >= 0 else 30
EVK_PERSPECTIVE = "0xB30f23bc5F93F097B3A699f71B0b1718Fc82e182"   # 모든 EVK vault 열거
ANCHORS = REAL_CRYPTO | STABLE | REAL_RWA

# 실물 자산 토큰(주소) — 이게 담보면 reflexivity 문제 아님(자기참조 아닌 진짜 자산)
REAL_ADDRS = {a.lower() for a in [
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",  # WBTC
    "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf",  # cbBTC
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # WETH
    "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0",  # wstETH
    "0xcd5fe23c85820f7b72d0926fc9b05b43e359b7ee",  # weETH
    "0x8236a87084f8b84306f72007f36f2618a5634494",  # LBTC
    "0x45804880de22913dafe09f4980848ece6ecbaf78",  # PAXG
    "0x68749665ff8d2d112fa859aa293f07a622782f38",  # XAUt
]}

def sel(s): return "0x" + keccak(text=s).hex()[:8]
def call(to, d): return CR.eth_call(to, d, BLOCK)
def a32(a): return a.lower().replace("0x", "").rjust(64, "0")
def u32(n): return hex(n)[2:].rjust(64, "0")
def caddr(to, s, arg=""):
    h = call(to, sel(s) + arg)
    if not h or len(h) < 42: return None
    a = "0x" + h[-40:]; return a if int(a, 16) else None
def uint(to, s):
    h = call(to, sel(s)); return int(h, 16) if h and h != "0x" else 0
def strret(h):
    if not h or len(h) < 130: return None
    try:
        b = bytes.fromhex(h[2:]); o = int.from_bytes(b[:32], "big")
        n = int.from_bytes(b[o:o + 32], "big")
        return b[o + 32:o + 32 + n].decode("utf8", "replace").strip()
    except Exception:
        return None
def addrs(h):
    if not h or h == "0x": return []
    try:
        b = bytes.fromhex(h[2:]); o = int.from_bytes(b[:32], "big")
        if o + 32 > len(b): return []
        n = int.from_bytes(b[o:o + 32], "big")
        if o + 32 + n * 32 > len(b): return []   # 길이 초과 = 손상된 응답 → 빈 배열(크래시 방지)
        return ["0x" + b[o + 32 + i * 32 + 12: o + 32 + (i + 1) * 32].hex() for i in range(n)]
    except Exception:
        return []
def sym(a):
    if not a: return None
    try: return CR.read_symbol(a, BLOCK) or a[:8]
    except Exception: return a[:8]

# ---- 오라클 어댑터 introspection (CrossAdapter 재귀로 leaf 피드 수집) ----
def leaf_descs(adapter, depth=0, seen=None):
    if not adapter or depth > 4: return []
    seen = seen or set()
    if adapter.lower() in seen: return []
    seen.add(adapter.lower())
    nm = strret(call(adapter, sel("name()"))) or ""
    if nm == "CrossAdapter":
        return (leaf_descs(caddr(adapter, "oracleBaseCross()"), depth + 1, seen)
                + leaf_descs(caddr(adapter, "oracleCrossQuote()"), depth + 1, seen))
    # leaf: Chainlink/Redstone 류는 feed().description(); 아니면 name + base/quote 심볼
    feed = caddr(adapter, "feed()")
    d = strret(call(feed, sel("description()"))) if feed else None
    if not d:
        b = caddr(adapter, "base()"); q = caddr(adapter, "quote()")
        d = f"{sym(b)}/{sym(q)}" if b and q else nm
    return [(nm, d or nm)]

def classify_oracle(router, token, uoa):
    if not router or not token or not uoa:
        return ("none", "router/uoa 없음")
    # 담보 자체가 실물 자산(WBTC/WETH/wstETH/gold…)이면 오라클 reflexivity 무관 → anchored
    if token.lower() in REAL_ADDRS or (sym(token) or "").upper() in (REAL_CRYPTO | REAL_RWA):
        return ("anchored", "real asset collateral")
    adapter = caddr(router, "getConfiguredOracle(address,address)", a32(token) + a32(uoa))
    if not adapter:  # 직접 config 없으면 resolve (ERC4626 해석 포함)
        h = call(router, sel("resolveOracle(uint256,address,address)") + u32(10**18) + a32(token) + a32(uoa))
        if h and len(h) >= 2 + 64 * 4:
            cand = "0x" + h[2 + 64 * 3:2 + 64 * 4][-40:]
            adapter = cand if int(cand, 16) else None
    if not adapter:
        return ("none", "어댑터 없음")
    leaves = leaf_descs(adapter)
    names = " ".join(n for n, _ in leaves).lower()
    descs = " ".join(d for _, d in leaves)
    words = set(descs.replace("/", " ").upper().split())
    real_anchor = bool(words & REAL_CRYPTO)         # ETH/BTC 등 실물 crypto 도달
    fixed = "fixedrate" in names                     # 하드코딩 고정가(peg 가정) — 위험
    nav = ("fundamental" in descs.lower() or "fundamental" in names or "naked" in descs.lower())
    networks = ("chainlink", "pyth", "redstone", "chronicle", "stork")
    market = any(nw in names for nw in networks)     # 탈중앙 오라클망 시장가 피드
    # 분류 우선순위: 가격사슬이 실물(ETH/BTC)에 닿으면 중간에 fixed/NAV leg 있어도 anchored.
    #   (WBTC→BTC 고정 + BTC/USD, wstETH→ETH 등은 실물 앵커이지 peg가정 아님)
    if real_anchor:                         cls = "anchored"
    elif market and not nav and not fixed:  cls = "market-feed"     # 합성도 실제 Chainlink 시장가면 정상
    elif fixed:                             cls = "fixed/hardcoded"  # 실물앵커 없는 $1 가정 (peg risk)
    elif nav:                               cls = "fundamental/NAV"  # 자가보고 NAV, 실물여부=축B
    else:                                   cls = "other"
    sees = ", ".join(f"{n}:{d}" for n, d in leaves)[:80]
    return (cls, sees)

def main():
    print(f"# Euler v2 reflexivity scan @block {BLOCK}")
    vaults = addrs(call(EVK_PERSPECTIVE, sel("verifiedArray()")))
    print(f"# {len(vaults)} EVK vaults; ranking borrowable by totalBorrows…")
    # borrowable = oracle + LTVList 있음. 규모 = totalBorrows.
    def vinfo(v):
        r = caddr(v, "oracle()")
        if not r: return None
        coll = addrs(call(v, sel("LTVList()")))
        if not coll: return None
        return {"v": v, "router": r, "uoa": caddr(v, "unitOfAccount()"),
                "asset": caddr(v, "asset()"), "coll": coll, "borrows": uint(v, "totalBorrows()")}
    with ThreadPoolExecutor(max_workers=12) as ex:
        infos = [x for x in ex.map(vinfo, vaults) if x]
    infos.sort(key=lambda x: -x["borrows"])
    infos = infos[:TOP]
    print(f"# introspecting top {len(infos)} borrowable vaults\n")
    # (borrow vault, collateral token) 별 오라클 분류
    rows = []
    def scan(info):
        out = []
        adec = CR.get_decimals(info["asset"], BLOCK) if info["asset"] else 18
        for cv in info["coll"]:
            tok = caddr(cv, "asset()") or cv
            cls, sees = classify_oracle(info["router"], tok, info["uoa"])
            out.append((sym(info["asset"]), sym(tok), cls, sees))
        return out
    with ThreadPoolExecutor(max_workers=10) as ex:
        for r in ex.map(scan, infos):
            rows += r
    # 위험 오라클 = 고정가(peg 가정) + 자가NAV. 시장피드/실물앵커는 정상.
    from collections import Counter
    danger = {"fixed/hardcoded": "HIGH", "fundamental/NAV": "MED"}
    risky = [r for r in rows if r[2] in danger]
    print(f"총 {len(rows)} (borrow-vault, collateral) 쌍.  오라클 분류:", dict(Counter(r[2] for r in rows)))
    print(f"위험 오라클(고정가/NAV)로 가격되는 담보: {len(risky)}\n")
    print("=== Euler 담보 中 가격발견 취약 오라클 (token 별 dedup) ===")
    seen = {}
    for borrow, tok, cls, sees in risky:
        if tok in seen: continue
        seen[tok] = (cls, sees)
    for tok, (cls, sees) in sorted(seen.items(), key=lambda kv: kv[1][0]):
        print(f"  [{danger[cls]:4}] {tok:14} 오라클[{cls}]: {sees}")
    # --- JSON 출력 (프론트/통합 리포트용): 담보토큰별 최악 오라클 클래스 ---
    import json
    SEV = {"fixed/hardcoded": 3, "fundamental/NAV": 2, "ext-feed?": 1,
           "market-feed": 0, "anchored": 0, "other": 0, "none": -1}
    gmap = {"fixed/hardcoded": "HIGH", "fundamental/NAV": "MED"}
    tokrec = {}
    for borrow, tok, cls, sees in rows:
        cur = tokrec.get(tok)
        if cur is None or SEV.get(cls, 0) > SEV.get(cur["oracle_class"], 0):
            tokrec[tok] = {"token": tok, "oracle_class": cls, "sees": sees,
                           "grade": gmap.get(cls, "ok"), "borrows": list((cur or {}).get("borrows", []))}
        if borrow not in tokrec[tok]["borrows"]:
            tokrec[tok]["borrows"].append(borrow)
    res = {"venue": "euler", "block": BLOCK, "tokens": tokrec}
    p = os.path.join(ROOT, "..", "graphs", "frontend", "euler.json")
    json.dump(res, open(p, "w"), indent=2)
    print(f"\nsaved -> {os.path.abspath(p)}  ({len(tokrec)} collateral tokens)")

if __name__ == "__main__":
    main()
