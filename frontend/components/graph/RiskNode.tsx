"use client";

import { Handle, type Node, type NodeProps, Position } from "@xyflow/react";
import {
  Boxes,
  Cable,
  Coins,
  Layers3,
  Radio,
  type LucideIcon,
} from "lucide-react";

import type { GraphNode, NodeTickState, NodeType } from "@/lib/api";
import { formatUsd } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ProtocolMark } from "./ProtocolMark";
import { brandFromSymbol, brandFromVenue } from "./protocols";

export interface RiskNodeData extends Record<string, unknown> {
  node: GraphNode;
  state: NodeTickState;
  walletHighlight: boolean;
  faded?: boolean; // Phase 4: 포커스 활성 시 비관련 노드를 흐리게
  expanded?: boolean; // 선택된 노드 or 그 1-hop 이웃 — 한 단계 확장 표시
}

export type RiskNodeType = Node<RiskNodeData, "risk">;

const TYPE_META: Record<
  NodeType,
  { icon: LucideIcon; accent: string; label: string }
> = {
  Token: { icon: Coins, accent: "#818cf8", label: "Token" },
  TokenProtocol: { icon: Layers3, accent: "#34d399", label: "Issuer" },
  DefiProtocol: { icon: Boxes, accent: "#60a5fa", label: "DeFi Protocol" },
  Oracle: { icon: Radio, accent: "#fbbf24", label: "Oracle" },
  Bridge: { icon: Cable, accent: "#c084fc", label: "Bridge" },
};

const RISK_CLASS = {
  safe: "node-healthy",
  caution: "node-caution",
  danger: "node-danger",
} as const;

// 노드 크기 등급 (4단계)
//  - large:     oracle, protocol_pool, market_registry, treasury, stability_module — 주요 인프라
//  - medium:    LST/LRT/stable 같은 핵심 토큰 (사람 라벨)
//  - small:     일반 underlying_asset (USDC, WETH 등)
//  - icon-only: 자동 발견된 a_token / variable_debt_token / price_feed — 로고만 표시
type NodeSize = "large" | "medium" | "small" | "icon-only";

function getBaseNodeSize(node: GraphNode): NodeSize {
  const md = (node.metadata ?? {}) as Record<string, unknown>;
  const cat = (md.category as string | undefined) ?? "";
  const discovered = !!md.discovered;
  const protocol = (md.protocol as string | undefined) ?? "";

  // 주요 인프라 = large
  if (
    node.type === "Oracle" ||
    cat === "market_registry" ||
    cat === "protocol_pool" ||
    cat === "protocol_admin" ||
    cat === "treasury" ||
    cat === "stability_module" ||
    cat === "lending" ||
    cat === "restaking" ||
    cat === "chain"
  ) {
    return "large";
  }

  // 자동 발견된 보조 토큰 → icon-only (시각적 노이즈 감소)
  if (discovered && (cat === "a_token" || cat === "variable_debt_token")) return "icon-only";
  if (discovered && (cat === "price_feed" || cat === "price_adapter")) return "icon-only";
  if (cat === "a_token" || cat === "variable_debt_token") return "icon-only";
  // price_feed / price_adapter 도 기본 icon-only
  if (cat === "price_feed" || cat === "price_adapter") return "icon-only";

  // 핵심 토큰 (라벨 있는 LST/LRT/stable/governance)
  if (cat === "lst_token" || cat === "lrt_token" || cat === "stable_token" || cat === "governance_token") return "medium";

  // discovered + protocol=external → underlying_asset 일반 (USDC, WETH 등 사람 라벨)
  if (cat === "underlying_asset") return "small";

  return "medium";
}

// 한 단계 확장 (selected/이웃/highlight)
function expandSize(s: NodeSize): NodeSize {
  if (s === "icon-only") return "small";
  if (s === "small") return "medium";
  if (s === "medium") return "large";
  return "large";
}

const SIZE_STYLE: Record<NodeSize, { width: string; padding: string; titleSize: string; iconBoxSize: string; iconSize: number }> = {
  large:     { width: "w-[220px]", padding: "px-3.5 py-3",  titleSize: "text-[14px]", iconBoxSize: "size-9", iconSize: 18 },
  medium:    { width: "w-[170px]", padding: "px-3 py-2.5",  titleSize: "text-[12px]", iconBoxSize: "size-7", iconSize: 14 },
  small:     { width: "w-[120px]", padding: "px-2 py-1.5",  titleSize: "text-[10px]", iconBoxSize: "size-5", iconSize: 11 },
  "icon-only":{ width: "w-[44px]", padding: "p-1.5",         titleSize: "hidden",      iconBoxSize: "size-7", iconSize: 13 },
};

