#!/usr/bin/env python3
"""크롤 산출물 전체를 스캔해 '아직 어댑터 없는 프로토콜' 후보를 빈도순으로 집계.
크롤이 엣지에 저장한 etherscan ContractName(label)으로 클러스터링 → 새 어댑터 우선순위.
usage: python3 feeder/gaps.py [graphs_dir]"""
import json, glob, os, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GDIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "graphs")

# 이미 어댑터/제네릭으로 해결되는 kind = 갭 아님
RESOLVED_KINDS = {"token", "EOA", "safe", "aToken", "erc4626_vault", "erc20_receipt"}
def is_gap(e):
    k = str(e.get("kind", ""))
    if k.startswith("ledger:"):
        return e.get("resolved") is False  # 어댑터 매칭됐지만 미해결(스텁)
    return k in ("contract", "proxy", "opaque")  # 정체불명 컨트랙트 = 새 프로토콜 후보

def gap_label(e):
    px = e.get("proxy") or {}
    impl = px.get("implementation_label")
    if impl:
        return f"{impl} (proxy:{px.get('proxy_label') or px.get('proxy_kind')})"
    return e.get("label") or e.get("kind") or "?"

def main():
    files = [f for f in glob.glob(os.path.join(GDIR, "crawl.*.json"))]
    by_label = collections.defaultdict(lambda: {"count": 0, "addrs": set(), "tokens": set(), "depths": set()})
    total_gap_edges = 0
    for f in files:
        try: d = json.load(open(f))
        except Exception: continue
        root = d.get("root", os.path.basename(f))
        for e in d.get("edges", []):
            if not is_gap(e): continue
            total_gap_edges += 1
            lab = gap_label(e)
            g = by_label[lab]
            g["count"] += 1; g["addrs"].add(e["holder"]); g["tokens"].add(root[:10]); g["depths"].add(e.get("depth"))
    rows = sorted(by_label.items(), key=lambda kv: (-len(kv[1]["tokens"]), -kv[1]["count"]))
    print(f"# gap candidates across {len(files)} crawls  ({total_gap_edges} gap edges)")
    print(f"{'label':42} {'occ':>4} {'uniq':>5} {'tokens':>7}")
    for lab, g in rows[:40]:
        print(f"{lab[:42]:42} {g['count']:>4} {len(g['addrs']):>5} {len(g['tokens']):>7}  e.g. {sorted(g['addrs'])[0][:12]}")

if __name__ == "__main__":
    main()
