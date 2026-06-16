"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

export type EoaFlowTransfer = {
  direction: "in" | "out" | "internal";
  token: string;
  symbol: string;
  amount?: number;
  count: number;
};

export type EoaFlowDetail = {
  event_id?: string;
  address?: string;
  tx_hash?: string;
  datetime_utc?: string;
  block_number?: number;
  category?: string;
  protocol?: string;
  action?: string;
  transfers?: EoaFlowTransfer[];
};

export type EoaFlowNode = {
  id: string;
  type: "eoa" | "event" | "protocol" | "asset" | string;
  label: string;
  data: {
    kind: "eoa" | "safe" | "event" | "protocol" | "asset" | string;
    category?: string;
    protocol?: string;
    action?: string;
    address?: string;
    lane?: number;
    step?: number;
    tx_hash?: string;
    block_number?: number;
    datetime_utc?: string;
    target?: string;
    target_label?: string;
    symbol?: string;
    event_count?: number;
    dfs_depth?: number;
    discovered_by?: string;
    first_seen_utc?: string;
    last_seen_utc?: string;
    category_counts?: Record<string, number>;
    transfers?: EoaFlowTransfer[];
  };
};

export type EoaFlowEdge = {
  id: string;
  source: string;
  target: string;
  edge_type: string;
  category?: string;
  label?: string;
  amount?: number;
  symbol?: string;
  tx_hash?: string;
  event_count?: number;
  details?: EoaFlowDetail[];
};

const CATEGORY_COLOR: Record<string, string> = {
  lending: "#38bdf8",
  yield_basis: "#22c55e",
  vault: "#a78bfa",
  pendle: "#f97316",
  swap: "#f59e0b",
  bridge: "#14b8a6",
  fx_long: "#ef4444",
  timeline: "#64748b",
};

const NODE_BG: Record<string, string> = {
  eoa: "#1f2937",
  safe: "#115e59",
  protocol: "#172554",
  asset: "#312e81",
};

function shortAddress(addr?: string): string {
  if (!addr) return "";
  return addr.length === 42 ? `${addr.slice(0, 6)}...${addr.slice(-4)}` : addr;
}

function nodeColor(n: EoaFlowNode): string {
  if (n.type === "event") return CATEGORY_COLOR[n.data.category ?? ""] ?? "#334155";
  if (n.type === "eoa" && n.data.kind === "safe") return NODE_BG.safe;
  return NODE_BG[n.type] ?? "#334155";
}

function edgeColor(e: EoaFlowEdge): string {
  if (e.edge_type === "wallet_move") return "#f8fafc";
  if (e.edge_type === "wallet_transfer") return "#c084fc";
  if (e.edge_type === "protocol_flow") return CATEGORY_COLOR[e.category ?? ""] ?? "#94a3b8";
  if (e.edge_type === "asset_in") return "#10b981";
  if (e.edge_type === "asset_out") return "#f43f5e";
  if (e.edge_type === "timeline") return "#64748b";
  return CATEGORY_COLOR[e.category ?? ""] ?? "#94a3b8";
}

function laneCount(nodes: EoaFlowNode[]): number {
  return Math.max(1, ...nodes.map((n) => (typeof n.data.lane === "number" ? n.data.lane + 1 : 1)));
}

function maxStep(nodes: EoaFlowNode[]): number {
  return Math.max(0, ...nodes.map((n) => (typeof n.data.step === "number" ? n.data.step : 0)));
}

