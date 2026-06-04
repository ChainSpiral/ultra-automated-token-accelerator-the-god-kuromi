"use client";

import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";

import type {
  ContagionScore,
  ExposureCluster,
  GraphEdge,
  GraphNode,
  NodeTickState,
  RiskLevel,
} from "@/lib/api";
import { formatUsd } from "@/lib/api";
import { cn } from "@/lib/utils";

const RISK_META: Record<RiskLevel, { label: string; color: string }> = {
  safe: { label: "Safe", color: "var(--color-healthy)" },
  caution: { label: "Caution", color: "var(--color-caution)" },
  danger: { label: "Danger", color: "var(--color-danger)" },
};

interface Relation {
  edge: GraphEdge;
  otherId: string;
  otherLabel: string;
  direction: "out" | "in";
}

export function SidePanel({
  node,
  state,
  edges,
  nodesById,
  contagion,
  exposure,
  tickNarrative,
  tickDate,
  onClose,
  onSelectNode,
}: {
  node: GraphNode | null;
  state: NodeTickState | null;
  edges: GraphEdge[];
  nodesById: Map<string, GraphNode>;
  contagion: ContagionScore | null;
  exposure: ExposureCluster | null;
  tickNarrative: string | null;
  tickDate: string | null;
  onClose: () => void;
  onSelectNode: (id: string) => void;
}) {
  const relations: Relation[] = node
    ? edges
        .filter((e) => e.source === node.id || e.target === node.id)
        .map((e) => {
          const out = e.source === node.id;
          const otherId = out ? e.target : e.source;
          return {
            edge: e,
            otherId,
            otherLabel: nodesById.get(otherId)?.label ?? otherId,
            direction: out ? ("out" as const) : ("in" as const),
          };
        })
    : [];

  const risk = state ? RISK_META[state.riskLevel] : RISK_META.safe;

  return (
    <AnimatePresence>
      {node && state && (
        <motion.aside
          key={node.id}
          initial={{ x: 400, opacity: 0.4 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 400, opacity: 0 }}
          transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
          className="absolute right-0 top-0 z-20 flex h-full w-[360px] flex-col border-l border-[var(--color-border-subtle)] bg-[var(--color-surface)]"
        >
          <div className="flex items-start justify-between border-b border-[var(--color-border-subtle)] px-5 py-4">
            <div>
              <h2 className="text-base font-semibold">{node.label}</h2>
              <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                {node.type}
                {node.metadata.chain ? ` · ${node.metadata.chain}` : ""}
                {node.metadata.category ? ` · ${node.metadata.category}` : ""}
              </p>
            </div>
            <button
              onClick={onClose}
              className="rounded-md p-1 text-[var(--color-text-muted)] transition-colors hover:bg-[var(--color-surface-raised)] hover:text-[var(--color-text-primary)]"
            >
              <X size={16} />
            </button>
          </div>

          <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
            <section>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                Current state
              </h3>
              <div className="flex flex-wrap items-center gap-2">
                <span className="flex items-center gap-1.5">
                  <span
                    className="inline-block size-2.5 rounded-full"
                    style={{ backgroundColor: risk.color }}
                  />
                  <span className="text-sm font-medium" style={{ color: risk.color }}>
                    {risk.label}
                  </span>
                </span>
                {state.liquidated && (
                  <span className="rounded bg-[color:var(--color-danger)]/15 px-1.5 py-0.5 text-[10px] font-medium uppercase text-[var(--color-danger)]">
                    liquidated
                  </span>
                )}
              </div>
              {state.note && (
                <p className="mt-2 rounded-lg bg-[var(--color-surface-raised)] px-3 py-2 font-mono text-[11px] leading-relaxed text-[var(--color-text-secondary)]">
                  {state.note}
                </p>
              )}
              <dl className="mt-3 space-y-1.5 text-sm">
                {state.tvl != null && <Row label="TVL" value={formatUsd(state.tvl)} />}
                {state.pegRatio != null && (
                  <Row
                    label={node.type === "Oracle" ? "Reports" : "Peg ratio"}
                    value={state.pegRatio.toFixed(4)}
                  />
                )}
              </dl>
            </section>

            {contagion && (
              <section>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                  Systemic impact
                </h3>
                <p className="mb-2.5 text-[13px] leading-relaxed text-[var(--color-text-secondary)]">
                  이 노드가 무너지면 시스템 TVL의{" "}
                  <span className="font-mono font-semibold text-[var(--color-text-primary)]">
                    {(contagion.impactScore * 100).toFixed(1)}%
                  </span>
                  가 위험에 노출됩니다.
                </p>
                <dl className="space-y-1.5 text-sm">
                  <Row label="Impact" value={`${(contagion.impactScore * 100).toFixed(1)}%`} />
                  <Row label="영향 노드" value={`${contagion.downstreamCount}개`} />
                  <Row label="TVL at risk" value={formatUsd(contagion.tvlAtRiskUsd)} />
                </dl>
              </section>
            )}

            {tickNarrative && (
              <section>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                  이 라운드{tickDate ? ` · ${tickDate}` : ""}
                </h3>
                <p className="rounded-lg bg-[var(--color-surface-raised)] px-3 py-2.5 text-[13px] leading-relaxed text-[var(--color-text-secondary)]">
                  {tickNarrative}
                </p>
              </section>
            )}

            {node.metadata.description && (
              <section>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                  About
                </h3>
                <p className="text-[13px] leading-relaxed text-[var(--color-text-secondary)]">
                  {node.metadata.description}
                </p>
              </section>
            )}

            {exposure && exposure.members.length > 0 && (
              <section>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                  Common exposure
                </h3>
                <ul className="space-y-1">
                  {exposure.members.map((m) => (
                    <li key={m.nodeId}>
                      <button
                        onClick={() => onSelectNode(m.nodeId)}
                        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors hover:bg-[var(--color-surface-raised)]"
                      >
                        <span className="truncate">{m.label}</span>
                        {m.amountUSD != null && (
                          <span className="ml-auto shrink-0 font-mono text-[10px] text-[var(--color-text-secondary)]">
                            {formatUsd(m.amountUSD)}
                          </span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
                Dependencies ({relations.length})
              </h3>
              <ul className="space-y-1">
                {relations.map((r) => (
                  <li key={r.edge.id}>
                    <button
                      onClick={() => onSelectNode(r.otherId)}
                      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors hover:bg-[var(--color-surface-raised)]"
                    >
                      <span
                        className={cn(
                          "shrink-0 font-mono text-[10px]",
                          r.direction === "out"
                            ? "text-[var(--color-accent)]"
                            : "text-[var(--color-text-muted)]",
                        )}
                      >
                        {r.direction === "out" ? "→" : "←"}
                      </span>
                      <span className="truncate">{r.otherLabel}</span>
                      <span className="ml-auto shrink-0 font-mono text-[10px] text-[var(--color-text-muted)]">
                        {r.edge.type}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-[var(--color-text-muted)]">{label}</dt>
      <dd className="font-mono">{value}</dd>
    </div>
  );
}
