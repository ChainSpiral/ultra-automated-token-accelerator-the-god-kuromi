#!/usr/bin/env python3
"""크롤 산출물 불변식 게이트 + 트리 요약.
검사하는 것(가치순):
  1) 보존/이중계산 — 같은 from_token(=같은 단위) 아래 Σfrac ≤ 1.0. 넘으면 이중계산 = FAIL.
     (price-free 라 depth 가 깊어지면 단위가 바뀌므로 '전역 Σ' 가 아니라 '레벨별 Σfrac' 로 검증.)
  2) 커버리지/cutoff — from_token 별 coverage(=Σfrac) 와 잔여('기타 N%')를 명시(silent 누락 금지).
  3) ledger coverage — 어댑터 children_sum/amount ≤ 1.0 (어댑터 이중계산 가드).
  4) provenance — resolved=False(opaque) 엣지 개수 명시.
  5) self-loop = 0 (from_token == holder 금지; crawl 이 막지만 backstop).
실패하면 비0 종료 → run.py 게이트가 그 토큰 변환을 중단한다.
usage: python3 feeder/validate.py graphs/crawl.steth.25235536.json"""
import json, sys, collections

EPS_FAIL = 0.02    # Σfrac 가 이 이상 1 초과면 이중계산으로 간주(FAIL)
EPS_WARN = 0.005   # 미세 초과는 경고만

d = json.load(open(sys.argv[1]))
edges = d["edges"]
print(f"root={d['root'][:12]} block={d['block']} edges={len(edges)}")
fails = []

# 1)+2) 레벨별 보존 + 커버리지: 같은 from_token 아래 frac 합
frac_sum = collections.defaultdict(float)
labels = {}
for e in edges:
    if e.get("frac") is not None:
        frac_sum[e["from_token"].lower()] += e["frac"]
        labels.setdefault(e["from_token"].lower(), e["from_token"][:12])
print("\n[conservation] Σfrac per from_token (coverage / residual):")
for ft, s in sorted(frac_sum.items(), key=lambda x: -x[1]):
    resid = 1.0 - s
    if s > 1.0 + EPS_FAIL:
        tag = "FAIL (double-count)"; fails.append(f"Σfrac>{1+EPS_FAIL} at {labels[ft]} ({s:.3f})")
    elif s > 1.0 + EPS_WARN:
        tag = "warn (~over 1.0)"
    else:
        tag = f"기타 {resid*100:4.1f}%" if resid > 0.001 else "full"
    print(f"  {labels[ft]}  Σfrac={s:6.3f}  {tag}")

# 3) ledger 어댑터 coverage
ledcov = [(e, e["coverage"]) for e in edges if e.get("coverage") is not None]
if ledcov:
    print("\n[ledger coverage]")
    for e, c in ledcov:
        bad = c is not None and c > 1.0 + EPS_FAIL
        if bad: fails.append(f"ledger coverage>1 at {e['holder'][:10]} ({c:.3f})")
        print(f"  {e['holder'][:10]} via:{e.get('via','?'):14} coverage={c:.3f} {'FAIL' if bad else 'OK'}")

# 4) provenance: unresolved / opaque
unresolved = [e for e in edges if e.get("resolved") is False]
opaque = [e for e in edges if e.get("kind") == "opaque"]
print(f"\n[provenance] unresolved(adapter TODO)={len(unresolved)}  opaque-leaf={len(opaque)}")

# 5) self-loop backstop
selfloops = [e for e in edges if e["from_token"].lower() == e["holder"].lower()]
if selfloops: fails.append(f"self-loop x{len(selfloops)}")
print(f"[self-loop] {len(selfloops)}  {'OK' if not selfloops else 'FAIL'}")

# depth/kind 분포 (진단)
print(f"[depths] {dict(sorted(collections.Counter(e['depth'] for e in edges).items()))}")
print(f"[kinds ] {dict(collections.Counter(e['kind'] for e in edges))}")

# 트리 출력
kids = collections.defaultdict(list)
for e in edges:
    kids[e["from_token"].lower()].append(e)
seen = set()
def show(tok, depth):
    if depth > 6 or tok in seen: return
    seen.add(tok)
    for e in sorted(kids.get(tok, []), key=lambda x: -x["amount"])[:6]:
        v = f" via:{e['via']}" if e.get("via") else ""
        r = "" if e.get("resolved", True) else " [unresolved]"
        print(f"{'    '*depth}└ {e['holder'][:10]} {e['amount']:>12,.0f} [{e['kind']}] {e['label']}{v}{r}")
        show(e["holder"].lower(), depth + 1)
print("\n=== tree ===")
show(d["root"].lower(), 0)

# 게이트
print()
if fails:
    print("VALIDATE: FAIL — " + "; ".join(fails))
    sys.exit(1)
print("VALIDATE: PASS")
