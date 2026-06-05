"use client";

import { useMemo, useEffect, useState, useCallback } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Position,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

// 흐르는 애니메이션을 줄 엣지 타입(프로토콜 흐름만 — 살짝)
const FLOW = new Set(["morpho", "compound_v3", "restake", "transformed", "lending", "vault", "cdp"]);

type RawNode = { id: string; type: string; label: string; data?: Record<string, unknown> };
type RawEdge = {
  id: string;
  source: string;
  target: string;
  label?: string;
  edge_type?: string;
  coverage?: number;
};

const EDGE_COLOR: Record<string, string> = {
  collateral: "#60a5fa",
  dex: "#34d399",
  yield: "#c084fc",
  oracle: "#fbbf24",
  issued_by: "#f472b6",
  // crawl edge types
  morpho: "#60a5fa",
  lending: "#38bdf8",
  vault: "#c084fc",
  wrapper: "#a3a3a3",
  restake: "#f472b6",
  transformed: "#fb923c",
  cdp: "#facc15",
  eigenlayer: "#f472b6",
  kelp: "#fb923c",
  maker: "#facc15",
  holds: "#475569",
};

// crawl kind(category) -> 노드 배경색
const KIND_BG: Record<string, string> = {
  token: "#4f46e5",
  EOA: "#334155",
  safe: "#3f3f46",
  aToken: "#0369a1",
  erc4626_vault: "#7c3aed",
  erc20_receipt: "#475569",
  "ledger:aave_v3": "#0369a1",
  "ledger:morpho": "#1d4ed8",
  "ledger:eigenlayer": "#be185d",
  "ledger:kelp": "#c2410c",
  "ledger:maker": "#a16207",
  "ledger:compound_v3": "#15803d",
  opaque: "#52525b",
  contract: "#334155",
};

function fmtUsd(v: unknown): string {
  const n = typeof v === "number" ? v : NaN;
  if (!isFinite(n)) return "";
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${Math.round(n).toLocaleString()}`;
}

function nodeLabel(n: RawNode): string {
  if (n.type === "token") return n.label;
  if (n.type === "oracle") return `🔮 ${n.label}`;
  const usd = fmtUsd(n.data?.tokens_held_usd);
  return usd ? `${n.label}   ${usd}` : n.label;
}

const isAddress = (s: string | undefined): s is string =>
  !!s && /^0x[0-9a-fA-F]{40}$/.test(s);

function nodeAddress(n: RawNode): string | null {
  const a = (n.data?.address as string | undefined) ?? n.id;
  return isAddress(a) ? a.toLowerCase() : null;
}

// 카테고리(kind) → 사람이 읽는 이름
const KIND_LABEL: Record<string, string> = {
  token: "토큰",
  EOA: "외부 지갑 (EOA)",
  safe: "Gnosis Safe (멀티시그)",
  contract: "컨트랙트",
  erc4626_vault: "ERC-4626 볼트",
  erc20_receipt: "영수증 토큰",
  aToken: "Aave aToken",
  opaque: "미분류 컨트랙트",
  "ledger:aave_v3": "Aave V3",
  "ledger:morpho": "Morpho",
  "ledger:eigenlayer": "EigenLayer",
  "ledger:kelp": "KelpDAO",
  "ledger:maker": "Sky / Maker",
  "ledger:compound_v3": "Compound V3",
};

interface ExplorerLink {
  label: string;
  href: string;
  hint: string;
}

// 주소 종류에 맞는 외부 탐색기 링크들. 전부 임의 주소 조회를 지원하는 곳만.
function explorerLinks(addr: string, isToken: boolean): ExplorerLink[] {
  const links: ExplorerLink[] = [
    {
      label: "Etherscan",
      href: `https://etherscan.io/${isToken ? "token" : "address"}/${addr}`,
      hint: isToken ? "토큰 컨트랙트·홀더·전송" : "트랜잭션·내부호출·코드",
    },
    {
      label: "DeBank",
      href: `https://debank.com/profile/${addr}`,
      hint: "지갑/컨트랙트 포트폴리오·포지션",
    },
    {
      label: "Arkham",
      href: `https://intel.arkm.com/explorer/address/${addr}`,
      hint: "엔티티 라벨·자금 흐름",
    },
  ];
  // DefiLlama는 주소 조회가 없어 토큰만 가격/유동성 페이지로 연결
  if (isToken) {
    links.push({
      label: "DefiLlama",
      href: `https://defillama.com/token/ethereum:${addr}`,
      hint: "토큰 가격·유동성·풀",
    });
  }
  return links;
}

