import json, math, os
from http.server import BaseHTTPRequestHandler, HTTPServer
ROOT=os.path.dirname(os.path.abspath(__file__))
FRONT=os.path.join(ROOT,"graphs","frontend")
MANIFEST=os.path.join(FRONT,"manifest.json")

def manifest():
    if os.path.exists(MANIFEST):
        return json.load(open(MANIFEST))
    return {"tokens":[]}

# flow.<name>.json -> 사람이 읽는 라벨 + 정렬 순서 (사건 먼저, 정상 대조군 마지막)
FLOW_LABELS={
    "stream":"Stream xUSD",
    "usd0pp":"USD0++",
    "reusd":"Resupply reUSD",
    "mim":"MIM",
    "rseth_live":"rsETH (정상)",
}
FLOW_ORDER=["stream","usd0pp","reusd","mim","rseth_live"]

def flows():
    out=[]
    for f in os.listdir(FRONT):
        if not (f.startswith("flow.") and f.endswith(".json")): continue
        name=f[len("flow."):-len(".json")]
        try: d=json.load(open(os.path.join(FRONT,f)))
        except Exception: continue
        m=d.get("metadata",{}) or {}
        out.append({
            "name":name,
            "label":FLOW_LABELS.get(name,name),
            "nodes":len(d.get("nodes",[])),
            "edges":len(d.get("edges",[])),
            "cycle_nodes":m.get("cycle_nodes",0) or 0,
            "from_block":m.get("from_block"),
            "to_block":m.get("to_block"),
        })
    order={n:i for i,n in enumerate(FLOW_ORDER)}
    out.sort(key=lambda x:(order.get(x["name"],99),x["name"]))
    return out

def sim_path(token):
    # token 심볼 -> sim 파일. 없으면 매니페스트 첫번째, 그것도 없으면 legacy crawl.sim.json
    if token:
        p=os.path.join(FRONT,f"{token}.sim.json")
        if os.path.exists(p): return p
    toks=manifest().get("tokens",[])
    if toks:
        return os.path.join(FRONT,toks[0]["file"])
    return os.path.join(FRONT,"crawl.sim.json")

def build(token=None):
    d=json.load(open(sim_path(token)))
    nodes=d["nodes"]; edges=d["edges"]
    # depth 별 동심원 레이아웃 (트리/DAG): root 중앙, depth 깊을수록 바깥 링.
    by_depth={}
    for n in nodes:
        dep=(n.get("data") or {}).get("depth")
        dep=-1 if (dep is None or n["type"]=="token") else dep
        by_depth.setdefault(dep,[]).append(n)
    pos={}
    for dep,group in by_depth.items():
        r=0 if dep<0 else 300+dep*340
        for i,n in enumerate(group):
            a=2*math.pi*i/max(1,len(group))
            pos[n["id"]]={"x":round(r*math.cos(a)),"y":round(r*math.sin(a))}
    nodes=[{**n,"position":pos.get(n["id"],{"x":0,"y":0})} for n in nodes]
    return {"nodes":nodes,"edges":edges}

class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Headers","*")
    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u=urlparse(self.path)
        if u.path=="/api/manifest":
            body=json.dumps(manifest()).encode()
            self.send_response(200); self.send_header("Content-Type","application/json"); self._cors()
            self.end_headers(); self.wfile.write(body)
        elif u.path=="/api/flows":
            # 사용 가능한 flow 데이터셋 목록 (프론트 선택 UI용)
            body=json.dumps(flows()).encode()
            self.send_response(200); self.send_header("Content-Type","application/json"); self._cors()
            self.end_headers(); self.wfile.write(body)
        elif u.path=="/api/graph":
            token=(parse_qs(u.query).get("token") or [None])[0]
            body=json.dumps(build(token)).encode()
            self.send_response(200); self.send_header("Content-Type","application/json"); self._cors()
            self.end_headers(); self.wfile.write(body)
        elif u.path=="/api/flow":
            # flow.<name>.json (flow_trace.py 산출물). name 미지정 시 첫 flow.* 파일.
            name=(parse_qs(u.query).get("name") or [None])[0]
            p=os.path.join(FRONT,f"flow.{name}.json") if name else None
            if not p or not os.path.exists(p):
                cand=sorted(f for f in os.listdir(FRONT) if f.startswith("flow.") and f.endswith(".json"))
                p=os.path.join(FRONT,cand[0]) if cand else None
            body=json.dumps(json.load(open(p)) if p and os.path.exists(p) else {"nodes":[],"edges":[]}).encode()
            self.send_response(200); self.send_header("Content-Type","application/json"); self._cors()
            self.end_headers(); self.wfile.write(body)
        elif u.path=="/api/contagions":
            # 볼트별 contagion 인덱스 (위험순) — 선택 UI용
            p=os.path.join(FRONT,"contagion.index.json")
            body=json.dumps(json.load(open(p)) if os.path.exists(p) else {"vaults":[]}).encode()
            self.send_response(200); self.send_header("Content-Type","application/json"); self._cors()
            self.end_headers(); self.wfile.write(body)
        elif u.path=="/api/contagion":
            # 단일 볼트 contagion 그래프. vault 미지정 시 인덱스 첫(최고위험) 볼트.
            vault=(parse_qs(u.query).get("vault") or [None])[0]
            if not vault:
                idx=os.path.join(FRONT,"contagion.index.json")
                vs=json.load(open(idx)).get("vaults",[]) if os.path.exists(idx) else []
                vault=vs[0]["address"] if vs else None
            p=os.path.join(FRONT,f"contagion.{vault.lower()}.json") if vault else None
            body=json.dumps(json.load(open(p)) if p and os.path.exists(p) else {"nodes":[],"edges":[]}).encode()
            self.send_response(200); self.send_header("Content-Type","application/json"); self._cors()
            self.end_headers(); self.wfile.write(body)
        elif u.path=="/api/reflexivity":
            # reflexivity_scan.py 산출물 (토큰별 reflexivity 등급)
            p=os.path.join(FRONT,"reflexivity.json")
            body=json.dumps(json.load(open(p)) if os.path.exists(p) else {"tokens":{}}).encode()
            self.send_response(200); self.send_header("Content-Type","application/json"); self._cors()
            self.end_headers(); self.wfile.write(body)
        elif self.path.startswith("/api/health"):
            self.send_response(200); self.send_header("Content-Type","application/json"); self._cors(); self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404); self._cors(); self.end_headers(); self.wfile.write(b'{"error":"mock: only /api/graph"}')
    def log_message(self,*a): pass
if __name__=="__main__":
    print("mock backend on http://localhost:8000  (/api/graph -> wstETH.sim.json)")
    HTTPServer(("127.0.0.1",8000),H).serve_forever()