function RiskNodeComponent({ data, selected }: NodeProps<RiskNodeType>) {
  const { node, state, walletHighlight, faded, expanded } = data;
  const meta = TYPE_META[node.type];
  const Icon = meta.icon;
  const inactive = !node.active;
  // 기본 크기 → expanded 면 한 단계 키움
  const baseSize = getBaseNodeSize(node);
  const size = expanded ? expandSize(baseSize) : baseSize;
  const sz = SIZE_STYLE[size];
  const isIconOnly = size === "icon-only";

  // which protocol does this node belong to? pool venue (lending market) or token issuer.
  const brand =
    brandFromVenue(node.metadata.venue) ??
    (node.type === "Token" ? brandFromSymbol(node.metadata.symbol ?? node.label) : null);

  // collateral issuer (e.g. PT-* market on Morpho whose collateral is from Pendle)
  const collatProto = node.metadata.collateral_protocol;
  const subline = brand
    ? (collatProto && collatProto !== brand.label
        ? `${brand.label} · ${collatProto} 담보`   // e.g. "Morpho Blue · Pendle 담보"
        : brand.label)
    : node.metadata.symbol
      ? node.metadata.symbol
      : node.metadata.category
        ? `${meta.label} · ${node.metadata.category}`
        : meta.label;

  const stat =
    node.type === "Oracle"
      ? state.pegRatio != null
        ? `reports ${state.pegRatio.toFixed(4)}`
        : null
      : state.pegRatio != null
        ? `peg ${state.pegRatio.toFixed(4)}`
        : state.tvl != null
          ? `TVL ${formatUsd(state.tvl)}`
          : null;

  return (
    <div
      className={cn(
        "relative rounded-xl",
        sz.width, sz.padding,
        "transition-[box-shadow,border-color,background-color,transform] duration-300",
        walletHighlight
          ? "bg-[var(--color-surface-raised)]"
          : "bg-[var(--color-surface)]",
        RISK_CLASS[state.riskLevel],
        state.falseNegative && !state.liquidated && "node-false-negative",
        inactive && "opacity-45 grayscale",
        // selected: ring + scale up (큰 노드일수록 적게 키움)
        selected && "ring-2 ring-[var(--color-accent)] ring-offset-2 ring-offset-[var(--color-background)]",
        selected && (size === "small" ? "scale-150" : size === "medium" ? "scale-125" : "scale-110"),
        walletHighlight && !selected && state.riskLevel === "safe" &&
          "ring-1 ring-[var(--color-accent)]/50",
        faded && !walletHighlight && !selected && "opacity-25",
      )}
      style={{ transformOrigin: "center center" }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!size-1.5 !border-0 !bg-transparent"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        className="!size-1.5 !border-0 !bg-transparent"
      />

      {walletHighlight && (
        <div
          className="absolute -right-1 -top-1 size-2.5 rounded-full bg-[var(--color-accent)]"
          style={{ boxShadow: "0 0 6px var(--color-accent)" }}
        />
      )}

      {isIconOnly ? (
        // 아이콘만 모드: 라벨 없이 작은 사각형 + hover/select 시 tooltip 으로 라벨
        <div
          className="flex items-center justify-center"
          title={node.label}
        >
          {brand ? (
            <ProtocolMark brand={brand} boxClass={sz.iconBoxSize} fontPx={sz.iconSize} />
          ) : (
            <div
              className={cn("flex items-center justify-center rounded-md", sz.iconBoxSize)}
              style={{ backgroundColor: `${meta.accent}1f` }}
            >
              <Icon size={sz.iconSize} style={{ color: meta.accent }} />
            </div>
          )}
        </div>
      ) : (
        <div className={cn("flex items-center", size === "small" ? "gap-1.5" : "gap-2.5")}>
          {brand ? (
            <ProtocolMark brand={brand} boxClass={sz.iconBoxSize} fontPx={sz.iconSize} />
          ) : (
            <div
              className={cn("flex shrink-0 items-center justify-center rounded-lg", sz.iconBoxSize)}
              style={{ backgroundColor: `${meta.accent}1f` }}
            >
              <Icon size={sz.iconSize} style={{ color: meta.accent }} />
            </div>
          )}
          <div className="min-w-0">
            <div className={cn("truncate font-semibold leading-tight", sz.titleSize)}>
              {node.label}
            </div>
            {size !== "small" && (
              <div className="truncate text-[11px] leading-tight text-[var(--color-text-muted)]">
                {subline}
              </div>
            )}
          </div>
        </div>
      )}

      {!isIconOnly && (stat || inactive || state.liquidated || state.falseNegative) && (
        <div className="mt-2 flex items-center justify-between gap-2">
          {stat && (
            <span className="truncate font-mono text-[11px] text-[var(--color-text-secondary)]">
              {stat}
            </span>
          )}
          {inactive && (
            <span className="shrink-0 rounded bg-[var(--color-surface-raised)] px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-[var(--color-text-muted)]">
              미존재
            </span>
          )}
          {state.liquidated && (
            <span className="shrink-0 rounded bg-[color:var(--color-danger)]/15 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-[var(--color-danger)]">
              liquidated
            </span>
          )}
          {state.falseNegative && !state.liquidated && !inactive && (
            <span className="shrink-0 rounded bg-[color:var(--color-accent)]/15 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-[var(--color-accent)]">
              false negative
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export const RiskNode = RiskNodeComponent;