function nodePosition(
  n: EoaFlowNode,
  metrics: { lanes: number; maxStep: number; hasEventNodes: boolean; protocolIndex: Map<string, number>; assetIndex: Map<string, number> },
) {
  const lane = typeof n.data.lane === "number" ? n.data.lane : 0;
  const step = typeof n.data.step === "number" ? n.data.step : 0;
  const stepsPerRow = 12;
  const row = Math.max(0, Math.floor(step / stepsPerRow));
  const col = Math.max(0, step % stepsPerRow);
  const eventGap = 290;
  const rowGap = 150;
  const rowsPerLane = Math.max(1, Math.ceil((metrics.maxStep + 1) / stepsPerRow));
  const eventTop = metrics.hasEventNodes ? 520 : 90;
  const laneGap = 90 + rowsPerLane * rowGap;
  const y = eventTop + lane * laneGap + row * rowGap;

  if (n.type === "eoa") {
    const depth = typeof n.data.dfs_depth === "number" ? n.data.dfs_depth : 0;
    return { x: 40 + depth * 270, y: 80 + lane * 76 };
  }
  if (n.type === "event") return { x: 300 + col * eventGap, y };

  const railX = metrics.hasEventNodes ? 300 + Math.min(metrics.maxStep + 1, stepsPerRow) * eventGap + 360 : 690;
  if (n.type === "protocol") {
    const index = metrics.protocolIndex.get(n.id) ?? 0;
    return { x: railX, y: eventTop + index * 92 };
  }
  if (n.type === "asset") {
    const index = metrics.assetIndex.get(n.id) ?? 0;
    return { x: railX + 300, y: eventTop + index * 82 };
  }
  return { x: railX, y: eventTop + metrics.lanes * laneGap };
}

