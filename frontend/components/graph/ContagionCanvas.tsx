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

export type CMarket = { id: string; loan: string | null; lltv: number | null; oracle: string; usd: number };
export type CNode = {
  id: string;
  type: "vault" | "collateral" | "oracle" | "issuer";
  label: string;
  // vault
  asset?: string;
  tvl_usd?: number;
  // collateral
  symbol?: string;
  usd?: number;
  pct_of_vault?: number;
  n_markets?: number;
  shared?: boolean;
  grade?: string | null;
  oracle_class?: string | null;
  sees?: string | null;
  self_referential?: boolean;
  issuer?: string | null;
  markets?: CMarket[];
  // oracle / issuer
  n_collaterals?: number;
  converge?: boolean;
  confidence?: string;
};
export type CEdge = {
  id: string;
  source: string;
  target: string;
  usd?: number;
  pct?: number;
  n_markets?: number;
  shared?: boolean;
  label?: string;
  kind?: string;
};

const GRADE_COLOR: Record<string, string> = {
  CRITICAL: "#ef4444",
  DISTRESSED: "#fb923c",
  HIGH: "#f59e0b",
  MED: "#eab308",
  CHECK: "#64748b",
  ok: "#22c55e",
};
const UNSCANNED = "#475569";

function gradeColor(g?: string | null) {
  return (g && GRADE_COLOR[g]) || UNSCANNED;
}

