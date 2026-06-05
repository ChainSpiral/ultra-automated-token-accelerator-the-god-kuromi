"use client";

import { useMemo, useEffect } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  MarkerType,
  Position,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

export type FlowNode = {
  id: string;
  label: string;
  data: { kind: string; is_seed: boolean; in_cycle: boolean; address: string };
};
export type FlowEdge = {
  id: string;
  source: string;
  target: string;
  asset: string;
  amount: number;
  count: number;
  label: string;
  in_cycle: boolean;
  mint_burn: boolean;
  morpho?: boolean;
  role?: string | null;
  sample_tx?: string;
};

const ASSET_COLOR: Record<string, string> = {
  xUSD: "#a78bfa",
  deUSD: "#f472b6",
  sdeUSD: "#fb923c",
  USDC: "#60a5fa",
  USDT: "#34d399",
};
const KIND_BG: Record<string, string> = {
  EOA: "#334155",
  contract: "#1d4ed8",
  token: "#6d28d9",
  mint_burn: "#7f1d1d",
};

const CYCLE = "#ef4444";

function kindOf(n: FlowNode): string {
  if (n.data.kind === "mint_burn") return "mint_burn";
  if (/\(token\)/.test(n.label)) return "token";
  return n.data.kind === "contract" ? "contract" : "EOA";
}

// seed 에서 출발하는 BFS 레이어링 → 좌→우 흐름 (그림처럼)
function layer(nodes: FlowNode[], edges: FlowEdge[]): Map<string, number> {
  const out = new Map<string, string[]>();
  for (const e of edges) {
    if (!out.has(e.source)) out.set(e.source, []);
    out.get(e.source)!.push(e.target);
  }
  const depth = new Map<string, number>();
  const q: string[] = [];
  for (const n of nodes) if (n.data.is_seed) { depth.set(n.id, 0); q.push(n.id); }
  if (q.length === 0 && nodes[0]) { depth.set(nodes[0].id, 0); q.push(nodes[0].id); }
  while (q.length) {
    const v = q.shift()!;
    const d = depth.get(v)!;
    for (const w of out.get(v) ?? []) {
      if (!depth.has(w)) { depth.set(w, d + 1); q.push(w); }
    }
  }
  let max = 0;
  for (const d of depth.values()) max = Math.max(max, d);
  for (const n of nodes) if (!depth.has(n.id)) depth.set(n.id, max + 1); // 미도달은 맨 오른쪽
  return depth;
}

export function FlowCanvas({ nodes, edges }: { nodes: FlowNode[]; edges: FlowEdge[] }) {
  const { layoutNodes, layoutEdges } = useMemo(() => {
    const depth = layer(nodes, edges);
    const byCol = new Map<number, FlowNode[]>();
    for (const n of nodes) {
      const d = depth.get(n.id)!;
      if (!byCol.has(d)) byCol.set(d, []);
      byCol.get(d)!.push(n);
    }
    const GAP = 78, COL = 320;
    const maxCol = Math.max(...[...byCol.values()].map((a) => a.length), 1);
    const colH = maxCol * GAP;

    const rfNodes: Node[] = [];
    [...byCol.keys()].sort((a, b) => a - b).forEach((d) => {
      const arr = byCol.get(d)!;
      arr.forEach((n, i) => {
        const kind = kindOf(n);
        const cyclic = n.data.in_cycle;
        rfNodes.push({
          id: n.id,
          position: { x: 40 + d * COL, y: i * GAP + (colH - arr.length * GAP) / 2 },
          sourcePosition: Position.Right,
          targetPosition: Position.Left,
          data: { label: n.label },
          style: {
            background: KIND_BG[kind] ?? "#334155",
            color: "#e5e7eb",
            border: cyclic
              ? `2px solid ${CYCLE}`
              : n.data.is_seed
                ? "2px solid #fbbf24"
                : "1px solid rgba(255,255,255,0.18)",
            boxShadow: cyclic ? `0 0 12px ${CYCLE}88` : undefined,
            borderRadius: 10,
            padding: "7px 11px",
            fontSize: 11,
            width: 220,
            textAlign: "left",
          },
        });
      });
    });

    const layoutEdges: Edge[] = edges.map((e) => {
      // Morpho 담보/차입 = 노랑 강조, 사이클 = 빨강, mint/burn = 점선
      const color = e.in_cycle ? CYCLE : e.morpho ? "#eab308" : ASSET_COLOR[e.asset] ?? "#64748b";
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        animated: e.in_cycle || !!e.morpho,
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
        style: {
          stroke: color,
          strokeWidth: e.in_cycle || e.morpho ? 2.5 : 1.4,
          strokeDasharray: e.mint_burn ? "3 3" : undefined,
          opacity: e.mint_burn ? 0.7 : 1,
        },
        labelStyle: { fontSize: 9.5, fill: e.in_cycle ? "#fca5a5" : e.morpho ? "#fde047" : "#cbd5e1" },
        labelBgStyle: { fill: "#0f172a", fillOpacity: 0.78 },
        labelBgPadding: [3, 2] as [number, number],
      };
    });

    return { layoutNodes: rfNodes, layoutEdges };
  }, [nodes, edges]);

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
        minZoom={0.15}
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
