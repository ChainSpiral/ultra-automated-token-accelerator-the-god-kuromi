#!/usr/bin/env python3
"""
REFLEXIVITY / 순환-백킹 스캐너 (사기성 구조 탐지).

근본 기준(사용자 정의):
  진짜 사기 = "받은 진짜 자산을 준비금으로 안 들고, 자기 토큰을 만드는 데 써서
              토큰이 자기 자신으로 백킹되는 순환구조." (예: xUSD←deUSD←xUSD, UST↔LUNA)
  레버리지 루프(rsETH 루핑)나 만기불일치(USD0++)는 사기 아님 — 밑에 실물이 있고 사이클이 없음.

탐지 두 축:
  1) 백킹 사이클 — 토큰 T 를 받치는 자산을 따라가면 T 로 돌아오나? (holdings 방향)
     edge T→U  :  asset()/underlying() (4626/wrapper)  또는  T 준비금이 U 를 보유.
     스캔셋 안에서 Tarjan SCC 로 사이클 검출.
  2) 오라클 reflexivity — T 가 담보로 쓰이는 대출시장(Morpho)의 오라클이 무엇을 보나?
     독립 실물피드(안전) vs T 자기풀/NAV/하드코딩(reflexive, 위험).

모든 값 BLOCK 고정 → 재현. usage: python3 feeder/reflexivity_scan.py [block]
"""
import json, os, re, sys, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from eth_utils import keccak

ROOT = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, ROOT)
import crawl as CR   # eth_call, read_addr, balanceof, etherscan_name, SEL, get_decimals ...

# BLOCK 파싱: --auto 뒤 숫자(=토큰개수)는 block 으로 오인하면 안 됨 → 그 위치 제외.
_auto_i = sys.argv.index("--auto") if "--auto" in sys.argv else -1
BLOCK = next((int(a) for i, a in enumerate(sys.argv) if i >= 1 and a.isdigit() and i != _auto_i + 1),
             25248315)
MORPHO = "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb"
MORPHO_GQL = "https://blue-api.morpho.org/graphql"
S_IDPARAMS = "0x2c3c9157"  # idToMarketParams(bytes32)->(loan,collateral,oracle,irm,lltv)

# 스캔 대상 (검증된 메인넷 주소). xUSD=사기 양성대조, rsETH/USDe 류=정상 대조.
TOKENS = {
    "xUSD":  "0xe2fc85bfb48c4cf147921fbe110cf92ef9f26f94",
    "deUSD": "0x15700b564ca08d9439c58ca5053166e8317aa138",
    "sdeUSD":"0x5c5b196abe0d54485975d1ec29617d42d9198326",
    "USDe":  "0x4c9edd5852cd905f086c759e8383e09bff1e68b3",
    "sUSDe": "0x9d39a5de30e57443bff2a8307a4256c8797a3497",
    "USD0":  "0x73a15fed60bf67631dc6cd7bc5b6e8da8190acf5",
    "USD0++":"0x35d8949372d46b7a3d5a56006ae77b215fc69bc0",
    "reUSD": "0x57ab1e0003f623289cd798b1824be09a793e4bec",
    "crvUSD":"0xf939e0a03fb07f59a73314e73794be0e57ac1b4e",
    "GHO":   "0x40d16fc0246ad3160ccc09b8d0d3a2cd28ae6c2f",
    "USDS":  "0xdc035d45d973e3ec169d2276ddab16f1e407384f",
    "sUSDS": "0xa3931d71877c0e7a3148cb7eb4463524fec27fbd",
    "rsETH": "0xa1290d69c65a6fe4df752f95823fae25cb99e5a7",
    "weETH": "0xcd5fe23c85820f7b72d0926fc9b05b43e359b7ee",
    "ezETH": "0xbf5495efe5db9ce00f80364c8b423567e58d2110",
    "pufETH":"0xd9a442856c234a39a81a089c06451ebaa4306a72",
    "frxUSD":"0xcacd6fd266af91b8aed52accc382b4e165586e29",
}
ADDR2SYM = {v.lower(): k for k, v in TOKENS.items()}
SET = {a.lower() for a in TOKENS.values()}

def gql(query):
    try:
        d = CR._post(MORPHO_GQL, {"query": query}, {"content-type": "application/json"})
        return d.get("data") or {}
    except Exception:
        return {}

