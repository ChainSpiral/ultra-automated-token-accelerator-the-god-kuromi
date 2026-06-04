"use client";

import { Pause, Play, RotateCcw } from "lucide-react";

import type { SimResult } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  simResult: SimResult | null;
  simRound: number;
  playing: boolean;
  onPlayPause: () => void;
  onRestart: () => void;
  onScrub: (round: number) => void;
}

export function BottomControls({
  simResult,
  simRound,
  playing,
  onPlayPause,
  onRestart,
  onScrub,
}: Props) {
  const totalRounds = simResult?.rounds.length ?? 0;
  const hasResult = simResult != null;
  const isDone = hasResult && simRound >= totalRounds && totalRounds > 0;

  return (
    <div className="flex h-12 shrink-0 items-center gap-3 border-t border-[var(--color-border-subtle)] bg-[var(--color-surface)] px-4">
      {/* Reset */}
      <button
        onClick={onRestart}
        disabled={!hasResult}
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-lg border transition-colors",
          hasResult
            ? "border-[var(--color-border-subtle)] text-[var(--color-text-muted)] hover:border-[var(--color-border-strong)] hover:text-[var(--color-text-primary)]"
            : "border-[var(--color-border-subtle)] text-[var(--color-border-strong)] cursor-not-allowed",
        )}
      >
        <RotateCcw size={13} />
      </button>

      {/* Play / Pause — disabled when mapping is complete (use ↺ to restart) */}
      <button
        onClick={onPlayPause}
        disabled={!hasResult || isDone}
        className={cn(
          "flex h-8 items-center gap-2 rounded-lg px-3 text-sm font-semibold transition-colors",
          !hasResult || isDone
            ? "bg-[var(--color-surface-raised)] text-[var(--color-text-muted)] cursor-not-allowed opacity-50"
            : playing
              ? "bg-[var(--color-surface-raised)] text-[var(--color-text-primary)] border border-[var(--color-border-strong)]"
              : "bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-dim)]",
        )}
      >
        {playing ? <Pause size={13} /> : <Play size={13} />}
        <span className="text-xs">{playing ? "일시정지" : "재생"}</span>
      </button>

      {/* Scrubber */}
      <div className="relative flex flex-1 items-center gap-2">
        <span className="shrink-0 text-[10px] text-[var(--color-text-muted)]">
          {hasResult ? "R0" : "—"}
        </span>
        <input
          type="range"
          min={0}
          max={totalRounds}
          value={simRound}
          disabled={!hasResult}
          onChange={(e) => onScrub(+e.target.value)}
          className={cn("flex-1 transition-opacity", !hasResult && "opacity-30")}
          style={{ accentColor: "var(--color-accent)" }}
        />
        <span className="shrink-0 text-[10px] text-[var(--color-text-muted)]">
          {hasResult ? `R${totalRounds}` : "—"}
        </span>
      </div>

      {/* Round counter */}
      <div className="shrink-0 font-mono text-xs text-[var(--color-text-muted)]">
        {hasResult ? (
          <span>
            <span className="text-[var(--color-text-primary)]">R{simRound}</span>
            {" / "}R{totalRounds}
          </span>
        ) : (
          <span>시뮬레이션 없음</span>
        )}
      </div>

      {/* Summary badge */}
      {simResult && simRound === totalRounds && totalRounds > 0 && (() => {
        const badDebt = simResult.total_bad_debt_usd_calibrated ?? simResult.total_bad_debt_usd;
        const hasCascade = badDebt > 1_000_000;
        return (
          <div
            className="shrink-0 rounded-full px-2.5 py-0.5 text-[10px] font-semibold"
            style={{
              color: hasCascade ? "var(--color-danger)" : "var(--color-caution)",
              backgroundColor: hasCascade ? "rgba(239,68,68,0.12)" : "rgba(251,191,36,0.12)",
              border: `1px solid ${hasCascade ? "rgba(239,68,68,0.3)" : "rgba(251,191,36,0.3)"}`,
            }}
          >
            {simResult.depeg_pct.toFixed(1)}% depeg · {badDebt > 1_000_000 ? `배드뎃 $${(badDebt / 1e6).toFixed(1)}M` : "cascade 없음"}
          </div>
        );
      })()}
    </div>
  );
}