function NodeInspector({ node, onClose }: { node: RawNode; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const addr = nodeAddress(node);
  const kind = String(node.data?.category ?? node.data?.kind ?? node.type);
  const kindLabel = KIND_LABEL[kind] ?? kind;
  const isToken = node.type === "token" || kind === "token";
  const symbol = (node.data?.symbol as string | undefined) ?? null;
  const usd = fmtUsd(node.data?.tokens_held_usd);
  const depth = node.data?.depth;

  const copy = useCallback(() => {
    if (!addr) return;
    navigator.clipboard?.writeText(addr).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    });
  }, [addr]);

  return (
    <aside
      className="absolute right-3 top-3 bottom-3 z-30 flex w-[330px] flex-col overflow-hidden rounded-xl border border-white/10 bg-[#0f172a]/97 shadow-2xl backdrop-blur"
      style={{ fontSize: 13 }}
    >
      <div className="flex items-start justify-between gap-2 border-b border-white/10 px-4 py-3">
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold text-slate-100">
            {symbol ?? node.label}
          </div>
          <div className="mt-0.5 text-[11px] text-slate-400">
            {kindLabel}
            {typeof depth === "number" ? ` · depth ${depth}` : ""}
            {usd ? ` · ${usd}` : ""}
          </div>
        </div>
        <button
          onClick={onClose}
          className="shrink-0 rounded-md px-2 py-0.5 text-slate-400 hover:bg-white/10 hover:text-slate-100"
        >
          ✕
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {addr ? (
          <section>
            <div className="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-slate-500">
              주소
            </div>
            <button
              onClick={copy}
              title="클릭하여 복사"
              className="flex w-full items-center gap-2 rounded-md bg-white/5 px-2.5 py-2 text-left font-mono text-[11px] text-slate-200 hover:bg-white/10"
            >
              <span className="truncate">{addr}</span>
              <span className="ml-auto shrink-0 text-[10px] text-slate-400">
                {copied ? "복사됨 ✓" : "복사"}
              </span>
            </button>
          </section>
        ) : (
          <p className="rounded-md bg-white/5 px-2.5 py-2 text-[11px] text-slate-400">
            온체인 주소가 없는 노드입니다 (집계/가상 노드).
          </p>
        )}

        {addr && (
          <section>
            <div className="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-slate-500">
              외부 탐색기
            </div>
            <div className="space-y-1.5">
              {explorerLinks(addr, isToken).map((l) => (
                <a
                  key={l.label}
                  href={l.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 rounded-md border border-white/10 bg-white/5 px-2.5 py-2 transition-colors hover:border-white/25 hover:bg-white/10"
                >
                  <span className="font-medium text-slate-100">{l.label}</span>
                  <span className="truncate text-[10px] text-slate-400">{l.hint}</span>
                  <span className="ml-auto shrink-0 text-slate-500">↗</span>
                </a>
              ))}
            </div>
          </section>
        )}
      </div>
    </aside>
  );
}

