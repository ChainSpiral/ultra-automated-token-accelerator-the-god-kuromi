"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { SiteHeader } from "@/components/SiteHeader";
import { GraphCanvas } from "@/components/graph/GraphCanvas";
import { SidePanel } from "@/components/graph/SidePanel";
import {
  type FocusResult,
  type NodeTickState,
  type TopologyResponse,
  type ContagionResult,
  type ShockableAsset,
  SAFE_NODE_STATE,
  fetchLiveShockableAssets,
  fetchShockableOracles,
  fetchRunnableAssets,
  fetchLiveContagion,
} from "@/lib/api";
import { FocusResultPanel } from "./FocusResultPanel";
import { WalletPanel } from "./WalletPanel";
import { ContagionControlPanel, type ContagionControls } from "./ContagionControlPanel";
import { ContagionResultPanel } from "@/components/backtest/ContagionResultPanel";

const TARGET_TOTAL_MS = 3000;
const MIN_INTERVAL_MS = 400;
const MAX_INTERVAL_MS = 1200;

function roundIntervalMs(numRounds: number): number {
  if (numRounds <= 0) return MAX_INTERVAL_MS;
  return Math.min(MAX_INTERVAL_MS, Math.max(MIN_INTERVAL_MS, Math.round(TARGET_TOTAL_MS / numRounds)));
}

interface Props {
  topology: TopologyResponse;
}

