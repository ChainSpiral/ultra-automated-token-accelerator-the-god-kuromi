#!/usr/bin/env python3
"""
Value-FLOW tracer (snapshot crawler 의 자매품).

crawl.py 는 "한 block 에 누가 무엇을 들고 있나"(정적 holdings)를 본다.
flow_trace.py 는 "돈이 시간 순서로 어떻게 흘렀나"(동적 flow)를 본다.
  - 노드 = 주소(EOA 포함! crawl 과 달리 EOA 가 leaf 가 아님)
  - 엣지 = ERC20 Transfer 집계 (token, amount, count, tx) — 방향 있음
  - 0x0 = mint/burn 센티넬
  - 사이클(자기 자신에게 가치가 돌아오는 닫힌 경로) 자동 탐지 → in_cycle 마킹
    = "자기 IOU 로 자기를 받쳐 공짜 민팅" 같은 reflexive loop 가 그래프에서 그대로 보인다.

데이터 소스: alchemy_getAssetTransfers (wide-range, decimal 디코딩, 페이지네이션).
재현성: from/to block 고정 + 캐시. 같은 (seeds, range) 재실행은 동일 그래프.

usage:
  python3 feeder/flow_trace.py --seeds 0x..,0x.. --from BLK --to BLK \
      [--depth 2] [--maxnodes 80] [--tokens xUSD,deUSD,sdeUSD,USDC,USDT] --out FILE
"""
import argparse, hashlib, json, os, sys, time, urllib.request, urllib.error
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache", "flow"); os.makedirs(CACHE, exist_ok=True)
ENV = "/Users/link/podotree/.env"
ZERO = "0x0000000000000000000000000000000000000000"
MORPHO = "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb"

# 라벨/분류는 정적 크롤러의 classify() 재사용 (A): symbol()·어댑터·Etherscan 자동 해석 + 캐시.
sys.path.insert(0, ROOT)
import crawl as CR

def load_env():
    e = {}
    for ln in open(ENV):
        ln = ln.strip()
        if "=" in ln and not ln.startswith("#"):
            k, v = ln.split("=", 1); e[k.strip()] = v.strip()
    return e
E = load_env()
RPC = E["ETH_RPC"]; ETHERSCAN = E.get("ETHERSCAN_API_KEY", "")

# 심볼 -> 주소 단축맵 (CLI 편의용. 여기 없는 심볼/주소도 동작 — classify 가 알아서 라벨).
# Morpho 담보/대출에 흔한 토큰까지 포함해 "다 보이게"의 기본 필터를 넓힘.
TOKENS = {
    "xUSD":   "0xe2fc85bfb48c4cf147921fbe110cf92ef9f26f94",
    "deUSD":  "0x15700b564ca08d9439c58ca5053166e8317aa138",
    "sdeUSD": "0x5c5b196abe0d54485975d1ec29617d42d9198326",
    "USDC":   "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    "USDT":   "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "WETH":   "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    "wstETH": "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0",
    "WBTC":   "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",
    "cbBTC":  "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf",
    # 다른 셀프루핑/리플렉시브 사건 토큰 (확장 테스트용)
    "USD0":   "0x73a15fed60bf67631dc6cd7bc5b6e8da8190acf5",
    "USD0++": "0x35d8949372d46b7a3d5a56006ae77b215fc69bc0",
    "reUSD":  "0x57ab1e0003f623289cd798b1824be09a793e4bec",
    "crvUSD": "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e",
    "MIM":    "0x99d8a9c45b2eca8864373a26d1459e3dff1e17f3",
    "FEI":    "0x956f47f50a910163d8bf957cf5846d573e7f87ca",
}
# 사람만 아는 포렌식 태그(override 최우선). 나머지 라벨은 classify() 가 자동 해석.
KNOWN = {
    "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb": "Morpho Blue",
    "0xcb4a7b790edb7fa3e2731efd7ed85275f92fc74a": "deUSD seller (Curve, 보도)",
    ZERO: "mint / burn",
}

