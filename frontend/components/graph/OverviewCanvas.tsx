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
  amount?: number;
};

interface HiddenEoaRelation {
  id: string;
  address: string;
  label: string;
  direction: "out" | "in";
  edgeLabel?: string;
  amount?: number;
}

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

function nodeKind(n: RawNode): string {
  return String(n.data?.category ?? n.data?.kind ?? n.type);
}

function isEoaNode(n: RawNode): boolean {
  return nodeKind(n) === "EOA";
}

function sideForAngle(angle: number, inward = false): Position {
  const x = Math.cos(angle) * (inward ? -1 : 1);
  const y = Math.sin(angle) * (inward ? -1 : 1);
  if (Math.abs(x) > Math.abs(y)) return x >= 0 ? Position.Right : Position.Left;
  return y >= 0 ? Position.Bottom : Position.Top;
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

function fmtTokenAmount(v: unknown): string {
  const n = typeof v === "number" ? v : NaN;
  if (!isFinite(n)) return "";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return Math.round(n).toLocaleString();
  return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function NodeInspector({
  node,
  hiddenEoas,
  onClose,
}: {
  node: RawNode;
  hiddenEoas: HiddenEoaRelation[];
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const addr = nodeAddress(node);
  const kind = nodeKind(node);
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

        {hiddenEoas.length > 0 && (
          <section>
            <div className="mb-1.5 flex items-center justify-between text-[10px] font-medium uppercase tracking-wider text-slate-500">
              <span>숨긴 EOA 주소</span>
              <span>{hiddenEoas.length}개</span>
            </div>
            <div className="space-y-1.5">
              {hiddenEoas.map((r) => (
                <a
                  key={`${r.id}:${r.address}`}
                  href={`https://etherscan.io/address/${r.address}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={r.address}
                  className="block rounded-md border border-white/10 bg-white/5 px-2.5 py-2 transition-colors hover:border-white/25 hover:bg-white/10"
                >
                  <div className="flex items-center gap-2">
                    <span className="shrink-0 font-mono text-[10px] text-slate-500">
                      {r.direction === "out" ? "→" : "←"}
                    </span>
                    <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-slate-200">
                      {r.address}
                    </span>
                    <span className="shrink-0 text-slate-500">↗</span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[10px] text-slate-400">
                    <span className="truncate">{r.label}</span>
                    {(r.edgeLabel || r.amount != null) && (
                      <span className="ml-auto shrink-0 font-mono">
                        {r.edgeLabel ?? fmtTokenAmount(r.amount)}
                      </span>
                    )}
                  </div>
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
  const { visibleNodes, visibleEdges, hiddenEoasByNode } = useMemo(() => {
    const visible = nodes.filter((n) => !isEoaNode(n));
    const allById = new Map(nodes.map((n) => [n.id, n]));
    const visibleIds = new Set(visible.map((n) => n.id));
    const hiddenByNode = new Map<string, HiddenEoaRelation[]>();

    const pushHidden = (nodeId: string, eoa: RawNode, edge: RawEdge, direction: "out" | "in") => {
      const addr = nodeAddress(eoa) ?? eoa.id;
      const arr = hiddenByNode.get(nodeId) ?? [];
      arr.push({
        id: edge.id,
        address: addr,
        label: eoa.label,
        direction,
        edgeLabel: edge.label,
        amount: edge.amount,
      });
      hiddenByNode.set(nodeId, arr);
    };

    for (const e of edges) {
      const source = allById.get(e.source);
      const target = allById.get(e.target);
      if (!source || !target) continue;
      const sourceEoa = isEoaNode(source);
      const targetEoa = isEoaNode(target);
      if (sourceEoa && !targetEoa && visibleIds.has(target.id)) pushHidden(target.id, source, e, "in");
      if (targetEoa && !sourceEoa && visibleIds.has(source.id)) pushHidden(source.id, target, e, "out");
    }

    for (const [nodeId, arr] of hiddenByNode) {
      hiddenByNode.set(
        nodeId,
        arr.sort((a, b) => (b.amount ?? 0) - (a.amount ?? 0) || a.address.localeCompare(b.address)),
      );
    }

    return {
      visibleNodes: visible,
      visibleEdges: edges.filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target)),
      hiddenEoasByNode: hiddenByNode,
    };
  }, [nodes, edges]);

  const { layoutNodes, layoutEdges } = useMemo(() => {
    const depthOf = (n: RawNode): number => {
      if (n.type === "token") return -1;
      const d = n.data?.depth;
      return typeof d === "number" ? d : 0;
    };
    const nodes = visibleNodes;
    const edges = visibleEdges;
    const nodeById = new Map(nodes.map((n) => [n.id, n]));
    const root = nodes.find((n) => n.type === "token") ?? nodes[0];
    const ringOf = (n: RawNode): number => Math.max(0, depthOf(n) + 1);
    const ringById = new Map(nodes.map((n) => [n.id, ringOf(n)]));
    const byRing = new Map<number, RawNode[]>();
    for (const n of nodes) {
      const r = ringOf(n);
      if (!byRing.has(r)) byRing.set(r, []);
      byRing.get(r)!.push(n);
    }

    const incoming = new Map<string, RawEdge[]>();
    for (const e of edges) {
      if (!nodeById.has(e.source) || !nodeById.has(e.target)) continue;
      const arr = incoming.get(e.target) ?? [];
      arr.push(e);
      incoming.set(e.target, arr);
    }

    const parentOf = new Map<string, string>();
    const weightByChild = new Map<string, number>();
    for (const n of nodes) {
      if (!root || n.id === root.id) continue;
      const targetRing = ringById.get(n.id) ?? 0;
      const candidates = (incoming.get(n.id) ?? [])
        .filter((e) => {
          const sourceRing = ringById.get(e.source);
          return sourceRing != null && sourceRing < targetRing;
        })
        .sort((a, b) => {
          const ar = ringById.get(a.source) ?? -1;
          const br = ringById.get(b.source) ?? -1;
          if (ar !== br) return br - ar;
          return (b.amount ?? 0) - (a.amount ?? 0);
        });
      const parent = candidates[0]?.source;
      if (parent) {
        parentOf.set(n.id, parent);
        weightByChild.set(n.id, candidates[0]?.amount ?? 0);
      }
    }
    if (root) {
      for (const n of nodes) {
        if (n.id !== root.id && !parentOf.has(n.id)) {
          parentOf.set(n.id, root.id);
          weightByChild.set(n.id, 0);
        }
      }
    }

    const childrenByParent = new Map<string, RawNode[]>();
    for (const [child, parent] of parentOf) {
      const c = nodeById.get(child);
      if (!c) continue;
      const arr = childrenByParent.get(parent) ?? [];
      arr.push(c);
      childrenByParent.set(parent, arr);
    }

    const subtreeWeight = new Map<string, number>();
    const measure = (id: string, stack = new Set<string>()): number => {
      const cached = subtreeWeight.get(id);
      if (cached != null) return cached;
      if (stack.has(id)) return 1;
      const children = childrenByParent.get(id) ?? [];
      if (children.length === 0) {
        subtreeWeight.set(id, 1);
        return 1;
      }
      stack.add(id);
      const total = children.reduce((sum, child) => sum + measure(child.id, stack), 0);
      stack.delete(id);
      const weight = Math.max(1, total);
      subtreeWeight.set(id, weight);
      return weight;
    };
    if (root) measure(root.id);

    const fanOrder = (arr: RawNode[]): RawNode[] => {
      const sorted = [...arr].sort((a, b) => {
        const sw = (subtreeWeight.get(b.id) ?? 1) - (subtreeWeight.get(a.id) ?? 1);
        if (sw !== 0) return sw;
        return (weightByChild.get(b.id) ?? 0) - (weightByChild.get(a.id) ?? 0);
      });
      const out: RawNode[] = [];
      sorted.forEach((child, i) => {
        if (i % 2 === 0) out.unshift(child);
        else out.push(child);
      });
      return out;
    };
    for (const [parent, arr] of childrenByParent) {
      childrenByParent.set(parent, fanOrder(arr));
    }

    const NODE_W = 250;
    const NODE_H = 54;
    const layoutById = new Map<string, { x: number; y: number; angle: number; depth: number }>();

    const fanSpanFor = (childCount: number, depth: number): number => {
      if (childCount <= 1) return 0;
      if (depth === 0) return Math.min(Math.PI * 0.86, Math.max(Math.PI * 0.62, childCount * 0.3));
      return Math.min(Math.PI * 0.92, Math.max(Math.PI * 0.5, childCount * 0.25));
    };

    const distanceFor = (childCount: number, depth: number): number => {
      const base = depth === 0 ? 560 : depth === 1 ? 590 : depth === 2 ? 560 : 460;
      return Math.max(380, base + Math.min(childCount, 12) * 22);
    };

    const placeFan = (parentId: string, stack = new Set<string>()) => {
      if (stack.has(parentId)) return;
      const parent = layoutById.get(parentId);
      if (!parent) return;
      const children = childrenByParent.get(parentId) ?? [];
      if (children.length === 0) return;
      const span = fanSpanFor(children.length, parent.depth);
      const distance = distanceFor(children.length, parent.depth);
      const start = parent.angle - span / 2;
      const step = children.length <= 1 ? 0 : span / (children.length - 1);
      stack.add(parentId);
      children.forEach((child, index) => {
        const angle = children.length === 1 ? parent.angle : start + step * index;
        const x = parent.x + Math.cos(angle) * distance;
        const y = parent.y + Math.sin(angle) * distance;
        layoutById.set(child.id, { x, y, angle, depth: parent.depth + 1 });
        placeFan(child.id, stack);
      });
      stack.delete(parentId);
    };

    if (root) {
      layoutById.set(root.id, { x: 0, y: 0, angle: 0, depth: 0 });
      placeFan(root.id);
    } else {
      nodes.forEach((n, i) => layoutById.set(n.id, { x: i * 300, y: 0, angle: 0, depth: 0 }));
    }

    const MIN_X = NODE_W + 92;
    const MIN_Y = NODE_H + 44;
    const ids = nodes.map((n) => n.id);
    for (let iter = 0; iter < 140; iter += 1) {
      let moved = false;
      for (let i = 0; i < ids.length; i += 1) {
        const a = layoutById.get(ids[i]);
        if (!a) continue;
        for (let j = i + 1; j < ids.length; j += 1) {
          const b = layoutById.get(ids[j]);
          if (!b) continue;
          let dx = b.x - a.x;
          let dy = b.y - a.y;
          if (dx === 0 && dy === 0) {
            dx = Math.cos((i + j) * 1.618);
            dy = Math.sin((i + j) * 1.618);
          }
          const overlapX = MIN_X - Math.abs(dx);
          const overlapY = MIN_Y - Math.abs(dy);
          if (overlapX <= 0 || overlapY <= 0) continue;

          const sx = dx >= 0 ? 1 : -1;
          const sy = dy >= 0 ? 1 : -1;
          const pushRootA = ids[i] !== root?.id;
          const pushRootB = ids[j] !== root?.id;
          const share = pushRootA && pushRootB ? 0.5 : 1;

          if (overlapX < overlapY) {
            const push = overlapX * share;
            if (pushRootA) a.x -= sx * push;
            if (pushRootB) b.x += sx * push;
          } else {
            const push = overlapY * share;
            if (pushRootA) a.y -= sy * push;
            if (pushRootB) b.y += sy * push;
          }
          moved = true;
        }
      }
      if (!moved) break;
    }

    const rfNodes: Node[] = [];
    nodes.forEach((n) => {
        const approx = Boolean(n.data?.approx);
        const kind = String(n.data?.category ?? n.type);
        const layout = layoutById.get(n.id) ?? { x: 0, y: 0, angle: 0, depth: 0 };
        const angle = layout.angle;
        const x = layout.x - NODE_W / 2;
        const y = layout.y - NODE_H / 2;
        rfNodes.push({
          id: n.id,
          position: { x, y },
          sourcePosition: n.id === root?.id ? Position.Right : sideForAngle(angle),
          targetPosition: n.id === root?.id ? Position.Left : sideForAngle(angle, true),
          data: { label: nodeLabel(n) },
          style: {
            background: KIND_BG[kind] ?? "#334155",
            color: "#e5e7eb",
            border: approx ? "1px dashed #f59e0b" : "1px solid rgba(255,255,255,0.18)",
            borderRadius: 8,
            padding: "8px 12px",
            fontSize: 12,
            width: NODE_W,
            textAlign: "left",
          },
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
  }, [visibleNodes, visibleEdges]);

  // 노드 클릭 → 상세 패널 (주소 + 외부 탐색기 링크)
  const rawById = useMemo(() => new Map(visibleNodes.map((n) => [n.id, n])), [visibleNodes]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = selectedId ? rawById.get(selectedId) ?? null : null;
  const focus = useMemo(() => {
    if (!selectedId) return null;
    const nodeIds = new Set<string>([selectedId]);
    const edgeIds = new Set<string>();
    for (const e of visibleEdges) {
      if (e.source !== selectedId && e.target !== selectedId) continue;
      nodeIds.add(e.source);
      nodeIds.add(e.target);
      edgeIds.add(e.id);
    }
    return { nodeIds, edgeIds };
  }, [visibleEdges, selectedId]);

  const highlightedNodes = useMemo(() => {
    if (!focus) return layoutNodes;
    return layoutNodes.map((n) => {
      const active = focus.nodeIds.has(n.id);
      const selectedNode = n.id === selectedId;
      return {
        ...n,
        style: {
          ...n.style,
          opacity: active ? 1 : 0.12,
          filter: active ? "none" : "grayscale(0.75)",
          border: selectedNode
            ? "2px solid #f8fafc"
            : active
              ? "1px solid rgba(255,255,255,0.42)"
              : "1px solid rgba(255,255,255,0.08)",
          boxShadow: selectedNode
            ? "0 0 0 3px rgba(99,102,241,0.32), 0 10px 26px rgba(0,0,0,0.35)"
            : active
              ? "0 8px 20px rgba(0,0,0,0.28)"
              : "none",
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
        style: {
          ...e.style,
          opacity: active ? 1 : 0.08,
          strokeWidth: active ? 3 : 1,
        },
        labelStyle: {
          ...e.labelStyle,
          opacity: active ? 1 : 0.12,
          fontSize: active ? 11 : 9,
        },
        labelBgStyle: {
          ...e.labelBgStyle,
          fillOpacity: active ? 0.84 : 0.1,
        },
      };
    });
  }, [focus, layoutEdges]);

  // 드래그 가능하도록 상태로 관리 (정적 prop 이면 드래그가 제자리로 튕김)
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState(highlightedNodes);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(highlightedEdges);
  useEffect(() => setRfNodes(highlightedNodes), [highlightedNodes, setRfNodes]);
  useEffect(() => setRfEdges(highlightedEdges), [highlightedEdges, setRfEdges]);

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
      {selected && (
        <NodeInspector
          node={selected}
          hiddenEoas={hiddenEoasByNode.get(selected.id) ?? []}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}
