#!/usr/bin/env python3
"""One-command pipeline: crawl -> convert -> frontend sim + manifest.
usage:
  python3 run.py <symbol|addr> [block] [--depth N] [--k K]   # 단일 토큰
  python3 run.py --all [block] [--depth N] [--k K]            # tokens.json 전체
  # block 생략 시 feeder/snapshot.py 의 고정 snapshot 사용
서버(mock_server :8000, next :3000)는 떠 있으면 브라우저 새로고침/셀렉터로 반영됨."""
import sys, os, json, subprocess, urllib.request
from feeder.snapshot import DEFAULT_SNAPSHOT_BLOCK

ROOT = os.path.dirname(os.path.abspath(__file__))
TOKENS = json.load(open(os.path.join(ROOT, "feeder", "tokens.json")))
ADDR2SYM = {v.lower(): k for k, v in TOKENS.items()}
FRONT = os.path.join(ROOT, "graphs", "frontend"); os.makedirs(FRONT, exist_ok=True)
MANIFEST = os.path.join(FRONT, "manifest.json")
ENV = "/Users/link/podotree/.env"

def rpc_env():
    for ln in open(ENV):
        if ln.strip().startswith("ETH_RPC"):
            return ln.split("=", 1)[1].strip()
    raise RuntimeError("ETH_RPC not found")

def head_block():
    r = urllib.request.Request(rpc_env(), data=json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}).encode(),
        headers={"content-type": "application/json"})
    return int(json.loads(urllib.request.urlopen(r, timeout=20).read())["result"], 16)

def opt(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default

def block_arg(index):
    return int(sys.argv[index]) if len(sys.argv) > index and sys.argv[index].isdigit() else DEFAULT_SNAPSHOT_BLOCK

def run_one(sym, addr, block, depth, k):
    print(f"\n=== {sym} ({addr}) @ {block} ===")
    crawl_json = os.path.join(ROOT, "graphs", f"crawl.{addr}.{block}.json")
    subprocess.run([sys.executable, os.path.join(ROOT, "feeder", "crawl.py"),
                    addr, str(block), "--depth", str(depth), "--k", str(k)], check=True)
    # 검증 게이트: 불변식(보존/coverage/self-loop) 실패 시 변환·매니페스트 갱신 중단
    subprocess.run([sys.executable, os.path.join(ROOT, "feeder", "validate.py"),
                    crawl_json], check=True)
    sim = os.path.join(FRONT, f"{sym}.sim.json")
    subprocess.run([sys.executable, os.path.join(ROOT, "adapters", "crawl_to_frontend.py"),
                    crawl_json, sim], check=True)
    d = json.load(open(sim))
    covs = [e.get("coverage") for e in d.get("edges", []) if isinstance(e.get("coverage"), (int, float))]
    avg_coverage = (sum(covs) / len(covs)) if covs else None
    return {"symbol": sym, "file": f"{sym}.sim.json", "block": block,
            "nodes": len(d["nodes"]), "edges": len(d["edges"]),
            "avg_coverage": avg_coverage, "coverage_edges": len(covs)}

def update_manifest(entry):
    m = {}
    if os.path.exists(MANIFEST):
        try: m = {e["symbol"]: e for e in json.load(open(MANIFEST)).get("tokens", [])}
        except Exception: m = {}
    m[entry["symbol"]] = entry
    order = list(TOKENS.keys())
    toks = sorted(m.values(), key=lambda e: order.index(e["symbol"]) if e["symbol"] in order else 999)
    json.dump({"tokens": toks}, open(MANIFEST, "w"), indent=2)

if __name__ == "__main__":
    depth = int(opt("--depth", 4)); k = int(opt("--k", 10))
    if sys.argv[1] == "--all":
        block = block_arg(2)
        for sym, addr in TOKENS.items():
            try:
                update_manifest(run_one(sym, addr.lower(), block, depth, k))
            except Exception as e:
                print(f"  !! {sym} failed: {e}")
    else:
        arg = sys.argv[1]
        if arg.lower() in (s.lower() for s in TOKENS):
            sym = next(s for s in TOKENS if s.lower() == arg.lower()); addr = TOKENS[sym].lower()
        else:
            addr = arg.lower(); sym = ADDR2SYM.get(addr, addr[:10])
        block = block_arg(2)
        update_manifest(run_one(sym, addr, block, depth, k))
    print(f"\nmanifest -> {MANIFEST}")