export function ContagionCanvas({ nodes, edges }: { nodes: CNode[]; edges: CEdge[] }) {
  const { rfNodes, rfEdges } = useMemo(() => {
    const vault = nodes.find((n) => n.type === "vault");
    const collats = nodes
      .filter((n) => n.type === "collateral")
      .sort((a, b) => (b.pct_of_vault ?? 0) - (a.pct_of_vault ?? 0));
    const issuers = nodes
      .filter((n) => n.type === "issuer")
      .sort((a, b) => (b.pct_of_vault ?? 0) - (a.pct_of_vault ?? 0));
    const oracles = nodes.filter((n) => n.type === "oracle");

    const GAP = 70;
    const colH = Math.max(collats.length, 1) * GAP;
    const out: Node[] = [];

    if (vault) {
      out.push({
        id: vault.id,
        position: { x: 40, y: colH / 2 - 30 },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: {
          label: (
            <div style={{ textAlign: "left", lineHeight: 1.35 }}>
              <div style={{ fontWeight: 700, fontSize: 12 }}>🏦 {vault.label}</div>
              <div style={{ fontSize: 10, opacity: 0.75 }}>
                {vault.asset} vault · TVL ${fmtM(vault.tvl_usd)}
              </div>
            </div>
          ),
        },
        style: {
          background: "#0f172a",
          color: "#e5e7eb",
          border: "2px solid #38bdf8",
          borderRadius: 12,
          padding: "9px 13px",
          width: 220,
          fontSize: 11,
        },
      });
    }

    collats.forEach((c, i) => {
      const pct = c.pct_of_vault ?? 0;
      const col = gradeColor(c.grade);
      const danger = c.shared && pct >= 0.5;
      out.push({
        id: c.id,
        position: { x: 380, y: i * GAP },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: {
          label: (
            <div style={{ textAlign: "left", lineHeight: 1.3 }}>
              <div style={{ fontWeight: 600, fontSize: 11.5 }}>
                {c.symbol}
                {c.self_referential ? " ⟳" : ""}
              </div>
              <div style={{ fontSize: 10 }}>
                <b>{Math.round(pct * 100)}%</b> · {c.n_markets}mkt
                {c.shared ? " · 공유" : ""}
              </div>
              <div style={{ fontSize: 9, opacity: 0.7 }}>
                {c.grade ?? "unscanned"}
                {c.oracle_class ? ` · ${c.oracle_class}` : ""}
              </div>
            </div>
          ),
        },
        style: {
          background: "#111827",
          color: "#e5e7eb",
          border: `${danger ? 3 : c.shared ? 2 : 1}px solid ${col}`,
          boxShadow: danger ? `0 0 14px ${col}aa` : undefined,
          borderRadius: 10,
          padding: "6px 10px",
          width: 168,
          fontSize: 11,
        },
      });
    });

    // 발행자 수렴 레이어 (★ 여러 담보 → 한 발행자 = 그래프여야만 하는 fan-in)
    const issH = Math.max(issuers.length, 1) * GAP;
    issuers.forEach((iss, i) => {
      const pct = iss.pct_of_vault ?? 0;
      const danger = pct >= 0.5;
      const col = danger ? "#ef4444" : iss.converge ? "#f59e0b" : "#64748b";
      out.push({
        id: iss.id,
        position: { x: 720, y: i * GAP + (colH - issH) / 2 },
        targetPosition: Position.Left,
        data: {
          label: (
            <div style={{ textAlign: "left", lineHeight: 1.3 }}>
              <div style={{ fontSize: 11, fontWeight: 700 }}>🏷 {iss.label}</div>
              <div style={{ fontSize: 10 }}>
                <b>{Math.round(pct * 100)}%</b> · {iss.n_collaterals}담보 수렴
              </div>
              <div style={{ fontSize: 8.5, opacity: 0.55 }}>발행자(heuristic)</div>
            </div>
          ),
        },
        style: {
          background: "#1a1505",
          color: "#e5e7eb",
          border: `${danger ? 3 : 2}px solid ${col}`,
          boxShadow: danger ? `0 0 16px ${col}aa` : undefined,
          borderRadius: 10,
          padding: "6px 11px",
          width: 152,
          fontSize: 11,
        },
      });
    });

    oracles.forEach((o, i) => {
      out.push({
        id: o.id,
        position: { x: 1040, y: i * GAP + 20 },
        targetPosition: Position.Left,
        data: {
          label: (
            <div style={{ textAlign: "left", lineHeight: 1.3 }}>
              <div style={{ fontSize: 10, fontWeight: 600 }}>🔮 공유 오라클</div>
              <div style={{ fontSize: 9, opacity: 0.75 }}>
                {o.label} · {o.n_collaterals}개 담보
              </div>
            </div>
          ),
        },
        style: {
          background: "#1e1b4b",
          color: "#e5e7eb",
          border: "2px dashed #a78bfa",
          borderRadius: 10,
          padding: "6px 10px",
          width: 160,
          fontSize: 10,
        },
      });
    });

    const re: Edge[] = edges.map((e) => {
      if (e.kind === "issuer") {
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          style: { stroke: "#a16207", strokeWidth: 1.3, strokeDasharray: "2 2" },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#a16207", width: 12, height: 12 },
        };
      }
      if (e.kind === "oracle") {
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          animated: true,
          style: { stroke: "#a78bfa", strokeWidth: 1.6, strokeDasharray: "4 3" },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#a78bfa", width: 14, height: 14 },
        };
      }
      const pct = e.pct ?? 0;
      const danger = e.shared && pct >= 0.5;
      const color = danger ? "#ef4444" : e.shared ? "#f59e0b" : "#475569";
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        animated: danger,
        style: { stroke: color, strokeWidth: 1.4 + pct * 6 },
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
        labelStyle: { fontSize: 10, fill: danger ? "#fca5a5" : "#cbd5e1", fontWeight: danger ? 700 : 400 },
        labelBgStyle: { fill: "#0f172a", fillOpacity: 0.8 },
        labelBgPadding: [3, 2] as [number, number],
      };
    });

    return { rfNodes: out, rfEdges: re };
  }, [nodes, edges]);

  const [n, setN, onN] = useNodesState(rfNodes);
  const [ed, setEd, onE] = useEdgesState(rfEdges);
  useEffect(() => setN(rfNodes), [rfNodes, setN]);
  useEffect(() => setEd(rfEdges), [rfEdges, setEd]);

  return (
    <div style={{ flex: 1, minHeight: 0, background: "#0b1220" }}>
      <ReactFlow
        nodes={n}
        edges={ed}
        onNodesChange={onN}
        onEdgesChange={onE}
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

function fmtM(n?: number) {
  if (!n) return "0";
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return `${n.toFixed(0)}`;
}