# ---------- 축1: 백킹 그래프 ----------
def backing_edges(sym, addr):
    """T 가 의존하는(=백킹) 토큰들. asset()/underlying() + T 준비금(자기 컨트랙트)이 보유한 셋 토큰."""
    edges = {}   # U_addr -> reason
    # 4626 / wrapper 언래핑
    for sel, why in ((CR.SEL["asset"], "asset()"), (CR.SEL["underlying"], "underlying()")):
        u = CR.read_addr(addr, sel, BLOCK)
        if u and u.lower() in SET and u.lower() != addr:
            edges[u.lower()] = why
    # T 준비금이 보유한 다른 셋 토큰 (T 컨트랙트 주소가 reserve 인 경우 — 4626 vault 등)
    for usym, uaddr in TOKENS.items():
        ul = uaddr.lower()
        if ul == addr or ul in edges: continue
        bal = CR.balanceof(uaddr, addr, BLOCK)
        if bal <= 0: continue
        dec = CR.get_decimals(uaddr, BLOCK)
        amt = bal / (10 ** dec)
        ts = CR.total_supply(uaddr, BLOCK) / (10 ** dec)
        # 먼지/우발 보유 제외: U 총공급의 0.1% 이상 들고 있어야 "백킹"으로 인정 (USD0 가 USD0++ 4개 들고있는 류 차단)
        if ts > 0 and amt / ts >= 0.001:
            edges[ul] = f"holds {amt:,.0f} {usym} ({amt/ts*100:.1f}% of supply)"
    return edges

# ---------- 축2: 오라클 ----------
def collateral_oracle(addr):
    """T 가 담보인 Morpho 시장 中 가장 reflexive 한(worst-oracle) 시장의 오라클+규모+빌리는 자산.
    distressed/규모/집중도(mid)는 그 worst-oracle 시장 기준으로 일관 보고. (size 최대 시장은 size_* 로 별도 보존)"""
    q = ('{ markets(first:30, where:{collateralAssetAddress_in:["%s"]}){ items{ '
         'marketId loanAsset{symbol} oracleAddress collateralAsset{priceUsd} '
         'state{collateralAssetsUsd supplyAssetsUsd borrowAssetsUsd} } } }') % addr
    items = (gql(q).get("markets") or {}).get("items") or []
    if not items:
        return None
    # GQL collateralAssetsUsd 가 null/0 인 시장 많음 → 담보·공급·차입 중 max 로 시장 규모 산정
    def msize(m):
        st = m.get("state") or {}
        return max(st.get("collateralAssetsUsd") or 0, st.get("supplyAssetsUsd") or 0,
                   st.get("borrowAssetsUsd") or 0)
    items.sort(key=lambda m: -msize(m))
    top = items[0]   # size 최대 시장 (참고용 보존 — size_mid/size_usd)
    # ★ multi-market: 상위 10개 마켓의 오라클을 모두 분류해 가장 reflexive 한 것 채택
    #   (top-by-size 마켓만 보면, 안전한 큰 마켓 + reflexive 작은 마켓 토큰을 놓침)
    SEV = {"bespoke/NAV": 3, "self-NAV": 2, "ext-feed?": 1, "market-feed": 0, "anchored": 0, "other": 0, "none": -1}
    csym = ADDR2SYM.get(addr, "?")
    worst = None   # (sev, cls, sees, oracle, market_dict)
    for m in items[:10]:
        orc = m.get("oracleAddress")
        if not orc: continue
        r = oracle_introspect(orc, addr, csym, CR.etherscan_name(orc))
        sev = SEV.get(r["cls"], 0)
        if worst is None or sev > worst[0]:
            worst = (sev, r["cls"], r["sees"], orc, m)
    if worst is None:
        worst = (-1, "none", "오라클 없음", top.get("oracleAddress"), top)
    wm = worst[4]                                   # worst-oracle 시장 = 보고 기준 시장
    wmid = wm["marketId"]
    tot = round(msize(wm))                          # ★ 규모도 worst-oracle 시장 기준 (오라클과 일관)
    cp = (wm.get("collateralAsset") or {}).get("priceUsd")
    distressed = ((cp is None) or (cp < 0.01)) and tot >= 1_000_000
    return {"market": wmid[:10], "mid": wmid,       # mid=worst-oracle 시장 (집중도·오라클 모두 이 시장 기준 → 일관)
            "worst_mid": wmid, "loan": wm["loanAsset"]["symbol"],
            "oracle": worst[3], "oracle_name": CR.etherscan_name(worst[3]) if worst[3] else None,
            "n_markets": len(items), "collat_usd": tot, "collat_price": cp, "distressed": distressed,
            "size_mid": top["marketId"], "size_usd": round(msize(top)),   # 참고: size 최대 시장(별도 라벨, 미카운트)
            "_collat": addr, "_precls": worst[1], "_presees": worst[2]}

