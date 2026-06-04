"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { SiteHeader } from "@/components/SiteHeader";
import { GraphCanvas } from "@/components/graph/GraphCanvas";
import {
  type BacktestIncident,
  type ContagionResult,
  type NodeTickState,
  type TopologyResponse,
  fetchBacktestIncidents,
  fetchContagion,
} from "@/lib/api";
import { BottomControls } from "@/components/simulation/BottomControls";
import { BacktestLeftPanel } from "./BacktestLeftPanel";
import { ContagionResultPanel } from "./ContagionResultPanel";

const TARGET_TOTAL_MS = 3000;
const MIN_INTERVAL_MS = 400;
const MAX_INTERVAL_MS = 1200;
const EMPTY_TOPOLOGY: TopologyResponse = { nodes: [], edges: [] };

function roundIntervalMs(n: number): number {
  if (n <= 0) return MAX_INTERVAL_MS;
  return Math.min(MAX_INTERVAL_MS, Math.max(MIN_INTERVAL_MS, Math.round(TARGET_TOTAL_MS / n)));
}

export function BacktestPage() {
  const [contagion, setContagion]   = useState<ContagionResult | null>(null);
  const [simRound, setSimRound]     = useState(0);
  const [playing, setPlaying]       = useState(false);
  const [isRunning, setIsRunning]   = useState(false);
  const [resultOpen, setResultOpen] = useState(false);   // panel shows after a run
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const [incidents, setIncidents]               = useState<BacktestIncident[]>([]);
  const [selectedIncident, setSelectedIncident] = useState<string>("");

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load incident list, default-select the first one.
  useEffect(() => {
    fetchBacktestIncidents()
      .then((r) => {
        setIncidents(r.incidents);
        if (r.incidents.length > 0) setSelectedIncident((cur) => cur || r.incidents[0].id);
      })
      .catch(() => {/* ignore */});
  }, []);

  // When the selected incident changes, load its HISTORICAL graph (static, round 0).
  // This is what makes the backtest page show a past graph instead of the live mapping.
  useEffect(() => {
    if (!selectedIncident) return;
    if (timerRef.current) clearInterval(timerRef.current);
    let cancelled = false;
    setIsRunning(true);
    setPlaying(false);
    setResultOpen(false);
    setSimRound(0);
    fetchContagion(selectedIncident, "solvency")
      .then((r) => { if (!cancelled) { setContagion(r); setSimRound(0); } })
      .catch(() => { if (!cancelled) setContagion(null); })
      .finally(() => { if (!cancelled) setIsRunning(false); });
    return () => { cancelled = true; };
  }, [selectedIncident]);

  const roundCount = contagion ? contagion.render.n_rounds : 0;
  const topology: TopologyResponse = contagion ? contagion.render.topology : EMPTY_TOPOLOGY;

  const nodeStates: Record<string, NodeTickState> = contagion
    ? (contagion.render.node_states_by_round[Math.min(simRound, roundCount - 1)] ?? {})
    : {};

  const simResult = contagion
    ? {
        rounds: new Array(roundCount).fill({}),
        depeg_pct: contagion.event.delta * 100,
        total_bad_debt_usd: contagion.ground_truth?.aave_bad_debt_usd
          ?? contagion.ground_truth?.solvency_loss_total_usd ?? 0,
        total_bad_debt_usd_calibrated: null,
      }
    : null;

  // Playback
  useEffect(() => {
    if (!playing || roundCount <= 0) return;
    const interval = roundIntervalMs(roundCount);
    timerRef.current = setInterval(() => {
      setSimRound((r) => {
        const next = r + 1;
        if (next >= roundCount) { setPlaying(false); return roundCount - 1; }
        return next;
      });
    }, interval);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [playing, roundCount]);

  const handleRun = useCallback(() => {
    if (!contagion) return;
    if (timerRef.current) clearInterval(timerRef.current);
    setResultOpen(true);
    setSimRound(0);
    setPlaying(true);
  }, [contagion]);

  const handlePlayPause = useCallback(() => setPlaying((p) => !p), []);
  const handleRestart   = useCallback(() => { setPlaying(false); setSimRound(0); }, []);
  const handleScrub     = useCallback((r: number) => { setPlaying(false); setSimRound(r); }, []);

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <SiteHeader />

      <div className="flex flex-1 overflow-hidden">
        <BacktestLeftPanel
          isRunning={isRunning}
          result={null}
          onRun={handleRun}
          incidents={incidents}
          selectedIncident={selectedIncident}
          onSelectIncident={setSelectedIncident}
        />

        {/* Center graph — the HISTORICAL incident graph */}
        <div className="relative flex-1 overflow-hidden">
          {/* React key forces a remount when the historical graph finishes loading or
              the incident changes — GraphCanvas initializes its nodes from `topology`
              only at mount, so we must remount once the async topology is populated. */}
          <GraphCanvas
            key={contagion ? contagion.incident_id : "empty"}
            graphKey={`contagion-${selectedIncident}`}
            topology={topology}
            nodeStates={nodeStates}
            walletHighlightIds={new Set()}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            cameraFollow
          />

          {resultOpen && <ContagionResultPanel data={contagion} />}

          {/* Hint */}
          {contagion && !resultOpen && !isRunning && (
            <div className="pointer-events-none absolute inset-x-0 bottom-6 z-10 flex justify-center">
              <span className="rounded-full border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] px-4 py-1.5 text-xs text-[var(--color-text-secondary)] shadow-lg">
                과거 사건 그래프 — 실행을 누르면 전파가 재생됩니다
              </span>
            </div>
          )}

          {/* Loading */}
          {isRunning && (
            <div className="absolute inset-0 z-30 flex items-center justify-center bg-[var(--color-background)]/60 backdrop-blur-sm">
              <div className="flex flex-col items-center gap-3">
                <div className="size-8 animate-spin rounded-full border-2 border-[var(--color-border-strong)] border-t-[var(--color-accent)]" />
                <span className="text-sm text-[var(--color-text-secondary)]">
                  {selectedIncident} 과거 그래프 로드 중…
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      <BottomControls
        simResult={simResult as any}
        simRound={simRound}
        playing={playing}
        onPlayPause={handlePlayPause}
        onRestart={handleRestart}
        onScrub={handleScrub}
      />
    </div>
  );
}
