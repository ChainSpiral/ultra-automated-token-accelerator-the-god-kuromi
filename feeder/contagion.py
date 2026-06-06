#!/usr/bin/env python3
"""
Vault-rooted contagion / shared-dependency map.

큐레이터 사각지대: "내 볼트가 N개 마켓에 분산된 것처럼 보여도, 실제론 같은 담보/오라클/발행자로
수렴해서 한 번 디페그에 같이 청산되는가?" — Reflexivity(자산 1개)도 Flow(사후)도 못 보여주는,
본질적으로 many-to-many 라 그래프여야만 하는 신호.

3개 수렴 축:
  1) 공유담보  — 서로 다른 마켓이 같은 담보를 씀
  2) 공유오라클 — 서로 다른 담보가 같은 오라클 주소에 의존
  3) 발행자 수렴(★) — 서로 달라 보이는 담보들이 같은 발행자 패밀리로 귀결
     (예: sUSDe/USDe/PT-USDe/PT-sUSDE = 전부 Ethena → "7담보"가 실제론 1개 베팅)

데이터: Morpho blue-api GraphQL (볼트→마켓→담보/오라클/lltv/supplyUSD).
등급 오버레이: graphs/frontend/reflexivity.json (담보 심볼).
발행자 패밀리: 심볼 휴리스틱(confidence=heuristic, MEDIUM) — 온체인 asset() 검증은 후속 업그레이드.

usage:
  python3 feeder/contagion.py                # 상위 listed 볼트 N개 + index
  python3 feeder/contagion.py 0xVAULTADDR    # 특정 볼트 1개
  python3 feeder/contagion.py --top 20
"""
import json, os, sys, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONT = os.path.join(ROOT, "graphs", "frontend")
REFLEX = os.path.join(FRONT, "reflexivity.json")
API = "https://blue-api.morpho.org/graphql"

SEV = {"CRITICAL": 5, "DISTRESSED": 4, "HIGH": 3, "MED": 2, "CHECK": 1, "ok": 0}

# 발행자 패밀리: (심볼 소문자 substring, 발행자명). 위에서부터 먼저 매칭 = 구체적인 것 먼저.
# heuristic(MEDIUM) — 발행자 귀속은 온체인으로 직접 검증 불가. 그룹핑 보조용.
FAMILY_RULES = [
    ("usdtb", "Ethena"), ("usde", "Ethena"),        # USDe, sUSDe, eUSDe, USDtb, PT-...USDe
    ("usds", "Sky"), ("sdai", "Sky"), ("dai", "Sky"),
    ("wsteth", "Lido"), ("steth", "Lido"),
    ("weeth", "EtherFi"), ("eeth", "EtherFi"),
    ("rseth", "KelpDAO"),
    ("ezeth", "Renzo"),
    ("sfrxeth", "Frax"), ("frxeth", "Frax"), ("frxusd", "Frax"), ("frax", "Frax"),
    ("crvusd", "Curve"),
    ("rlusd", "Ripple"),
    ("mseth", "Metronome"), ("msusd", "Metronome"),
    ("eurc", "Circle"), ("usdc", "Circle"),
    ("cbbtc", "Coinbase"), ("cbeth", "Coinbase"),
    ("wbtc", "BitGo"),
    ("tbtc", "Threshold"),
    ("reth", "RocketPool"),
    ("ethx", "Stader"),
    ("pyusd", "PayPal"),
    ("usdt", "Tether"),
]


def resolve_family(symbol):
    """담보 심볼 → (발행자, 정규화코어). PT-<x>-<date> 는 코어 x 로 환원."""
    s = (symbol or "").strip()
    core = s
    if s.upper().startswith("PT-"):
        core = s[3:].rsplit("-", 1)[0]   # "PT-sUSDE-31JUL2025" -> "sUSDE"
    low = core.lower()
    for sub, issuer in FAMILY_RULES:
        if sub in low:
            return issuer, core
    return None, core


def gql(query, variables=None):
    body = {"query": query}
    if variables:
        body["variables"] = variables
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=45).read())
    except urllib.error.HTTPError as e:
        raise SystemExit("GraphQL %s: %s" % (e.code, e.read().decode()[:300]))
    if "errors" in r:
        raise SystemExit("GraphQL errors: " + json.dumps(r["errors"])[:300])
    return r["data"]


def load_reflex():
    if not os.path.exists(REFLEX):
        return {}
    d = json.load(open(REFLEX))
    return d.get("tokens", d)


