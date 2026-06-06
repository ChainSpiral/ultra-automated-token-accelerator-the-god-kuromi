#!/usr/bin/env python3
"""DeBank Pro API vs 우리 온체인 검증·시간비교. usage: python3 feeder/debank_cmp.py [addr]"""
import json, urllib.request, time, sys
E = {}
for ln in open("/Users/link/podotree/.env"):
    ln = ln.strip()
    if "=" in ln and not ln.startswith("#"):
        k, v = ln.split("=", 1); E[k.strip()] = v.strip()
RPC = E["ETH_RPC"]; KEY = E["DEBANK_API_KEY"]
ADDR = (sys.argv[1] if len(sys.argv) > 1 else "0xcd2eb13d6831d4602d80e5db9230a57596cdca63").lower()

def debank(path):
    req = urllib.request.Request("https://pro-openapi.debank.com" + path,
                                 headers={"AccessKey": KEY, "accept": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())
def rpc(m, p):
    r = urllib.request.Request(RPC, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": m, "params": p}).encode(),
                               headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=30).read()).get("result")
def call(to, d):
    try: return rpc("eth_call", [{"to": to, "data": d}, "latest"])
    except Exception: return None
def bal(tok, addr):
    h = call(tok, "0x70a08231" + addr[2:].rjust(64, "0")); return int(h, 16) if h and h != "0x" else 0
def dec(tok):
    h = call(tok, "0x313ce567"); return int(h, 16) if h and h != "0x" else 18

print("addr:", ADDR)
print("=== DeBank Pro API (pre-indexed) ===")
t0 = time.time(); tb = debank("/v1/user/total_balance?id=" + ADDR); t1 = time.time() - t0
total = tb.get("total_usd_value", 0)
print("  total_balance: $%s | %.2fs" % (format(round(total), ","), t1))
t0 = time.time(); toks = debank("/v1/user/all_token_list?id=%s&chain_id=eth&is_all=false" % ADDR); t2 = time.time() - t0
toks = [t for t in toks if (t.get("amount") or 0) * (t.get("price") or 0) > 1000]
toks.sort(key=lambda t: -((t.get("amount") or 0) * (t.get("price") or 0)))
print("  all_token_list(eth): %d tokens >$1k | %.2fs" % (len(toks), t2))
print("  DeBank 합계 %.2fs" % (t1 + t2))

print("\n=== 검증: DeBank 잔고 vs 우리 온체인 balanceOf(latest) ===")
t0 = time.time(); ok = 0; n = 0
for t in toks[:6]:
    a = t.get("id", "")
    if not (isinstance(a, str) and a.startswith("0x") and len(a) == 42):
        continue
    n += 1
    onchain = bal(a, ADDR) / 10 ** dec(a)
    db = t.get("amount", 0)
    match = abs(onchain - db) / max(db, 1e-9) < 0.005
    ok += 1 if match else 0
    mark = "OK" if match else "MISMATCH"
    print("  %-10s DeBank %s vs 온체인 %s  %s" % (t.get("symbol", "?"),
          format(round(db, 4), ","), format(round(onchain, 4), ","), mark))
t_verify = time.time() - t0
print("\n검증 결과: %d/%d 일치 | 우리 온체인확인 %.2fs" % (ok, n, t_verify))
print("\n=== 시간 요약 ===")
print("  DeBank (현재 포트폴리오 전체, pre-indexed): %.2fs" % (t1 + t2))
print("  우리 (6개월 transfer 라이브 스캔): ~35s  /  같은 잔고 %d개 온체인확인: %.2fs" % (n, t_verify))
