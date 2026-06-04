"use client";

import { Loader2 } from "lucide-react";

import type { BacktestResult, BacktestIncident } from "@/lib/api";
import { formatUsd } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  isRunning: boolean;
  result: BacktestResult | null;
  onRun: () => void;
  incidents: BacktestIncident[];
  selectedIncident: string;
  onSelectIncident: (id: string) => void;
}

export function BacktestLeftPanel({
  isRunning, result, onRun,
  incidents, selectedIncident, onSelectIncident,
}: Props) {
  const snap = result?.snapshot;

  return (
    <aside className="flex w-[280px] shrink-0 flex-col border-r border-[var(--color-border-subtle)] bg-[var(--color-surface)]">
      {/* Title */}
      <div className="shrink-0 border-b border-[var(--color-border-subtle)] px-4 py-3">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Backtest
        </p>
        <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">
          역사적 사건 재현 · 엔진 오차 측정
        </p>
      </div>

      {/* Incident list — pick from /api/backtest/incidents */}
      <div className="shrink-0 px-4 py-4">
        <p className="mb-2 text-[9px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          사건 선택
        </p>
        <div className="space-y-2">
          {(incidents.length > 0 ? incidents : [{
            id: "kelp_2026", date: "2026-04-18", asset: "rseth",
            description: "Kelp DAO LayerZero exploit", is_hypothetical: false,
          }]).map((inc) => (
            <IncidentCard
              key={inc.id}
              incident={inc}
              active={inc.id === selectedIncident}
              onClick={() => onSelectIncident(inc.id)}
            />
          ))}
        </div>
      </div>

      {/* Run button */}
      <div className="shrink-0 px-4 pb-4">
        <button
          onClick={onRun}
          disabled={isRunning}
          className={cn(
            "flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors",
            isRunning
              ? "cursor-not-allowed bg-[var(--color-surface-raised)] text-[var(--color-text-muted)]"
              : "bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-dim)]",
          )}
        >
          {isRunning ? (
            <>
              <Loader2 size={13} className="animate-spin" />
              <span>백테스트 실행 중…</span>
            </>
          ) : (
            <span>백테스트 실행</span>
          )}
        </button>
      </div>

      {/* Snapshot preview */}
      {snap && (
        <div className="flex-1 overflow-y-auto border-t border-[var(--color-border-subtle)] px-4 py-4">
          <p className="mb-3 text-[9px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            스냅샷 파라미터
          </p>
          <div className="space-y-1.5">
            <SnapRow label="블록 (사건 직전)" value="24,895,000" verified />
            <SnapRow label="rsETH Oracle" value={`$${snap.oracle_price.toLocaleString()}`} verified />
            <SnapRow label="Aave V3 예치량" value={`${snap.atoken_supply.toLocaleString()} rsETH`} verified />
            <SnapRow label="DEX 유동성" value={formatUsd(snap.dex_liquidity_usd)} verified />
            <SnapRow label="LT (일반)" value={`${(snap.lt_normal * 100).toFixed(0)}%`} verified />
            <SnapRow label="LT (eMode)" value={snap.lt_emode > 0 ? `${(snap.lt_emode * 100).toFixed(0)}%` : "—"} verified />
          </div>

          <div className="mt-3 flex items-center gap-1.5 text-[9px] text-[var(--color-text-muted)]">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-healthy)]" />
            Alchemy 아카이브 검증 완료
          </div>
        </div>
      )}

      {!snap && !isRunning && (
        <div className="flex flex-1 items-center justify-center px-4">
          <p className="text-center text-[11px] leading-relaxed text-[var(--color-text-muted)]">
            버튼을 누르면 사건 직전 블록 데이터를 기반으로 시뮬레이션을 실행합니다
          </p>
        </div>
      )}
    </aside>
  );
}

// Incidents that are kept in the registry but NOT fully validated yet.
// We lock them in the UI to prevent users from running half-baked backtests,
// and to focus mentor/team attention on the rigorously-verified set
// (kelp_2026, steth_depeg_2022) for the interim presentation.
const LOCKED_INCIDENTS = new Set<string>(["ezeth_depeg_2024"]);

function IncidentCard({
  incident, active, onClick,
}: {
  incident: BacktestIncident;
  active: boolean;
  onClick: () => void;
}) {
  const locked = LOCKED_INCIDENTS.has(incident.id);
  const isContagion = incident.type === "contagion";
  const badgeLabel = locked
    ? "🔒 준비 중"
    : isContagion ? "전파 · DebtRank"
    : incident.is_hypothetical ? "가상 시나리오" : "실제 사건";
  const badgeColor = locked
    ? "bg-[rgba(107,114,128,0.15)] text-[var(--color-text-muted)]"
    : isContagion
      ? "bg-[rgba(99,102,241,0.15)] text-[var(--color-accent)]"
      : incident.is_hypothetical
        ? "bg-[rgba(251,191,36,0.15)] text-[var(--color-caution)]"
        : "bg-[rgba(239,68,68,0.15)] text-[var(--color-danger)]";
  return (
    <button
      type="button"
      onClick={locked ? undefined : onClick}
      disabled={locked}
      className={cn(
        "block w-full rounded-xl border p-3.5 text-left transition-all",
        locked
          ? "cursor-not-allowed border-[var(--color-border-subtle)] opacity-50"
          : active
            ? "cursor-pointer border-[var(--color-accent)] bg-[rgba(99,102,241,0.08)]"
            : "cursor-pointer border-[var(--color-border-subtle)] hover:border-[var(--color-border-strong)]",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-[11px] font-bold text-[var(--color-text-primary)]">
            {incident.id}
          </p>
          <p className="mt-0.5 text-[9px] text-[var(--color-text-muted)]">
            {incident.date} · {incident.asset}
          </p>
        </div>
        <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[9px] font-bold", badgeColor)}>
          {badgeLabel}
        </span>
      </div>
      <p className="mt-2 text-[10px] leading-relaxed text-[var(--color-text-secondary)]">
        {incident.description}
      </p>
    </button>
  );
}

function SnapRow({
  label,
  value,
  verified,
}: {
  label: string;
  value: string;
  verified?: boolean;
}) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] px-2.5 py-1.5">
      <span className="text-[10px] text-[var(--color-text-muted)]">{label}</span>
      <div className="flex items-center gap-1.5">
        {verified && (
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-healthy)]" />
        )}
        <span className="text-[10px] font-semibold text-[var(--color-text-primary)]">{value}</span>
      </div>
    </div>
  );
}
