"use client";

import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle, ChevronLeft, ChevronRight, Loader2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type {
  FocusResult,
  FocusSuggestion,
  NodeTickState,
  PortfolioSimulateResult,
  SimResult,
  WalletPortfolio,
  WalletPosition,
} from "@/lib/api";
import {
  fetchFocus,
  fetchFocusSuggestions,
  fetchPortfolioSimulate,
  fetchWalletPortfolio,
  fetchWalletPosition,
  formatUsd,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  simResult: SimResult | null;
  simRound: number;
  nodeStates: Record<string, NodeTickState>;
  onHighlightChange: (ids: Set<string>) => void;
  onFocusChange?: (result: FocusResult | null, loading: boolean, error: string | null) => void;
  rightOffset?: number;
}

const ZONE_COLOR: Record<string, string> = {
  safe:        "var(--color-healthy)",
  warning:     "var(--color-caution)",
  critical:    "var(--color-danger)",
  liquidatable:"#a855f7",
};
const ZONE_LABEL: Record<string, string> = {
  safe:        "안전",
  warning:     "주의",
  critical:    "위험",
  liquidatable:"청산 임박",
};

export function WalletPanel({ simResult, simRound, nodeStates, onHighlightChange, onFocusChange, rightOffset = 12 }: Props) {
  const [open, setOpen] = useState(true);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [position, setPosition] = useState<WalletPosition | null>(null);
  const [portfolio, setPortfolio] = useState<WalletPortfolio | null>(null);
  const [portfolioSim, setPortfolioSim] = useState<PortfolioSimulateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState(false);

  const address = position?.address ?? null;

  // 입력 종류 자동 감지: 0x...40자 = address (지갑 모드 + 포커스),
  // 0x...64자 = tx (포커스만),
  // 그 외 = token (포커스만)
  function detectKind(s: string): "address" | "tx" | "token" | "empty" {
    const t = s.trim();
    if (!t) return "empty";
    if (/^0x[0-9a-fA-F]{64}$/.test(t)) return "tx";
    if (/^0x[0-9a-fA-F]{40}$/.test(t)) return "address";
    return "token";
  }

  async function runFocus(query: string) {
    if (!onFocusChange) return;
    onFocusChange(null, true, null);
    try {
      const result = await fetchFocus(query);
      onFocusChange(result, false, null);
      // 그래프 하이라이트: center + related
      const ids = new Set<string>([
        ...(result.center_node_ids ?? []),
        ...(result.related_node_ids ?? []),
      ]);
      if (ids.size > 0) {
        onHighlightChange(ids);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "포커스 조회 실패";
      onFocusChange(null, false, msg);
    }
  }

  async function handleLookup(query: string) {
    const trimmed = query.trim();
    if (!trimmed) return;
    const kind = detectKind(trimmed);

    // 모든 입력에 대해 focus 조회 (그래프 하이라이트 + 결과 패널)
    runFocus(trimmed);

    // 지갑 주소면 기존 포지션/포트폴리오도 함께
    if (kind !== "address") {
      // 지갑 분석 결과는 비워둠
      setPosition(null);
      setPortfolio(null);
      setPortfolioSim(null);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);
    setPosition(null);
    setPortfolio(null);
    setPortfolioSim(null);
    try {
      const [pos, port, sim] = await Promise.all([
        fetchWalletPosition(trimmed),
        fetchWalletPortfolio(trimmed).catch(() => null),
        fetchPortfolioSimulate(trimmed).catch(() => null),
      ]);
      setPosition(pos);
      setPortfolio(port);
      setPortfolioSim(sim);
      // 포트폴리오에서 추가 노드 발견되면 하이라이트에 합침
      if (port?.exposed_graph_nodes && port.exposed_graph_nodes.length > 0) {
        onHighlightChange(new Set(port.exposed_graph_nodes));
      }
      setFlash(true);
      setTimeout(() => setFlash(false), 600);
    } catch {
      setError("지갑 포지션 조회 실패. (포커스 결과는 우측에서 확인 가능)");
    } finally {
      setLoading(false);
    }
  }

  function handleClear() {
    setInput("");
    setPosition(null);
    setPortfolio(null);
    setPortfolioSim(null);
    setError(null);
    onHighlightChange(new Set());
    if (onFocusChange) onFocusChange(null, false, null);
  }

  const currentKind = detectKind(input);

  // 자동완성 (토큰 모드일 때만)
  const [suggestions, setSuggestions] = useState<FocusSuggestion[]>([]);
  const [showSuggest, setShowSuggest] = useState(false);
  const suggestTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (currentKind !== "token") {
      setSuggestions([]);
      return;
    }
    if (suggestTimerRef.current) clearTimeout(suggestTimerRef.current);
    suggestTimerRef.current = setTimeout(() => {
      fetchFocusSuggestions(input, 6)
        .then((r) => setSuggestions(r.suggestions))
        .catch(() => setSuggestions([]));
    }, 150);
    return () => {
      if (suggestTimerRef.current) clearTimeout(suggestTimerRef.current);
    };
  }, [input, currentKind]);

  function selectSuggestion(s: FocusSuggestion) {
    const q = s.symbol || s.label || s.id;
    setInput(q);
    setShowSuggest(false);
    handleLookup(q);
  }

  // Compute affected wallet nodes from simulation
  const affectedWalletNodes = (() => {
    if (!simResult || !portfolio) return [];
    const walletNodes = new Set(portfolio.exposed_graph_nodes);
    const affectedInSim = new Set<string>();
    for (let i = 0; i < simRound && i < simResult.rounds.length; i++) {
      for (const nodeId of simResult.rounds[i].affected_nodes) {
        if (walletNodes.has(nodeId)) affectedInSim.add(nodeId);
      }
    }
    return Array.from(affectedInSim).map((id) => ({
      id,
      state: nodeStates[id],
    }));
  })();

  return (
    <div
      className="pointer-events-none absolute top-3 z-20 flex flex-col gap-2"
      style={{ right: rightOffset, width: open ? 276 : 36, transition: "width 0.2s, right 0.3s cubic-bezier(0.16,1,0.3,1)" }}
    >
      <div
        className="pointer-events-auto overflow-hidden rounded-xl border border-[var(--color-border-subtle)] shadow-2xl"
        style={{ backdropFilter: "blur(12px)", backgroundColor: "rgba(19,19,22,0.88)" }}
      >
        {/* Header */}
        <div className="flex items-center gap-2 border-b border-[var(--color-border-subtle)] px-3 py-2">
          {open && (
            <>
              <span className="text-[9px] font-bold uppercase tracking-widest text-[var(--color-text-muted)]">
                검색
              </span>
              <div
                className={cn(
                  "flex flex-1 items-center overflow-hidden rounded border transition-colors",
                  flash ? "border-[var(--color-accent)]" : address ? "border-[var(--color-accent)]/50" : "border-[var(--color-border-subtle)]",
                )}
                style={{ backgroundColor: "rgba(10,10,11,0.6)" }}
              >
                <input
                  value={input}
                  onChange={(e) => { setInput(e.target.value); setShowSuggest(true); }}
                  onFocus={() => setShowSuggest(true)}
                  onBlur={() => setTimeout(() => setShowSuggest(false), 150)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") { setShowSuggest(false); handleLookup(input); }
                    if (e.key === "Escape") setShowSuggest(false);
                  }}
                  placeholder="지갑·토큰·tx"
                  className="flex-1 bg-transparent px-2 py-1 font-mono text-[10px] outline-none placeholder:text-[var(--color-text-muted)]"
                />
                {input && (
                  <span className="shrink-0 mr-1 rounded bg-[var(--color-surface-raised)] px-1 py-px text-[8px] uppercase text-[var(--color-text-muted)]">
                    {currentKind === "address" ? "지갑" : currentKind === "tx" ? "트랜잭션" : currentKind === "token" ? "토큰" : ""}
                  </span>
                )}
                {input && !loading && (
                  <button
                    onClick={() => handleLookup(input)}
                    className="shrink-0 px-2 py-1 text-[9px] font-semibold text-[var(--color-accent)] hover:text-white transition-colors"
                  >
                    분석
                  </button>
                )}
                {loading && <Loader2 size={11} className="mx-2 animate-spin text-[var(--color-text-muted)]" />}
                {address && !loading && (
                  <button onClick={handleClear} className="px-1.5 text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]">
                    <X size={11} />
                  </button>
                )}
              </div>
            </>
          )}
          <button
            onClick={() => setOpen((v) => !v)}
            className="ml-auto shrink-0 text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors"
          >
            {open ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
          </button>
        </div>

        {/* Autocomplete dropdown (Phase 4 — 토큰 모드만) */}
        {open && showSuggest && currentKind === "token" && suggestions.length > 0 && (
          <div
            className="border-b border-[var(--color-border-subtle)] max-h-[180px] overflow-y-auto"
            style={{ backgroundColor: "rgba(15,15,18,0.95)" }}
          >
            {suggestions.map((s) => (
              <button
                key={s.id}
                onMouseDown={(e) => { e.preventDefault(); selectSuggestion(s); }}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[10px] hover:bg-[var(--color-surface-raised)] transition-colors"
              >
                <span className="text-[var(--color-text-primary)]">{s.symbol || s.label}</span>
                <span className="text-[var(--color-text-muted)] truncate flex-1">{s.label}</span>
                {s.category && (
                  <span className="rounded bg-[var(--color-surface-raised)] px-1 py-px text-[8px] uppercase text-[var(--color-text-muted)]">
                    {s.category}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}

        {/* Body */}
        <AnimatePresence>
          {open && (
            <motion.div
              initial={{ height: 0 }}
              animate={{ height: "auto" }}
              exit={{ height: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="max-h-[60vh] overflow-y-auto">
                {error && (
                  <div className="px-3 py-2.5 text-[11px] text-[var(--color-danger)]">{error}</div>
                )}

                {!address && !loading && !error && (
                  <div className="px-3 py-4 text-center text-[11px] leading-relaxed text-[var(--color-text-muted)]">
                    지갑 주소 · 토큰 심볼 · tx 해시 중<br />
                    무엇이든 입력하면 그래프에서 강조됩니다
                  </div>
                )}

                {loading && (
                  <div className="flex items-center justify-center gap-2 px-3 py-4 text-[11px] text-[var(--color-text-muted)]">
                    <Loader2 size={13} className="animate-spin" />
                    조회 중…
                  </div>
                )}

                {position && !loading && (
                  <div className="px-3 py-2.5 space-y-3">
                    {/* Position summary */}
                    {position.has_position ? (
                      <div>
                        <div className="mb-1.5 flex items-center gap-1.5">
                          <span
                            className="rounded px-1.5 py-0.5 text-[9px] font-bold uppercase"
                            style={{
                              color: ZONE_COLOR[position.zone ?? "safe"],
                              backgroundColor: `${ZONE_COLOR[position.zone ?? "safe"]}15`,
                            }}
                          >
                            {ZONE_LABEL[position.zone ?? "safe"]}
                          </span>
                          <span className="text-[10px] text-[var(--color-text-muted)]">Aave V3 포지션</span>
                        </div>
                        <dl className="space-y-1 text-[11px]">
                          {position.total_collateral_usd != null && (
                            <StatRow label="담보" value={formatUsd(position.total_collateral_usd)} />
                          )}
                          {position.total_debt_usd != null && (
                            <StatRow label="부채" value={formatUsd(position.total_debt_usd)} />
                          )}
                          {position.health_factor != null && (
                            <StatRow
                              label="Health Factor"
                              value={position.health_factor.toFixed(3)}
                              valueColor={
                                position.health_factor < 1.05
                                  ? "var(--color-danger)"
                                  : position.health_factor < 1.2
                                    ? "var(--color-caution)"
                                    : "var(--color-healthy)"
                              }
                            />
                          )}
                          {position.liq_oracle_price != null && (
                            <StatRow
                              label="청산 가격"
                              value={`$${position.liq_oracle_price.toLocaleString()}`}
                            />
                          )}
                        </dl>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1.5 text-[11px] text-[var(--color-text-muted)]">
                        <CheckCircle size={12} className="text-[var(--color-healthy)]" />
                        rsETH 포지션 없음
                      </div>
                    )}

                    {/* Portfolio holdings */}
                    {portfolio && portfolio.holdings.length > 0 && (
                      <div>
                        <div className="mb-1.5 text-[9px] font-bold uppercase tracking-wider text-[var(--color-text-muted)]">
                          LST/LRT 보유 ({formatUsd(portfolio.total_lst_lrt_usd)})
                        </div>
                        <div className="space-y-1">
                          {portfolio.holdings.map((h) => (
                            <div
                              key={`${h.symbol}-${h.source}`}
                              className="flex items-center justify-between rounded px-2 py-1 text-[10px]"
                              style={{ backgroundColor: "rgba(255,255,255,0.03)" }}
                            >
                              <span className="font-semibold text-[var(--color-text-primary)]">{h.symbol}</span>
                              <span className="font-mono text-[var(--color-text-muted)]">{formatUsd(h.value_usd)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Multi-asset portfolio simulation (Aave V3 HF per scenario) */}
                    {portfolioSim?.has_simulatable_position && portfolioSim.scenarios && portfolioSim.scenarios.length > 0 && (
                      <div>
                        <div className="mb-1.5 text-[9px] font-bold uppercase tracking-wider text-[var(--color-text-muted)]">
                          시나리오별 Health Factor — {portfolioSim.primary_asset} ({portfolioSim.primary_family?.toUpperCase()})
                        </div>
                        {portfolioSim.aave_account && (
                          <div className="mb-1.5 flex items-center justify-between rounded px-2 py-1 text-[10px]"
                            style={{ backgroundColor: "rgba(255,255,255,0.04)" }}>
                            <span className="text-[var(--color-text-muted)]">현재 HF (live)</span>
                            <span className="font-mono font-bold text-[var(--color-text-primary)]">
                              {portfolioSim.aave_account.live_hf?.toFixed(3) ?? "—"}
                            </span>
                          </div>
                        )}
                        <div className="space-y-1">
                          {portfolioSim.scenarios.map((s) => {
                            const color = s.liquidated
                              ? "var(--color-danger)"
                              : (s.new_hf ?? 99) < 1.2
                                ? "var(--color-caution)"
                                : "var(--color-healthy)";
                            return (
                              <div
                                key={s.scenario}
                                className="flex items-center justify-between rounded px-2 py-1 text-[10px]"
                                style={{ backgroundColor: `${color}10` }}
                              >
                                <div className="flex flex-col">
                                  <span className="font-semibold text-[var(--color-text-primary)]">{s.display_name}</span>
                                  {s.delta_hf != null && (
                                    <span className="text-[9px] text-[var(--color-text-muted)]">
                                      ΔHF {s.delta_hf > 0 ? "+" : ""}{s.delta_hf.toFixed(3)}
                                    </span>
                                  )}
                                </div>
                                <div className="flex flex-col items-end">
                                  <span className="font-mono font-bold" style={{ color }}>
                                    {s.new_hf?.toFixed(3) ?? "—"}
                                  </span>
                                  {s.liquidated && (
                                    <span className="text-[8px] font-bold uppercase text-[var(--color-danger)]">
                                      LIQUIDATED
                                    </span>
                                  )}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                        {portfolioSim.data_quality && (
                          <details className="mt-2">
                            <summary className="cursor-pointer text-[9px] text-[var(--color-text-muted)]">
                              근사치 한계 (3건)
                            </summary>
                            <div className="mt-1 space-y-1 text-[9px] leading-relaxed text-[var(--color-text-muted)]">
                              {Object.values(portfolioSim.data_quality).map((note, i) => (
                                <p key={i}>• {note}</p>
                              ))}
                            </div>
                          </details>
                        )}
                      </div>
                    )}

                    {/* Simulation impact on wallet */}
                    {simResult && simRound > 0 && affectedWalletNodes.length > 0 && (
                      <div>
                        <div className="mb-1.5 flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-wider text-[var(--color-danger)]">
                          <AlertTriangle size={10} />
                          시뮬레이션 영향 ({affectedWalletNodes.length}개 노드)
                        </div>
                        <div className="space-y-1">
                          {affectedWalletNodes.map(({ id, state }) => (
                            <div
                              key={id}
                              className="flex items-center justify-between rounded px-2 py-1 text-[10px]"
                              style={{
                                backgroundColor: state?.riskLevel === "danger"
                                  ? "rgba(239,68,68,0.08)"
                                  : "rgba(251,191,36,0.08)",
                              }}
                            >
                              <span className="font-mono text-[var(--color-text-secondary)]">{id}</span>
                              <span
                                className="text-[9px] font-bold uppercase"
                                style={{
                                  color: state?.riskLevel === "danger"
                                    ? "var(--color-danger)"
                                    : "var(--color-caution)",
                                }}
                              >
                                {state?.liquidated ? "LIQUIDATED" : state?.riskLevel?.toUpperCase() ?? "AFFECTED"}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {simResult && simRound > 0 && affectedWalletNodes.length === 0 && portfolio && (
                      <div className="flex items-center gap-1.5 rounded-md px-2.5 py-2 text-[10px]"
                        style={{ backgroundColor: "rgba(16,185,129,0.08)", color: "var(--color-healthy)" }}>
                        <CheckCircle size={12} />
                        R{simRound}까지 내 포지션에 직접 영향 없음
                      </div>
                    )}
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function StatRow({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-[var(--color-text-muted)]">{label}</dt>
      <dd className="font-mono" style={{ color: valueColor ?? "var(--color-text-secondary)" }}>{value}</dd>
    </div>
  );
}