# --- 축B: 대출 시장 자기거래/집중 탐지 (private/sole-borrower 패턴 = Stream xUSD 수법) ---
def market_risk(mid):
    """시장 포지션 조회 → 차입자 집중도 + 같은 주체가 공급+차입(self-dealing) 여부."""
    if not mid:
        return None
    q = ('{ marketPositions(first:60, orderBy:BorrowShares, orderDirection:Desc, '
         'where:{marketUniqueKey_in:["%s"]}){ items{ user{address} '
         'state{ borrowAssetsUsd supplyAssetsUsd collateralUsd } } } }') % mid
    items = (gql(q).get("marketPositions") or {}).get("items") or []
    borrowers = [(i["user"]["address"].lower(), (i.get("state") or {}).get("borrowAssetsUsd") or 0,
                  (i.get("state") or {}).get("supplyAssetsUsd") or 0) for i in items]
    borrowers = [b for b in borrowers if b[1] > 0]
    if not borrowers:
        return {"n_borrowers": 0, "conc": 0, "self_deal": False, "borrow_usd": 0}
    tot = sum(b[1] for b in borrowers)
    self_deal = [b[0] for b in borrowers if b[2] > 0]   # 차입+공급 동시 = 자기 대출 자기가 댐
    return {"n_borrowers": len(borrowers), "conc": max(b[1] for b in borrowers) / tot if tot else 0,
            "self_deal": bool(self_deal), "self_deal_addr": self_deal[:1], "borrow_usd": round(tot)}

# --- 정밀 오라클 introspection: MorphoChainlinkOracleV2 getter 를 keccak 셀렉터로 직접 호출 ---
REAL_CRYPTO = {"ETH", "WETH", "STETH", "WSTETH", "BTC", "WBTC", "CBBTC", "TBTC", "LBTC"}
STABLE = {"USDC", "USDT", "DAI"}            # 가장 깊은 독립 가격발견 스테이블
REAL_RWA = {"XAU", "XAUT", "GOLD", "PAXG"}  # 독립 실물(금) — XAU/USD 등도 외부 앵커

def _sel(sig): return "0x" + keccak(text=sig).hex()[:8]
def _caddr(o, sig):
    h = CR.eth_call(o, _sel(sig), BLOCK)
    if not h or h == "0x" or len(h) < 42: return None
    a = "0x" + h[-40:]; return a if int(a, 16) != 0 else None
def _desc(f):
    h = CR.eth_call(f, _sel("description()"), BLOCK)
    if not h or h == "0x" or len(h) < 130: return None
    try:
        b = bytes.fromhex(h[2:]); off = int.from_bytes(b[:32], "big")
        ln = int.from_bytes(b[off:off + 32], "big")
        return b[off + 32:off + 32 + ln].decode("utf8", "replace").strip()
    except Exception:
        return None