VAULT_Q = """
query($first:Int!){ vaults(first:$first, orderBy: TotalAssets, orderDirection: Desc,
  where:{listed:true, chainId_in:[1]}){ items {
    address name asset{symbol address}
    state { totalAssetsUsd
      allocation { supplyAssetsUsd
        market { id lltv oracleAddress
          collateralAsset{ symbol address } loanAsset{ symbol } } } } } } }
"""
ONE_Q = """
query($addr:String!){ vaultByAddress(address:$addr, chainId:1){
  address name asset{symbol address}
  state { totalAssetsUsd
    allocation { supplyAssetsUsd
      market { id lltv oracleAddress
        collateralAsset{ symbol address } loanAsset{ symbol } } } } } }
"""


def fetch_vaults(top):
    return gql(VAULT_Q, {"first": top})["vaults"]["items"]


def fetch_one(addr):
    v = gql(ONE_Q, {"addr": addr}).get("vaultByAddress")
    return [v] if v else []


def build_graph(v, reflex):
    st = v.get("state") or {}
    tav = st.get("totalAssetsUsd") or 0
    allocs = [a for a in (st.get("allocation") or [])
              if (a.get("market") or {}).get("collateralAsset")]
    if not allocs:
        return None

    # 담보별 집계
    collat = {}
    for a in allocs:
        m = a["market"]
        c = m["collateralAsset"]
        sym = c["symbol"]
        usd = a.get("supplyAssetsUsd") or 0
        o = m.get("oracleAddress") or "?"
        d = collat.setdefault(sym, {"usd": 0.0, "markets": [], "address": c.get("address"), "oracles": set()})
        d["usd"] += usd
        d["oracles"].add(o)
        d["markets"].append({
            "id": m["id"], "loan": (m.get("loanAsset") or {}).get("symbol"),
            "lltv": round(int(m["lltv"]) / 1e18, 4) if m.get("lltv") else None,
            "oracle": o, "usd": round(usd, 2),
        })

    # 공유오라클 (서로 다른 담보 가로지름)
    oracle_collats = {}
    for sym, d in collat.items():
        for o in d["oracles"]:
            oracle_collats.setdefault(o, set()).add(sym)
    shared_oracles = {o: cs for o, cs in oracle_collats.items() if len(cs) > 1 and o != "?"}

    # 발행자 패밀리 집계 (★)
    issuer_agg = {}   # issuer -> {usd, collats:set}
    for sym, d in collat.items():
        issuer, _core = resolve_family(sym)
        if issuer:
            ia = issuer_agg.setdefault(issuer, {"usd": 0.0, "collats": set()})
            ia["usd"] += d["usd"]
            ia["collats"].add(sym)

    nodes = [{
        "id": "vault", "type": "vault", "label": v["name"],
        "address": v["address"], "asset": (v.get("asset") or {}).get("symbol"),
        "tvl_usd": round(tav, 2),
    }]
    edges = []

    def reflex_for(sym):
        r = reflex.get(sym)
        if not r:
            return {"grade": None}
        return {"grade": r.get("grade"), "oracle_class": r.get("oracle_class"),
                "sees": r.get("sees"), "self_referential": bool(r.get("cycle"))}

    for sym, d in sorted(collat.items(), key=lambda x: -x[1]["usd"]):
        n_mkt = len(d["markets"])
        pct = (d["usd"] / tav) if tav else 0
        rf = reflex_for(sym)
        issuer, _ = resolve_family(sym)
        nodes.append({
            "id": "collat:" + sym, "type": "collateral", "label": sym,
            "symbol": sym, "address": d.get("address"),
            "usd": round(d["usd"], 2), "pct_of_vault": round(pct, 4),
            "n_markets": n_mkt, "shared": n_mkt > 1,
            "grade": rf["grade"], "sev": SEV.get(rf["grade"], 0),
            "oracle_class": rf.get("oracle_class"), "sees": rf.get("sees"),
            "self_referential": rf.get("self_referential", False),
            "issuer": issuer, "markets": d["markets"],
        })
        edges.append({
            "id": "e:vault:" + sym, "source": "vault", "target": "collat:" + sym,
            "usd": round(d["usd"], 2), "pct": round(pct, 4),
            "n_markets": n_mkt, "shared": n_mkt > 1,
            "label": "%d마켓 · %.0f%%" % (n_mkt, pct * 100),
        })

    # 발행자 노드 (2개 이상 담보가 귀결 = 수렴 = 그래프여야만 하는 신호)
    for issuer, ia in sorted(issuer_agg.items(), key=lambda x: -x[1]["usd"]):
        pct = (ia["usd"] / tav) if tav else 0
        iid = "issuer:" + issuer
        nodes.append({
            "id": iid, "type": "issuer", "label": issuer,
            "usd": round(ia["usd"], 2), "pct_of_vault": round(pct, 4),
            "n_collaterals": len(ia["collats"]), "converge": len(ia["collats"]) > 1,
            "confidence": "heuristic",
        })
        for sym in ia["collats"]:
            edges.append({
                "id": "e:" + sym + ":" + iid, "source": "collat:" + sym, "target": iid,
                "kind": "issuer",
            })

    # 공유오라클 노드
    for o, cs in shared_oracles.items():
        oid = "oracle:" + o
        nodes.append({"id": oid, "type": "oracle", "label": o[:10] + "…",
                      "address": o, "n_collaterals": len(cs), "shared": True})
        for sym in cs:
            edges.append({"id": "e:" + sym + ":" + o, "source": "collat:" + sym,
                          "target": oid, "kind": "oracle", "label": "공유오라클"})

    # 점수
    shared_collats = [(n["symbol"], n["pct_of_vault"]) for n in nodes
                      if n["type"] == "collateral" and n["shared"]]
    top_shared = max(shared_collats, key=lambda x: x[1]) if shared_collats else None
    issuer_list = [(n["label"], n["pct_of_vault"]) for n in nodes if n["type"] == "issuer"]
    top_issuer = max(issuer_list, key=lambda x: x[1]) if issuer_list else None
    worst_grade = max((n for n in nodes if n["type"] == "collateral"),
                      key=lambda n: n["sev"], default=None)
    score = {
        "n_markets": len(allocs), "n_collaterals": len(collat),
        "n_shared_collat": len(shared_collats), "n_shared_oracle": len(shared_oracles),
        "n_issuers": len(issuer_agg),
        "top_shared_collat": top_shared[0] if top_shared else None,
        "top_shared_pct": round(top_shared[1], 4) if top_shared else 0,
        "top_issuer": top_issuer[0] if top_issuer else None,
        "top_issuer_pct": round(top_issuer[1], 4) if top_issuer else 0,
        "worst_collat_grade": worst_grade["grade"] if worst_grade else None,
    }
    return {
        "vault": {"address": v["address"], "name": v["name"],
                  "asset": (v.get("asset") or {}).get("symbol"), "tvl_usd": round(tav, 2)},
        "score": score, "nodes": nodes, "edges": edges,
    }