function Inspector({ node, onClose }: { node: EoaFlowNode; onClose: () => void }) {
  const addr = node.data.address || node.data.target;
  const tx = node.data.tx_hash;
  const transfers = node.data.transfers ?? [];
  const counts = node.data.category_counts ?? {};

  return (
    <aside className="absolute right-4 top-4 z-20 max-h-[calc(100%-2rem)] w-[360px] overflow-auto rounded-md border border-white/10 bg-[#101725]/95 p-4 shadow-2xl backdrop-blur">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{node.type}</div>
          <div className="mt-1 whitespace-pre-line text-sm font-semibold leading-snug text-slate-100">{node.label}</div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-white/10 px-2 py-1 text-xs text-slate-400 hover:bg-white/10 hover:text-slate-100"
          aria-label="Close"
        >
          x
        </button>
      </div>

      <div className="space-y-4 text-xs">
        {(node.data.category || node.data.action || node.data.protocol) && (
          <section className="grid grid-cols-[80px_1fr] gap-y-1.5">
            {node.data.category && <span className="text-slate-500">category</span>}
            {node.data.category && <span className="text-slate-200">{node.data.category}</span>}
            {node.data.protocol && <span className="text-slate-500">protocol</span>}
            {node.data.protocol && <span className="text-slate-200">{node.data.protocol}</span>}
            {node.data.action && <span className="text-slate-500">action</span>}
            {node.data.action && <span className="text-slate-200">{node.data.action}</span>}
            {node.data.datetime_utc && <span className="text-slate-500">time</span>}
            {node.data.datetime_utc && <span className="font-mono text-slate-200">{node.data.datetime_utc}</span>}
            {node.data.block_number != null && <span className="text-slate-500">block</span>}
            {node.data.block_number != null && <span className="font-mono text-slate-200">{node.data.block_number.toLocaleString()}</span>}
          </section>
        )}

        {addr && (
          <section>
            <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">address</div>
            <a
              href={`https://etherscan.io/address/${addr}`}
              target="_blank"
              rel="noopener noreferrer"
              className="block truncate rounded-md border border-white/10 bg-white/5 px-2.5 py-2 font-mono text-[11px] text-slate-200 hover:bg-white/10"
              title={addr}
            >
              {addr}
            </a>
          </section>
        )}

        {tx && (
          <section>
            <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">tx</div>
            <a
              href={`https://etherscan.io/tx/${tx}`}
              target="_blank"
              rel="noopener noreferrer"
              className="block truncate rounded-md border border-white/10 bg-white/5 px-2.5 py-2 font-mono text-[11px] text-slate-200 hover:bg-white/10"
              title={tx}
            >
              {tx}
            </a>
          </section>
        )}

        {transfers.length > 0 && (
          <section>
            <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">asset delta</div>
            <div className="space-y-1.5">
              {transfers.map((tr) => (
                <a
                  key={`${tr.direction}:${tr.token}:${tr.symbol}`}
                  href={`https://etherscan.io/token/${tr.token}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 rounded-md border border-white/10 bg-white/5 px-2.5 py-2 hover:bg-white/10"
                  title={tr.token}
                >
                  <span className={tr.direction === "out" ? "text-rose-300" : "text-emerald-300"}>
                    {tr.direction === "out" ? "-" : "+"}
                  </span>
                  <span className="font-mono text-slate-100">{tr.amount?.toLocaleString() ?? `${tr.count}x`}</span>
                  <span className="truncate text-slate-400">{tr.symbol}</span>
                </a>
              ))}
            </div>
          </section>
        )}

        {Object.keys(counts).length > 0 && (
          <section>
            <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">category counts</div>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(counts).map(([k, v]) => (
                <span key={k} className="rounded-md border border-white/10 bg-white/5 px-2 py-1 font-mono text-[10px] text-slate-300">
                  {k} {v}
                </span>
              ))}
            </div>
          </section>
        )}
      </div>
    </aside>
  );
}

function EdgeInspector({
  edge,
  source,
  target,
  onClose,
}: {
  edge: EoaFlowEdge;
  source?: EoaFlowNode;
  target?: EoaFlowNode;
  onClose: () => void;
}) {
  const details = edge.details ?? [];
  return (
    <aside className="absolute left-4 top-4 z-20 max-h-[calc(100%-2rem)] w-[430px] overflow-auto rounded-md border border-white/10 bg-[#101725]/95 p-4 shadow-2xl backdrop-blur">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">edge</div>
          <div className="mt-1 text-sm font-semibold leading-snug text-slate-100">{edge.label ?? edge.edge_type}</div>
          <div className="mt-1 truncate font-mono text-[10px] text-slate-500">
            {source?.label ?? edge.source} {"->"} {target?.label ?? edge.target}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-white/10 px-2 py-1 text-xs text-slate-400 hover:bg-white/10 hover:text-slate-100"
          aria-label="Close"
        >
          x
        </button>
      </div>

      <div className="mb-3 flex flex-wrap gap-1.5 text-[10px]">
        <span className="rounded-md border border-white/10 bg-white/5 px-2 py-1 font-mono text-slate-300">
          {edge.edge_type}
        </span>
        {edge.category && (
          <span className="rounded-md border border-white/10 bg-white/5 px-2 py-1 font-mono text-slate-300">
            {edge.category}
          </span>
        )}
        <span className="rounded-md border border-white/10 bg-white/5 px-2 py-1 font-mono text-slate-300">
          {details.length || edge.event_count || 0} events
        </span>
      </div>

      {details.length === 0 ? (
        <div className="rounded-md border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-400">
          상세 tx는 아직 이 edge에 붙지 않았고, 요약 edge만 있습니다.
          {edge.tx_hash && (
            <a
              href={`https://etherscan.io/tx/${edge.tx_hash}`}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 block truncate font-mono text-[11px] text-slate-200 hover:text-white"
            >
              sample {edge.tx_hash}
            </a>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {details.map((detail, index) => (
            <div key={`${detail.event_id ?? detail.tx_hash ?? index}`} className="rounded-md border border-white/10 bg-white/5 p-2.5">
              <div className="flex items-center gap-2 text-[10px] text-slate-500">
                <span className="font-mono text-slate-300">{detail.datetime_utc?.slice(0, 10) ?? "unknown"}</span>
                {detail.category && <span>{detail.category}</span>}
                {detail.block_number != null && <span className="ml-auto font-mono">{detail.block_number.toLocaleString()}</span>}
              </div>
              <div className="mt-1 text-xs font-medium text-slate-100">
                {detail.protocol || detail.category || "transfer"}
                {detail.action ? <span className="text-slate-400"> · {detail.action}</span> : null}
              </div>
              {(detail.transfers ?? []).length > 0 && (
                <div className="mt-2 space-y-1">
                  {(detail.transfers ?? []).map((tr) => (
                    <div key={`${tr.direction}:${tr.token}:${tr.symbol}`} className="flex items-center gap-2 font-mono text-[10px]">
                      <span className={tr.direction === "out" ? "text-rose-300" : "text-emerald-300"}>
                        {tr.direction === "out" ? "-" : tr.direction === "in" ? "+" : "~"}
                      </span>
                      <span className="text-slate-100">{tr.amount?.toLocaleString() ?? `${tr.count}x`}</span>
                      <span className="truncate text-slate-400">{tr.symbol}</span>
                    </div>
                  ))}
                </div>
              )}
              {detail.tx_hash && (
                <a
                  href={`https://etherscan.io/tx/${detail.tx_hash}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={detail.tx_hash}
                  className="mt-2 block truncate font-mono text-[10px] text-slate-500 hover:text-slate-200"
                >
                  {detail.tx_hash}
                </a>
              )}
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}

export function EoaFlowCanvas({ nodes, edges }: { nodes: EoaFlowNode[]; edges: EoaFlowEdge[] }) {
  const visibleNodes = useMemo(() => nodes.filter((n) => n.type !== "event"), [nodes]);
  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => edges.filter((e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target)),
    [edges, visibleNodeIds],
  );
  const rawById = useMemo(() => new Map(visibleNodes.map((n) => [n.id, n])), [visibleNodes]);
  const rawEdgeById = useMemo(() => new Map(visibleEdges.map((e) => [e.id, e])), [visibleEdges]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const selected = selectedId ? rawById.get(selectedId) ?? null : null;
  const selectedEdge = selectedEdgeId ? rawEdgeById.get(selectedEdgeId) ?? null : null;

  const { layoutNodes, layoutEdges } = useMemo(() => {
    const protocolIds = visibleNodes.filter((n) => n.type === "protocol").map((n) => n.id).sort();
    const assetIds = visibleNodes.filter((n) => n.type === "asset").map((n) => n.id).sort();
    const metrics = {
      lanes: laneCount(visibleNodes),
      maxStep: maxStep(visibleNodes),
      hasEventNodes: false,
      protocolIndex: new Map(protocolIds.map((id, i) => [id, i])),
      assetIndex: new Map(assetIds.map((id, i) => [id, i])),
    };

    const rfNodes: Node[] = visibleNodes.map((n) => {
      const pos = nodePosition(n, metrics);
      const isEvent = n.type === "event";
      const isEoa = n.type === "eoa";
      const isSafe = isEoa && n.data.kind === "safe";
      return {
        id: n.id,
        position: pos,
        sourcePosition: isEvent || isEoa ? Position.Right : Position.Right,
        targetPosition: isEvent ? Position.Left : Position.Left,
        data: { label: n.label },
        style: {
          background: nodeColor(n),
          color: "#e5e7eb",
          border: isEoa ? `2px solid ${isSafe ? "#5eead4" : "#f8fafc"}` : "1px solid rgba(255,255,255,0.18)",
          borderRadius: 8,
          padding: "8px 11px",
          fontSize: isEvent ? 10.5 : 11,
          lineHeight: 1.25,
          width: isEvent ? 250 : 220,
          minHeight: isEvent ? 88 : 44,
          textAlign: "left",
          whiteSpace: "pre-line",
        },
      };
    });

    const rfEdges: Edge[] = visibleEdges.map((e) => {
      const color = edgeColor(e);
      const isTimeline = e.edge_type === "timeline";
      const isAsset = e.edge_type.startsWith("asset_");
      const isWallet = e.edge_type === "wallet_move" || e.edge_type === "wallet_transfer";
      const isProtocol = e.edge_type === "protocol_flow";
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        label: isTimeline ? undefined : e.label,
        animated: e.edge_type === "call" || e.edge_type === "wallet_move" || isProtocol,
        data: e,
        style: {
          stroke: color,
          strokeWidth: isTimeline ? 1.6 : isWallet ? 2.6 : isAsset ? 1.4 : isProtocol ? 2.4 : 2.2,
          strokeDasharray: isTimeline ? "4 5" : e.edge_type === "asset_out" || e.edge_type === "wallet_transfer" ? "3 4" : undefined,
          opacity: isTimeline ? 0.62 : 0.95,
        },
        labelStyle: { fontSize: 9.5, fill: color },
        labelBgStyle: { fill: "#0f172a", fillOpacity: 0.82 },
        labelBgPadding: [3, 2] as [number, number],
      };
    });

    return { layoutNodes: rfNodes, layoutEdges: rfEdges };
  }, [visibleNodes, visibleEdges]);

  const focus = useMemo(() => {
    if (!selectedId && !selectedEdgeId) return null;
    const nodeIds = new Set<string>(selectedId ? [selectedId] : []);
    const edgeIds = new Set<string>();
    if (selectedEdgeId) {
      const selected = rawEdgeById.get(selectedEdgeId);
      if (selected) {
        nodeIds.add(selected.source);
        nodeIds.add(selected.target);
        edgeIds.add(selected.id);
      }
    }
    for (const e of visibleEdges) {
      if (!selectedId) continue;
      if (e.source !== selectedId && e.target !== selectedId) continue;
      nodeIds.add(e.source);
      nodeIds.add(e.target);
      edgeIds.add(e.id);
    }
    return { nodeIds, edgeIds };
  }, [rawEdgeById, selectedEdgeId, selectedId, visibleEdges]);

  const highlightedNodes = useMemo(() => {
    if (!focus) return layoutNodes;
    return layoutNodes.map((n) => {
      const active = focus.nodeIds.has(n.id);
      return {
        ...n,
        style: {
          ...n.style,
          opacity: active ? 1 : 0.14,
          filter: active ? "none" : "grayscale(0.8)",
          boxShadow: n.id === selectedId ? "0 0 0 3px rgba(248,250,252,0.22), 0 12px 24px rgba(0,0,0,0.35)" : undefined,
        },
      };
    });
  }, [focus, layoutNodes, selectedId]);

  const highlightedEdges = useMemo(() => {
    if (!focus) return layoutEdges;
    return layoutEdges.map((e) => {
      const active = focus.edgeIds.has(e.id);
      return {
        ...e,
        animated: active && e.animated,
        style: { ...e.style, opacity: active ? 1 : 0.08, strokeWidth: active ? 3 : 1 },
        labelStyle: { ...e.labelStyle, opacity: active ? 1 : 0.12 },
        labelBgStyle: { ...e.labelBgStyle, fillOpacity: active ? 0.82 : 0.1 },
      };
    });
  }, [focus, layoutEdges]);

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState(highlightedNodes);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(highlightedEdges);
  useEffect(() => setRfNodes(highlightedNodes), [highlightedNodes, setRfNodes]);
  useEffect(() => setRfEdges(highlightedEdges), [highlightedEdges, setRfEdges]);

  const onNodeClick = useCallback((_e: React.MouseEvent, node: Node) => {
    setSelectedId(node.id);
    setSelectedEdgeId(null);
  }, []);

  const onEdgeClick = useCallback((_e: React.MouseEvent, edge: Edge) => {
    setSelectedEdgeId(edge.id);
    setSelectedId(null);
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedId(null);
    setSelectedEdgeId(null);
  }, []);

  return (
    <div style={{ position: "relative", flex: 1, minHeight: 0, background: "#0b1220" }}>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onEdgeClick={onEdgeClick}
        onPaneClick={clearSelection}
        fitView
        minZoom={0.08}
        proOptions={{ hideAttribution: true }}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
      >
        <Background color="#1e293b" gap={24} />
        <Controls />
        <MiniMap pannable zoomable />
      </ReactFlow>
      {selectedEdge && (
        <EdgeInspector
          edge={selectedEdge}
          source={rawById.get(selectedEdge.source)}
          target={rawById.get(selectedEdge.target)}
          onClose={() => setSelectedEdgeId(null)}
        />
      )}
      {selected && <Inspector node={selected} onClose={() => setSelectedId(null)} />}
      <div className="pointer-events-none absolute bottom-4 left-4 rounded-md border border-white/10 bg-[#101725]/90 px-3 py-2 text-[10px] text-slate-400">
        <div className="flex flex-wrap gap-3">
          <Legend c="#64748b" t="timeline" />
          <Legend c="#f8fafc" t="wallet move" />
          <Legend c="#115e59" t="safe" />
          <Legend c="#c084fc" t="wallet tx" />
          <Legend c="#10b981" t="asset in" />
          <Legend c="#f43f5e" t="asset out" />
          <Legend c="#38bdf8" t="lending" />
          <Legend c="#22c55e" t="yield basis" />
          <Legend c="#a78bfa" t="vault" />
          <Legend c="#f59e0b" t="swap" />
        </div>
      </div>
    </div>
  );
}

function Legend({ c, t }: { c: string; t: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className="inline-block size-2 rounded-sm" style={{ backgroundColor: c }} />
      {t}
    </span>
  );
}