def oracle_introspect(oracle, collat, collat_sym, oracle_name):
    """오라클이 '무엇을 보는지' 정밀 판정: 가격이 독립 실물피드(ETH/USD 등)에 앵커되나,
    아니면 합성자산 자기 전용피드/NAV(reflexive)에만 의존하나."""
    if not oracle: return {"cls": "none", "sees": "대출담보 시장 없음"}
    if (CR.get_code(oracle, BLOCK) or "0x") == "0x": return {"cls": "none", "sees": "EOA"}
    # 담보 자체가 실물 자산(WBTC/WETH/wstETH/gold…)이면 reflexivity 무관 → anchored (euler_scan 과 일관)
    if collat_sym and collat_sym.upper() in (REAL_CRYPTO | REAL_RWA):
        return {"cls": "anchored", "sees": "real asset collateral"}
    bv = _caddr(oracle, "BASE_VAULT()")
    # ★ 담보(BASE) 측 피드만으로 분류. QUOTE_FEED 는 대출/통화(USD) 정규화라 담보 reflexivity 와 무관.
    #   (예: USD0++ 시장 [BASE:USD0++/USD, QUOTE:USDC/USD] → USDC 때문에 anchored 오판하던 FN 수정)
    feeds = [f for f in (_caddr(oracle, s) for s in ("BASE_FEED_1()", "BASE_FEED_2()")) if f]
    descs = [(_desc(f) or "?") for f in feeds]
    # 실물 앵커 판정: 피드 설명에 실물자산 심볼이 "단어"로 등장하면 앵커됨.
    #   "rsETH/ETH exchange rate" → 단어 {RSETH,ETH,..} ∩ 실물 = {ETH} → 앵커 (ETH 표시가)
    #   "xUSD/USD" → 단어 {XUSD,USD} ∩ 실물 = ∅ → 앵커 아님 (USD 는 fiat 단위, 실물 아님)
    anchored = any(set(re.split(r"[\s/]+", d.upper())) & (REAL_CRYPTO | STABLE | REAL_RWA) for d in descs)
    vault_self = False
    if bv:
        und = CR.read_addr(bv, CR.SEL["asset"], BLOCK)
        vault_self = (bv.lower() == collat) or (und and und.lower() == collat)
    und0 = CR.read_addr(collat, CR.SEL["asset"], BLOCK)
    synth = {collat_sym.upper()} | ({ADDR2SYM.get(und0.lower(), "").upper()} if und0 else set())
    synth.discard("")
    def _words(s): return set(re.split(r"[^A-Za-z0-9+]+", s.upper()))
    # NAV/펀더멘털 = 자가보고(reflexive). 합성 자기참조는 단어경계 매칭(부분문자열 오탐 방지).
    nav = any(k in d.lower() for d in descs for k in ("fundamental", "naked"))
    refs_synth = any(synth & _words(d) for d in descs)
    # market-feed: 실제 오라클 네트워크(Chainlink/Pyth/RedStone…)가 가격 소스면 합성이라도 정상 시장가.
    #   네트워크 이름이 피드 컨트랙트명 또는 description 에 있으면 인정 (prose 피드 "RedStone Price Feed for USDe" 포함).
    #   단 "fundamental"/"naked"(자가 NAV)는 nav 가 먼저 잡으므로 여기 안 옴.
    NETS = ("chainlink", "pyth", "redstone", "chronicle", "stork", "aggregator")
    feed_names = [(CR.etherscan_name(f) or "") for f in feeds]
    market = bool(feeds) and (not nav) and \
        any(any(nw in (nm + " " + d).lower() for nw in NETS) for nm, d in zip(feed_names, descs))
    sees = ", ".join(([("VAULT=SELF" if vault_self else "VAULT=" + ADDR2SYM.get((bv or '').lower(), (bv or '')[:8]))] if bv else [])
                     + [f"FEED:{d}" for d in descs]) or "(MorphoChainlink getter 없음)"
    if anchored:                       cls = "anchored"        # 실물 앵커 — 안전
    elif nav:                          cls = "bespoke/NAV"     # 자가보고 NAV/펀더멘털 — reflexive
    elif market:                       cls = "market-feed"     # 실제 네트워크 시장가 피드 — 정상
    elif refs_synth:                   cls = "bespoke/NAV"     # 합성 전용 피드(네트워크 아님) — 신뢰기반
    elif vault_self and not feeds:     cls = "self-NAV"        # 자기 convertToAssets, peg 가정
    elif not bv and not feeds:
        # MorphoChainlink 아님 → 바이트코드에서 담보/기초자산 주소 참조 여부로 coarse 판정
        lc = (CR.get_code(oracle, BLOCK) or "").lower()
        refs = (collat[2:].lower() in lc) or (und0 and und0[2:].lower() in lc)
        cls = "bespoke/NAV" if refs else "ext-feed?"
        sees = ("비표준 오라클: 바이트코드가 담보 참조(자기NAV류)" if refs
                else "비표준 오라클(외부피드 추정, 수동확인)")
    else:                              cls = "other"
    return {"cls": cls, "sees": sees}

def classify_oracle(o):
    # collateral_oracle 가 이미 multi-market 최악 분류를 _precls/_presees 에 계산해둠 (중복 introspection 제거)
    if not o: return ("none", "대출담보 시장 없음")
    return (o.get("_precls", "none"), o.get("_presees", ""))