def main():
    args = sys.argv[1:]
    top = 12
    addr = None
    if "--top" in args:
        i = args.index("--top")
        top = int(args[i + 1]); args = args[:i] + args[i + 2:]
    if args and args[0].startswith("0x"):
        addr = args[0].lower()

    reflex = load_reflex()
    vaults = fetch_one(addr) if addr else fetch_vaults(top)
    os.makedirs(FRONT, exist_ok=True)

    index = []
    for v in vaults:
        g = build_graph(v, reflex)
        if not g:
            continue
        a = g["vault"]["address"].lower()
        fn = "contagion.%s.json" % a
        json.dump(g, open(os.path.join(FRONT, fn), "w"), ensure_ascii=False)
        s = g["score"]
        index.append({
            "address": a, "name": g["vault"]["name"], "asset": g["vault"]["asset"],
            "tvl_usd": g["vault"]["tvl_usd"], "file": fn,
            "n_markets": s["n_markets"], "n_collaterals": s["n_collaterals"],
            "top_shared_collat": s["top_shared_collat"], "top_shared_pct": s["top_shared_pct"],
            "top_issuer": s["top_issuer"], "top_issuer_pct": s["top_issuer_pct"],
            "n_issuers": s["n_issuers"], "n_shared_oracle": s["n_shared_oracle"],
            "worst_collat_grade": s["worst_collat_grade"],
        })
        flag = ""
        if s["top_issuer_pct"] >= 0.5:
            flag = "  ⚠️ 발행자 %s %.0f%%" % (s["top_issuer"], s["top_issuer_pct"] * 100)
        print("  %-30s %-6s $%8.1fM  %2dmkt/%2dcol/%2discuer%s" % (
            g["vault"]["name"][:30], g["vault"]["asset"] or "?",
            g["vault"]["tvl_usd"] / 1e6, s["n_markets"], s["n_collaterals"],
            s["n_issuers"], flag))

    # 발행자 집중 위험순 (없으면 공유담보순)
    index.sort(key=lambda x: -(x["top_issuer_pct"] or x["top_shared_pct"]))
    json.dump({"vaults": index}, open(os.path.join(FRONT, "contagion.index.json"), "w"), ensure_ascii=False)
    print("\n%d vaults → graphs/frontend/contagion.*.json + contagion.index.json" % len(index))


if __name__ == "__main__":
    main()