# ---------- low level ----------
def _post(body):
    req = urllib.request.Request(RPC, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
    for attempt in range(4):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=90).read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 3:
                time.sleep(0.6 * (attempt + 1)); continue
            raise
def rpc(method, params):
    j = _post({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if "error" in j: raise RuntimeError(f"{method}: {j['error']}")
    return j["result"]

def cache_get(key):
    p = os.path.join(CACHE, key + ".json")
    return json.load(open(p)) if os.path.exists(p) else None
def cache_put(key, val):
    json.dump(val, open(os.path.join(CACHE, key + ".json"), "w"))

# ---------- asset transfers (paginated, cached) ----------
def asset_transfers(direction, addr, frm, to, contracts):
    """direction: 'from'|'to'. 한 주소의 해당 방향 erc20 transfer 전부 (window 내)."""
    # 캐시키에 토큰필터 지문 포함 — 필터 바뀌면 캐시 재사용 안 되도록(스테일 방지).
    # hashlib 로 안정적 지문(파이썬 hash()는 프로세스마다 달라 재현성 깨짐).
    fp = "all" if not contracts else hashlib.md5(
        ",".join(sorted(c.lower() for c in contracts)).encode()).hexdigest()[:8]
    ck = f"{direction}_{addr}_{frm}_{to}_{fp}"
    c = cache_get(ck)
    if c is not None: return c
    out = []; page = None
    base = {"fromBlock": hex(frm), "toBlock": hex(to), "category": ["erc20"],
            "withMetadata": False, "maxCount": hex(1000),
            ("fromAddress" if direction == "from" else "toAddress"): addr}
    if contracts: base["contractAddresses"] = contracts
    while True:
        p = dict(base)
        if page: p["pageKey"] = page
        r = rpc("alchemy_getAssetTransfers", [p])
        out += r.get("transfers", [])
        page = r.get("pageKey")
        if not page: break
        time.sleep(0.05)
    cache_put(ck, out); return out

# (A) 라벨링은 crawl 의 캐시된 1차 함수만 가볍게 재사용 (classify 전체는 노드당 ~6콜이라 무거움).
#     getCode(EOA판별, 캐시) → symbol(토큰이면 심볼) → Etherscan 이름(캐시). ~2콜/노드.
#     반환: (label, kind)  kind ∈ {mint_burn, EOA, token, contract}
_SYM = {}
def _symbol(addr, block):
    if addr in _SYM: return _SYM[addr]
    c = cache_get("sym_" + addr)
    if c is None:
        c = CR.read_symbol(addr, block) or ""
        cache_put("sym_" + addr, c)
    _SYM[addr] = c or None; return _SYM[addr]

def resolve(addr, block):
    if addr == ZERO:
        return KNOWN[ZERO], "mint_burn"
    code = CR.get_code(addr)                 # 캐시됨
    is_eoa = (not code or code == "0x")
    if addr in KNOWN:                        # 포렌식 태그 override 최우선
        return KNOWN[addr], ("EOA" if is_eoa else "contract")
    if is_eoa:
        return "EOA " + addr[:10], "EOA"
    sym = _symbol(addr, block)
    if sym:
        return sym, "token"                  # xUSD/deUSD/USDC …
    nm = CR.etherscan_name(addr)             # 캐시됨(미스 시 0.21s)
    if nm:
        return nm, "contract"                # CoW=GPv2Settlement, Morpho 마켓 등
    return "contract " + addr[:10], "contract"

# ---------- BFS flow trace (레벨별 병렬 fetch) ----------
# bottleneck = getAssetTransfers 순차 대기. 한 depth 의 주소들을 ThreadPoolExecutor 로 동시 조회.
WORKERS = 8

def trace(seeds, frm, to, depth, maxnodes, contracts):
    seeds = [s.lower() for s in seeds]
    edges = {}                       # (f,t,asset) -> {amount,count,minblk,maxblk,tx}
    nodes = set(seeds)
    seen_addr = set()
    frontier = [s for s in seeds if s != ZERO]   # 이미 빈도순으로 정렬돼 들어옴
    for d in range(depth + 1):
        # 넓은 윈도우에서 frontier 폭발 방지: 남은 예산만큼만, 빈도 높은 순으로.
        budget = max(0, maxnodes - len(seen_addr))
        todo = [a for a in dict.fromkeys(frontier) if a not in seen_addr and a != ZERO][:budget]
        if not todo: break
        seen_addr.update(todo)
        # (addr, dir) 작업을 한 번에 병렬로
        jobs = [(a, dirn) for a in todo for dirn in ("from", "to")]
        def fetch(job):
            a, dirn = job
            try:
                return job, asset_transfers(dirn, a, frm, to, contracts)
            except Exception as ex:
                print(f"  !! {dirn} {a[:10]}: {ex}", file=sys.stderr)
                return job, []
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            results = list(ex.map(fetch, jobs))
        nxt = defaultdict(int)               # counterparty -> 등장 빈도(=중요도)
        for (a, dirn), rows in results:
            for r in rows:
                f = (r.get("from") or ZERO).lower()
                t = (r.get("to") or ZERO).lower()
                asset = r.get("asset") or "?"
                val = r.get("value") or 0.0
                blk = int(r["blockNum"], 16)
                key = (f, t, asset)
                e = edges.get(key)
                if e is None:
                    edges[key] = {"amount": val, "count": 1, "minblk": blk, "maxblk": blk,
                                  "tx": r.get("hash")}
                else:
                    e["amount"] += val; e["count"] += 1
                    e["minblk"] = min(e["minblk"], blk); e["maxblk"] = max(e["maxblk"], blk)
                for nb in (f, t):
                    if nb != ZERO: nodes.add(nb)
                cp = t if dirn == "from" else f       # counterparty → 다음 레벨
                if cp != ZERO and cp not in seen_addr: nxt[cp] += 1
        # 다음 레벨은 빈도 높은 순(가장 많이 거래된 상대 = 핵심 행위자) 으로
        frontier = [a for a, _ in sorted(nxt.items(), key=lambda kv: -kv[1])]
    return nodes, edges, seen_addr

# 라벨도 노드별 네트워크라 미리 병렬로 캐시 워밍 (Etherscan rate-limit 고려해 작은 풀).
def prewarm_labels(nodes, block):
    todo = [a for a in nodes if a != ZERO]
    def w(a):
        try: resolve(a, block)
        except Exception: pass
    with ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(w, todo))

# ---------- 병적 루프 탐지 (PATHOLOGICAL self-funding cycle) ----------
# "돈이 도는 모든 고리"(스왑 라운드트립 포함)는 노이즈다. 진짜 문제는:
#   닫힌 고리(가치가 출발점으로 복귀) 안에 **새로 만들어진/빌린 가치가 주입**된 경우.
#   injected = (0x0→X 민팅 받은 X) ∪ (Morpho→X 차입/인출 받은 X).
#   고리 위에 injected 멤버가 있어야만 = "민팅/레버리지로 만든 돈을 재순환" = 병적.
# 순수 스왑 고리(자산 교환=보존, 주입 없음)는 제외 → 정상 vault 는 깨끗해진다.
# injected_token: addr -> {그 주소가 민팅/차입으로 받은 토큰 심볼}.
# 병적 판정 = 닫힌 고리 위의 어떤 멤버가 받은 토큰 T 가, **그 고리 안에서 다시 순환**할 때.
#   (LST 처럼 정상 민팅은 토큰을 보유/LP 할 뿐 자기 고리로 되돌리지 않음 → 제외됨)
def find_cycles(roots, nodes, edges, injected_token, maxlen=5):
    adj = defaultdict(list)  # node -> [(neighbor, edge_key, asset)]  (0x0 제외)
    for (f, t, a) in edges:
        if f != ZERO and t != ZERO and f != t:
            adj[f].append((t, (f, t, a), a))
    roots = [s for s in dict.fromkeys(roots) if s in nodes]
    cyc_nodes = set(); cyc_edges = set()
    sys.setrecursionlimit(10000)
    for s in roots:
        def dfs(v, path, epath, assets):
            if len(epath) >= maxlen:
                return
            for (w, ek, asset) in adj.get(v, ()):
                if w == s and len(epath) >= 1:           # s 로 복귀 = 닫힌 고리
                    ring = set(path) | {s}
                    ring_assets = assets | {asset}
                    # ★ 루트 s 가 민팅/차입으로 받은 "자기 토큰"이 자기 고리로 되돌아올 때만 = 자기참조 루프.
                    #   (정상 토큰이 홀더들 사이를 도는 우발적 고리는 s 본인 주입토큰과 무관 → 제외)
                    if injected_token.get(s, frozenset()) & ring_assets:
                        cyc_nodes.update(ring); cyc_edges.update(epath + [ek])
                elif w not in path and w != s:
                    dfs(w, path + [w], epath + [ek], assets | {asset})
        dfs(s, [s], [], set())
    return cyc_nodes, cyc_edges

# ---------- assemble frontend JSON ----------
def build_json(seeds, frm, to, nodes, edges, explored):
    seeds_l = [s.lower() for s in seeds]
    # 그래프 = "탐색한 코어"(fetch 한 노드) + 그들끼리의 엣지 + mint/burn·Morpho.
    # 미탐색 leaf(경계 밖, 한 번만 등장) 수천 개는 버린다 — 사이클은 코어 안에 있음.
    keep = set(explored) | {ZERO, MORPHO}
    edges = {(f, t, a): e for (f, t, a), e in edges.items() if f in keep and t in keep}
    used = set()
    for (f, t, _a) in edges:
        used.add(f); used.add(t)
    nodes = {n for n in nodes if n in used}
    prewarm_labels(nodes, to)               # 코어 노드 라벨 병렬 워밍(이후 resolve 는 캐시 적중)
    # 레버리지 주입: 주소 X 가 **차입**(Morpho→X)으로 받은 토큰. (민팅은 모든 토큰의 정상 동작이라
    # 제외 — LRT/스테이블은 항상 민팅하므로 false positive. 위험은 "빌린 가치"의 재순환에서 온다.)
    # TODO: Aave/Curve-llamalend/Fraxlend 등 다른 대출 소스도 등록하면 reUSD 류도 잡힘(현재 미커버).
    LENDERS = {MORPHO}
    injected_token = defaultdict(set)
    for (f, t, a) in edges:
        if f in LENDERS and t != ZERO: injected_token[t].add(a)
    # 고리 탐색 뿌리 = seed ∪ 차입받은 주소
    roots = list(set(seeds_l) | set(injected_token))
    cyclic, cyc_edges = find_cycles(roots, nodes, edges, injected_token)
    out_nodes = []
    for a in sorted(nodes):
        label, kind = resolve(a, to)        # (A) classify 기반 자동 라벨
        out_nodes.append({
            "id": a, "type": "address",
            "label": label,
            "data": {
                "kind": kind,
                "is_seed": a in seeds_l,
                "in_cycle": a in cyclic,
                "address": a,
            },
        })
    out_edges = []
    for (f, t, asset), e in edges.items():
        # (C) Morpho Blue 와의 transfer 는 담보/차입 의미를 라벨에 부여
        role = None
        if t == MORPHO: role = "공급/담보"
        elif f == MORPHO: role = "차입/인출"
        base = f"{asset} {e['amount']:,.0f}" + (f" ×{e['count']}" if e["count"] > 1 else "")
        out_edges.append({
            "id": f"{f}->{t}:{asset}",
            "source": f, "target": t,
            "asset": asset, "amount": round(e["amount"], 4), "count": e["count"],
            "role": role,
            "label": (f"[{role}] " if role else "") + base,
            "block_range": [e["minblk"], e["maxblk"]],
            "sample_tx": e["tx"],
            "in_cycle": (f, t, asset) in cyc_edges,
            "morpho": (f == MORPHO or t == MORPHO),
            "mint_burn": (f == ZERO or t == ZERO),
        })
    return {
        "mode": "flow",
        "nodes": out_nodes, "edges": out_edges,
        "metadata": {
            "seeds": seeds, "from_block": frm, "to_block": to,
            "cycle_nodes": len(cyclic),
            "source": "feeder/flow_trace.py (alchemy_getAssetTransfers)",
        },
    }

# (B) 시드 자동 발굴: 토큰의 "가장 활발한 행위자"를 활동량으로 랭킹.
#   민팅 사건(공짜민팅)·소각 사건(디페그 redemption) 둘 다 커버하려고
#   mint 수신/burn 송신/일반 transfer 등장 횟수를 모두 합산(=degree).
def discover_seeds(token, frm, to, n=4):
    # 토큰의 전체 transfer (from/to 필터 없이, contractAddresses 만)
    ck = f"alltransfers_{token}_{frm}_{to}"
    rows = cache_get(ck)
    if rows is None:
        rows = []; page = None
        base = {"fromBlock": hex(frm), "toBlock": hex(to), "category": ["erc20"],
                "withMetadata": False, "maxCount": hex(1000), "contractAddresses": [token]}
        while True:
            p = dict(base)
            if page: p["pageKey"] = page
            r = rpc("alchemy_getAssetTransfers", [p])
            rows += r.get("transfers", []); page = r.get("pageKey")
            if not page: break
            time.sleep(0.05)
        cache_put(ck, rows)
    deg = defaultdict(int); minted = defaultdict(int); burned = defaultdict(int)
    for r in rows:
        f = (r.get("from") or "").lower(); t = (r.get("to") or "").lower()
        if f == ZERO and t and t != ZERO: minted[t] += 1
        if t == ZERO and f and f != ZERO: burned[f] += 1
        for a in (f, t):
            if a and a != ZERO and a != token.lower(): deg[a] += 1
    ranked = sorted(deg.items(), key=lambda kv: -kv[1])[:n]
    kind = "민팅 활발" if sum(minted.values()) >= sum(burned.values()) else "소각/redemption 활발"
    print(f"# seed 자동발굴: {token[:10]} 활동 top{n} ({len(rows)} transfers, {kind})")
    for a, d in ranked:
        print(f"   {a}  deg×{d}  mint×{minted.get(a,0)} burn×{burned.get(a,0)}")
    return [a for a, _ in ranked]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", help="comma addr/심볼 (수동 시드)")
    ap.add_argument("--seed-from-token", dest="sft", help="이 토큰 민팅 수신자에서 시드 자동발굴")
    ap.add_argument("--nseeds", type=int, default=4, help="자동발굴 시드 개수")
    ap.add_argument("--from", dest="frm", type=int, required=True)
    ap.add_argument("--to", type=int, required=True)
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--maxnodes", type=int, default=120)
    ap.add_argument("--tokens", default="xUSD,deUSD,sdeUSD,USDC,USDT",
                    help="추적 토큰(심볼/주소). 'all' 이면 필터 해제(모든 ERC20).")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if not a.seeds and not a.sft:
        ap.error("--seeds 또는 --seed-from-token 중 하나는 필요")
    contracts = None if a.tokens.strip().lower() == "all" else \
        [TOKENS.get(s, s).lower() for s in a.tokens.split(",")]
    seeds = []
    if a.sft:
        seeds += discover_seeds(TOKENS.get(a.sft, a.sft).lower(), a.frm, a.to, a.nseeds)
    if a.seeds:
        seeds += [TOKENS.get(s, s).lower() for s in a.seeds.split(",")]
    seeds = list(dict.fromkeys(seeds))  # dedup, 순서 유지
    print(f"# flow trace seeds={[s[:10] for s in seeds]} blocks {a.frm}->{a.to} "
          f"depth<={a.depth} tokens={a.tokens}")
    nodes, edges, explored = trace(seeds, a.frm, a.to, a.depth, a.maxnodes, contracts)
    j = build_json(seeds, a.frm, a.to, nodes, edges, explored)
    json.dump(j, open(a.out, "w"), indent=2)
    print(f"nodes={len(j['nodes'])} edges={len(j['edges'])} "
          f"cycle_nodes={j['metadata']['cycle_nodes']} "
          f"morpho_edges={sum(1 for e in j['edges'] if e.get('morpho'))} -> {a.out}")

if __name__ == "__main__":
    main()