# ---------- 사이클 검출 (Tarjan) ----------
# --- 토큰 자동발굴: Morpho 담보 universe 를 시장규모순으로 (하드코딩 목록 대신) ---
def discover_tokens(n):
    q = ('{ markets(first:300, orderBy:SupplyAssetsUsd, orderDirection:Desc, where:{chainId_in:[1]}){ '
         'items{ collateralAsset{address symbol} state{collateralAssetsUsd supplyAssetsUsd} } } }')
    items = (gql(q).get("markets") or {}).get("items") or []
    sz = defaultdict(float); sym = {}
    for m in items:
        c = m.get("collateralAsset")
        if not c or not c.get("address"): continue
        a = c["address"].lower(); sym[a] = c.get("symbol") or a[:8]
        st = m.get("state") or {}
        sz[a] += max(st.get("collateralAssetsUsd") or 0, st.get("supplyAssetsUsd") or 0)
    out = {}
    for a, _ in sorted(sz.items(), key=lambda kv: -kv[1])[:n]:
        s = sym[a]
        while s in out: s += "_"
        out[s] = a
    return out

def find_scc(graph):
    idx = {}; low = {}; on = {}; st = []; cnt = [0]; out = []
    sys.setrecursionlimit(10000)
    def strong(v):
        idx[v] = low[v] = cnt[0]; cnt[0] += 1; st.append(v); on[v] = True
        for w in graph.get(v, ()):
            if w not in idx: strong(w); low[v] = min(low[v], low[w])
            elif on.get(w): low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            comp = []
            while True:
                w = st.pop(); on[w] = False; comp.append(w)
                if w == v: break
            out.append(comp)
    for v in list(graph):
        if v not in idx: strong(v)
    return out