export function SimulationPage({ topology }: Props) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [walletHighlightIds, setWalletHighlightIds] = useState<Set<string>>(new Set());

  // Focus search (token/address/tx lookup on the full map)
  const [focusResult, setFocusResult] = useState<FocusResult | null>(null);
  const [focusLoading, setFocusLoading] = useState(false);
  const [focusError, setFocusError] = useState<string | null>(null);
  const [focusZoomActive, setFocusZoomActive] = useState(false);
  const handleFocusChange = useCallback((r: FocusResult | null, l: boolean, e: string | null) => {
    setFocusResult(r);
    setFocusLoading(l);
    setFocusError(e);
    if (l) setFocusZoomActive(false);
  }, []);

  const focusOnlyIds = useMemo(() => {
    if (!focusZoomActive || !focusResult) return null;
    const ids = new Set<string>([
      ...(focusResult.center_node_ids ?? []),
      ...(focusResult.related_node_ids ?? []),
    ]);
    return ids.size > 0 ? ids : null;
  }, [focusZoomActive, focusResult]);

  const nodesById = useMemo(
    () => new Map(topology.nodes.map((n) => [n.id, n])),
    [topology],
  );
  const selectedNode = selectedNodeId ? nodesById.get(selectedNodeId) ?? null : null;
  const selectedState = selectedNodeId ? SAFE_NODE_STATE : null;

  const SIDE_PANEL_W = 360;
  const walletRight = selectedNodeId ? SIDE_PANEL_W + 12 : 12;

  // ── Live contagion (what-if): shock any asset by δ on CURRENT state, run DebtRank ──
  const [cgAssets, setCgAssets]   = useState<ShockableAsset[]>([]);
  const [cgOracles, setCgOracles] = useState<ShockableAsset[]>([]);
  const [cgRunnable, setCgRunnable] = useState<ShockableAsset[]>([]);
  // search target: collateral TOKENS vs shared ORACLES (separate, easier-to-search lists)
  const [searchKind, setSearchKind] = useState<"token" | "oracle">("token");
  const [controls, setControls]   = useState<ContagionControls>({
    asset: "", delta: 0.4, channel: "depeg", naive: false, includeDiscovered: false,
    morpho: true, aave: true, spark: true, skycdp: true,
    recovery: 1.0, recoveryAuto: true, downstream: true,
    freeze: "",
  });
  const patchControls = useCallback(
    (p: Partial<ContagionControls>) => setControls((c) => ({ ...c, ...p })), []);
  const [cgRunning, setCgRunning] = useState(false);
  const [contagion, setContagion] = useState<ContagionResult | null>(null);
  const [cgRound, setCgRound]     = useState(0);
  const [cgPlaying, setCgPlaying] = useState(false);
  const cgTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    fetchLiveShockableAssets()
      .then((r) => {
        setCgAssets(r.assets);
        if (r.assets[0]) setControls((c) => (c.asset ? c : { ...c, asset: r.assets[0].symbol }));
      })
      .catch(() => {/* ignore */});
    fetchShockableOracles().then((r) => setCgOracles(r.assets)).catch(() => {/* ignore */});
    fetchRunnableAssets().then((r) => setCgRunnable(r.assets)).catch(() => {/* ignore */});
  }, []);

  // asset list depends on search target + channel:
  //  - oracle search → shared oracles (common-mode)
  //  - liquidity channel → SUPPLIED (loan) assets; else collateral tokens.
  const panelAssets = searchKind === "oracle"
    ? cgOracles
    : controls.channel === "liquidity" ? cgRunnable : cgAssets;
  // when switching search target / channel, snap the selected asset to a valid one.
  useEffect(() => {
    if (panelAssets.length === 0) return;
    if (!panelAssets.some((a) => a.symbol === controls.asset)) {
      setControls((c) => ({ ...c, asset: panelAssets[0].symbol }));
    }
  }, [searchKind, controls.channel, panelAssets, controls.asset]);

  const cgRoundCount = contagion ? contagion.render.n_rounds : 0;
  const cgNodeStates: Record<string, NodeTickState> = contagion
    ? (contagion.render.node_states_by_round[Math.min(cgRound, cgRoundCount - 1)] ?? {})
    : {};

  useEffect(() => {
    if (!cgPlaying || cgRoundCount <= 0) return;
    const iv = roundIntervalMs(cgRoundCount);
    cgTimer.current = setInterval(() => {
      setCgRound((r) => { const n = r + 1; if (n >= cgRoundCount) { setCgPlaying(false); return cgRoundCount - 1; } return n; });
    }, iv);
    return () => { if (cgTimer.current) clearInterval(cgTimer.current); };
  }, [cgPlaying, cgRoundCount]);

  const runContagion = useCallback(async () => {
    if (!controls.asset || (!controls.morpho && !controls.aave && !controls.spark && !controls.skycdp)) return;
    setCgRunning(true);
    try {
      const venues: ("morpho" | "aave" | "spark" | "skycdp")[] = [];
      if (controls.morpho) venues.push("morpho");
      if (controls.aave) venues.push("aave");
      if (controls.spark) venues.push("spark");
      if (controls.skycdp) venues.push("skycdp");
      const r = await fetchLiveContagion(controls.asset, controls.delta, {
        venues, downstream: controls.downstream,
        // omit recovery when auto → backend derives it per-asset
        recovery: controls.recoveryAuto ? undefined : controls.recovery,
        channel: controls.channel, naive: controls.naive,
        includeDiscovered: controls.includeDiscovered, freeze: controls.freeze,
      });
      setContagion(r);
      setCgRound(0);
      setCgPlaying(true);
    } catch (e) {
      alert(`전염 시뮬레이션 실패: ${e instanceof Error ? e.message : "오류"}`);
    } finally {
      setCgRunning(false);
    }
  }, [controls]);

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <SiteHeader />

      <div className="flex flex-1 overflow-hidden">
        {/* Left panel — contagion controls (Layer1 shock + Layer2 model levers) */}
        <ContagionControlPanel
          assets={panelAssets}
          controls={controls}
          onChange={patchControls}
          running={cgRunning}
          onRun={runContagion}
          searchKind={searchKind}
          onSearchKindChange={setSearchKind}
        />

        {/* Center: full ecosystem map (hidden while the contagion overlay is open) */}
        <div className="relative flex-1 overflow-hidden">
          {!contagion && (
            <GraphCanvas
              graphKey="simulation"
              topology={topology}
              nodeStates={{}}
              walletHighlightIds={walletHighlightIds}
              selectedNodeId={selectedNodeId}
              onSelectNode={setSelectedNodeId}
              focusCenterIds={focusResult?.center_node_ids ?? undefined}
              focusOnlyIds={focusOnlyIds}
            />
          )}

          <SidePanel
            node={selectedNode}
            state={selectedState}
            edges={topology.edges}
            nodesById={nodesById}
            contagion={null}
            exposure={null}
            tickNarrative={null}
            tickDate={null}
            onClose={() => setSelectedNodeId(null)}
            onSelectNode={setSelectedNodeId}
          />

          {/* Hint overlay */}
          {!contagion && (
            <div className="pointer-events-none absolute inset-x-0 bottom-6 z-10 flex justify-center">
              <span className="rounded-full border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] px-4 py-1.5 text-xs text-[var(--color-text-secondary)] shadow-lg">
                왼쪽 패널에서 채널·자산·파라미터를 설정하고 전염 시뮬레이션을 실행하세요
              </span>
            </div>
          )}

          {/* Wallet Panel overlay — wallet/portfolio + focus search on the full map */}
          <WalletPanel
            simResult={null}
            simRound={0}
            nodeStates={{}}
            onHighlightChange={setWalletHighlightIds}
            onFocusChange={handleFocusChange}
            rightOffset={walletRight}
          />

          {/* Focus result panel — appears below WalletPanel */}
          <FocusResultPanel
            result={focusResult}
            loading={focusLoading}
            error={focusError}
            zoomActive={focusZoomActive}
            onToggleZoom={() => setFocusZoomActive((v) => !v)}
            onClose={() => {
              setFocusResult(null);
              setFocusError(null);
              setFocusZoomActive(false);
              setWalletHighlightIds(new Set());
            }}
            onSelectNode={(id) => setSelectedNodeId(id)}
          />

          {/* Live contagion overlay — covers the canvas with the live-built weighted graph */}
          {contagion && (
            <div className="absolute inset-0 z-40 bg-[var(--color-background)]">
              <GraphCanvas
                key={`cg-${contagion.incident_id}-${contagion.event.delta}`}
                graphKey="live-contagion"
                topology={contagion.render.topology}
                nodeStates={cgNodeStates}
                walletHighlightIds={new Set()}
                selectedNodeId={null}
                onSelectNode={() => {}}
                cameraFollow
              />
              <ContagionResultPanel data={contagion} />
              <button
                onClick={() => { setContagion(null); setCgPlaying(false); }}
                className="absolute left-3 top-3 z-50 rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-surface)] px-3 py-1.5 text-[11px] font-semibold text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
              >
                ← 맵으로 돌아가기
              </button>
              <div className="absolute bottom-3 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-full border border-[var(--color-border-subtle)] bg-[var(--color-surface)]/95 px-4 py-1.5 shadow-lg backdrop-blur">
                <button onClick={() => setCgPlaying((p) => !p)} className="text-[12px] text-[var(--color-text-primary)]">
                  {cgPlaying ? "⏸" : "▶"}
                </button>
                <input
                  type="range" min={0} max={Math.max(0, cgRoundCount - 1)} value={cgRound}
                  onChange={(e) => { setCgPlaying(false); setCgRound(Number(e.target.value)); }}
                  className="w-64"
                />
                <span className="font-mono text-[10px] text-[var(--color-text-secondary)]">R{cgRound}/{Math.max(0, cgRoundCount - 1)}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
