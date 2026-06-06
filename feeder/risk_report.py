#!/usr/bin/env python3
"""
통합 cross-venue 리스크 리포트 — Morpho(reflexivity.json) + Euler(euler.json) 를 토큰 단위로 합쳐
한 장의 ranked 위험 리스트로. (큐레이터/퀀트용 portfolio 리포트)

각 venue 스캔을 먼저 돌려 JSON 생성 후 실행:
  python3 feeder/reflexivity_scan.py [--auto N]   # -> reflexivity.json (Morpho)
  python3 feeder/euler_scan.py --top 30           # -> euler.json (Euler)
  python3 feeder/risk_report.py                    # -> unified_risk.json + 출력
"""
import json, os

ROOT = os.path.dirname(os.path.abspath(__file__))
FRONT = os.path.join(ROOT, "..", "graphs", "frontend")
RANK = {"CRITICAL": 0, "DISTRESSED": 1, "HIGH": 2, "MED": 3, "CHECK": 4, "ok": 5, None: 9}

def load(name):
    p = os.path.join(FRONT, name)
    return json.load(open(p)) if os.path.exists(p) else {}

def main():
    morpho = load("reflexivity.json").get("tokens", {})
    euler = load("euler.json").get("tokens", {})
    syms = set(morpho) | set(euler)
    merged = {}
    for s in syms:
        m = morpho.get(s); e = euler.get(s)
        venues = {}
        if m: venues["morpho"] = {"grade": m["grade"], "oracle_class": m.get("oracle_class"),
                                  "sees": m.get("sees"), "distressed": m.get("distressed"),
                                  "concentration": m.get("concentration"), "collat_usd": m.get("collat_usd")}
        if e: venues["euler"] = {"grade": e["grade"], "oracle_class": e.get("oracle_class"),
                                 "sees": e.get("sees")}
        worst = min((v["grade"] for v in venues.values()), key=lambda g: RANK.get(g, 9))
        merged[s] = {"token": s, "worst_grade": worst, "venues": venues,
                     "n_venues": len(venues)}
    ranked = sorted(merged.values(), key=lambda r: (RANK.get(r["worst_grade"], 9), r["token"]))
    # 출력
    print(f"# 통합 CROSS-VENUE 리스크 리포트  (Morpho {len(morpho)} + Euler {len(euler)} → {len(syms)} tokens)\n")
    from collections import Counter
    print("worst-grade 분포:", dict(Counter(r["worst_grade"] for r in ranked)), "\n")
    print(f"{'GRADE':11}{'TOKEN':14}{'VENUES':28} 사유")
    print("-" * 110)
    for r in ranked:
        if RANK.get(r["worst_grade"], 9) >= 5: continue   # ok 는 생략(위험만)
        vstr = ", ".join(f"{vn}:{vd['grade']}({vd.get('oracle_class','?')})" for vn, vd in r["venues"].items())
        why = next((vd.get("sees") for vd in r["venues"].values() if vd.get("sees")), "") or ""
        print(f"{r['worst_grade']:11}{r['token']:14}{vstr[:27]:28} {why[:48]}")
    out = {"morpho_tokens": len(morpho), "euler_tokens": len(euler), "tokens": merged,
           "ranked": [r["token"] for r in ranked]}
    p = os.path.join(FRONT, "unified_risk.json")
    json.dump(out, open(p, "w"), indent=2)
    print(f"\nsaved -> {os.path.abspath(p)}")

if __name__ == "__main__":
    main()