def main():
    global TOKENS, ADDR2SYM, SET
    if "--auto" in sys.argv:
        i = sys.argv.index("--auto")
        N = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 and sys.argv[i + 1].isdigit() else 25
        disc = discover_tokens(N)
        ctrl = {"xUSD": "0xe2fc85bfb48c4cf147921fbe110cf92ef9f26f94",   # 사기 대조군 항상 포함
                "USD0++": "0x35d8949372d46b7a3d5a56006ae77b215fc69bc0"}
        have = {a.lower() for a in disc.values()}
        TOKENS = {**disc, **{k: v for k, v in ctrl.items() if v.lower() not in have}}
        ADDR2SYM = {v.lower(): k for k, v in TOKENS.items()}
        SET = {a.lower() for a in TOKENS.values()}
        print(f"# auto-discovered {len(TOKENS)} Morpho 담보 토큰 (시장규모순)")
    print(f"# reflexivity scan @block {BLOCK}  ({len(TOKENS)} tokens)\n")
    # 1) 백킹 엣지 (병렬)
    def be(item): s, a = item; return s, backing_edges(s, a.lower())
    with ThreadPoolExecutor(max_workers=8) as ex:
        backing = dict(ex.map(be, TOKENS.items()))
    graph = {TOKENS[s].lower(): set(backing[s].keys()) for s in TOKENS}
    # 2) 오라클 (병렬)
    def oc(item): s, a = item; return s, collateral_oracle(a.lower())
    with ThreadPoolExecutor(max_workers=6) as ex:
        oracles = dict(ex.map(oc, TOKENS.items()))
    # 2b) 시장 자기거래/집중 (축B, 병렬)
    def mr(s): return s, (market_risk(oracles[s]["mid"]) if oracles[s] else None)
    with ThreadPoolExecutor(max_workers=6) as ex:
        risks = dict(ex.map(mr, TOKENS))
    # 3) 사이클(순환 백킹)
    sccs = [c for c in find_scc(graph) if len(c) > 1]
    # self-loop (T 가 자기를 직접 백킹) 도 사이클 — SCC 출력에 포함시켜 cycle 플래그와 일관성 유지
    sccs += [[a] for a, deps in graph.items() if a in deps]
    in_cycle = {a for c in sccs for a in c}

    print("순환 백킹 SCC:", [[ADDR2SYM.get(a, a[:8]) for a in c] for c in sccs] or "없음", "\n")
    rows = []; records = {}
    for s, a in TOKENS.items():
        al = a.lower()
        ocls, sees = classify_oracle(oracles[s])
        cyc = al in in_cycle
        o = oracles[s]; rk = risks.get(s)
        # 축B: sole-borrower(=private 시장, Stream 수법) — 집중>90% & 차입자≤2 & 의미있는 $.
        #   (self-dealing=공급+차입 동일주체는 그냥 "루핑"이라 정상 → 등급에서 제외, 정보로만)
        looping = bool(rk and rk.get("self_deal"))
        # 집중 = 한 차입자가 90%+ 점유 & 의미있는 규모 (차입자 수 무관 — conc 가 이미 독점 포착)
        sole = bool(rk and rk["conc"] > 0.90 and rk["borrow_usd"] >= 1_000_000)
        reflexive = ocls in ("bespoke/NAV",)
        distressed = bool(o and o.get("distressed"))
        # 등급: DISTRESSED(담보 가격불가+큰부채=이미 frozen/bad-debt, 신규위험 아님) 를 먼저 분리.
        #       그 다음 LIVE 위험: 순환백킹/private+reflexive=CRITICAL; 전용피드/private=HIGH; 자기NAV=MED
        if distressed: grade = "DISTRESSED"
        elif cyc or (sole and reflexive): grade = "CRITICAL"
        elif reflexive or sole: grade = "HIGH"
        elif ocls == "self-NAV": grade = "MED"
        elif ocls == "ext-feed?": grade = "CHECK"   # 비표준 오라클, 외부피드 추정(수동확인)
        else: grade = "ok"
        deps = ", ".join(f"{ADDR2SYM.get(u,u[:6])}({why})" for u, why in backing[s].items()) or "-"
        bsig = ""
        if rk and rk["n_borrowers"]:
            flags = []
            if sole: flags.append("★sole-borrower(private)")
            if looping: flags.append("looping")
            bsig = f" | 시장:{rk['n_borrowers']}borrowers 집중{rk['conc']*100:.0f}% ${rk['borrow_usd']:,}" + ("/" + ",".join(flags) if flags else "")
        frozen_tag = " ⚠FROZEN(담보 가격불가→이미 bad-debt/aftermath 가능)" if distressed else ""
        lends = (f"→{o['loan']} 담보시장 (${o['collat_usd']:,}) | 오라클[{ocls}]: {sees}{bsig}{frozen_tag}"
                 if o else "담보로 안 쓰임")
        rows.append((grade, s, cyc, ocls, deps, lends))
        records[s] = {
            "grade": grade, "token": a, "cycle": cyc, "oracle_class": ocls, "sees": sees,
            "distressed": distressed, "backing": deps,
            "loan": (o or {}).get("loan"), "collat_usd": (o or {}).get("collat_usd", 0),
            "oracle": (o or {}).get("oracle"), "oracle_name": (o or {}).get("oracle_name"),
            "n_markets": (o or {}).get("n_markets", 0),
            "concentration": (rk["conc"] if rk else None), "n_borrowers": (rk["n_borrowers"] if rk else 0),
            "borrow_usd": (rk["borrow_usd"] if rk else 0), "sole_borrower": sole, "looping": looping,
        }
    # 출력
    order = {"CRITICAL": 0, "DISTRESSED": 1, "HIGH": 2, "MED": 3, "CHECK": 4, "ok": 5}
    rows.sort(key=lambda r: (order.get(r[0], 9), r[1]))
    print(f"{'GRADE':9}{'TOKEN':8}{'순환백킹':8} 담보로 무엇을 빌리나 / 오라클이 보는 것")
    print("-" * 115)
    for grade, s, cyc, ocls, deps, lends in rows:
        print(f"{grade:9}{s:8}{('CYCLE!' if cyc else '-'):8} {lends}")
        if deps != "-": print(f"{'':17}└ 백킹: {deps[:90]}")
    # save
    res = {"block": BLOCK, "scc": [[ADDR2SYM.get(a, a) for a in c] for c in sccs],
           "order": ["CRITICAL", "DISTRESSED", "HIGH", "MED", "CHECK", "ok"],
           "tokens": records}
    p = os.path.join(ROOT, "..", "graphs", "frontend", "reflexivity.json")
    json.dump(res, open(p, "w"), indent=2)
    print(f"\nsaved -> {os.path.abspath(p)}")

if __name__ == "__main__":
    main()