export function OverviewCanvas({ nodes, edges }: { nodes: RawNode[]; edges: RawEdge[] }) {
  const { layoutNodes, layoutEdges } = useMemo(() => {
    // depth 별 컬럼 레이아웃 (좌→우 의존성 트리). root(token)=가장 왼쪽.
    const depthOf = (n: RawNode): number => {
      if (n.type === "token") return -1;
      const d = n.data?.depth;
      return typeof d === "number" ? d : 0;
    };
    const byDepth = new Map<number, RawNode[]>();
    for (const n of nodes) {
      const d = depthOf(n);
      if (!byDepth.has(d)) byDepth.set(d, []);
      byDepth.get(d)!.push(n);
    }
    const GAP = 86;
    const COL = 330;
    const maxCol = Math.max(...[...byDepth.values()].map((a) => a.length), 1);
    const colH = maxCol * GAP;
    const depths = [...byDepth.keys()].sort((a, b) => a - b);

    const rfNodes: Node[] = [];
    depths.forEach((d) => {
      const arr = byDepth.get(d)!;
      const x = 40 + (d + 1) * COL;
      arr.forEach((n, i) => {
        const approx = Boolean(n.data?.approx);
        const kind = String(n.data?.category ?? n.type);
        rfNodes.push({
          id: n.id,
          position: { x, y: i * GAP + (colH - arr.length * GAP) / 2 },
          sourcePosition: Position.Right,
          targetPosition: Position.Left,
          data: { label: nodeLabel(n) },
          style: {
            background: KIND_BG[kind] ?? "#334155",
            color: "#e5e7eb",
            border: approx ? "1px dashed #f59e0b" : "1px solid rgba(255,255,255,0.18)",
            borderRadius: 10,
            padding: "8px 12px",
            fontSize: 12,
            width: 250,
            textAlign: "left",
          },
        });
      });
    });

    const layoutEdges: Edge[] = edges.map((e) => {
      const color = EDGE_COLOR[e.edge_type ?? ""] ?? "#475569";
      const flow = FLOW.has(e.edge_type ?? "");
      // coverage(검증 비율): 있으면 라벨에 붙이고, 90% 미만이면 점선으로 "부분검증" 표시
      const cov = typeof e.coverage === "number" ? e.coverage : null;
      const underVerified = cov != null && cov < 0.9;
      const label =
        cov != null ? `${e.label ?? ""}  ·  cov ${(cov * 100).toFixed(0)}%`.trim() : e.label;
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        label,
        animated: flow, // 프로토콜 흐름 엣지만 흐르는 점선
        style: {
          stroke: color,
          strokeWidth: flow ? 2 : 1.5,
          strokeDasharray: underVerified ? "2 3" : undefined,
          opacity: underVerified ? 0.6 : 1,
        },
        labelStyle: { fontSize: 10, fill: underVerified ? "#f59e0b" : "#cbd5e1" },
        labelBgStyle: { fill: "#0f172a", fillOpacity: 0.75 },
        labelBgPadding: [4, 2] as [number, number],
      };
    });

    return { layoutNodes: rfNodes, layoutEdges };
  }, [nodes, edges]);

  // 드래그 가능하도록 상태로 관리 (정적 prop 이면 드래그가 제자리로 튕김)
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState(layoutNodes);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(layoutEdges);
  useEffect(() => setRfNodes(layoutNodes), [layoutNodes, setRfNodes]);
  useEffect(() => setRfEdges(layoutEdges), [layoutEdges, setRfEdges]);

  // 노드 클릭 → 상세 패널 (주소 + 외부 탐색기 링크)
  const rawById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = selectedId ? rawById.get(selectedId) ?? null : null;
  const onNodeClick = useCallback(
    (_e: React.MouseEvent, node: Node) => setSelectedId(node.id),
    [],
  );

  return (
    <div style={{ position: "relative", flex: 1, minHeight: 0, background: "#0b1220" }}>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={() => setSelectedId(null)}
        fitView
        minZoom={0.2}
        proOptions={{ hideAttribution: true }}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
      >
        <Background color="#1e293b" gap={24} />
        <Controls />
        <MiniMap pannable zoomable />
      </ReactFlow>
      {selected && <NodeInspector node={selected} onClose={() => setSelectedId(null)} />}
    </div>
  );
}
