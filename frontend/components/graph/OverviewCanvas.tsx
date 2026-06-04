"use client";

import { useMemo, useEffect } from "react";
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
type RawEdge = { id: string; source: string; target: string; label?: string; edge_type?: string };

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
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        animated: FLOW.has(e.edge_type ?? ""), // 프로토콜 흐름 엣지만 흐르는 점선
        style: { stroke: color, strokeWidth: FLOW.has(e.edge_type ?? "") ? 2 : 1.5 },
        labelStyle: { fontSize: 10, fill: "#cbd5e1" },
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

  return (
    <div style={{ flex: 1, minHeight: 0, background: "#0b1220" }}>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
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
    </div>
  );
}
