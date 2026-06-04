/**
 * API client + type definitions for new-simulator.
 *
 * Two layers:
 *  - SimulatorAPI* types: what the Python backend (localhost:8000) returns
 *  - Graph component types: what RiskNode/FloatingEdge/GraphCanvas expect
 *
 * mapSimulatorGraph() bridges the two.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    ...init,
  });
  if (!res.ok) throw new Error(`${init?.method ?? "GET"} ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

// ─────────────────────────────────────────────────────────────
// Graph component types (matches soo_front RiskNode / GraphCanvas)
// ─────────────────────────────────────────────────────────────

export type NodeType = "Token" | "TokenProtocol" | "DefiProtocol" | "Oracle" | "Bridge";
export type RiskLevel = "safe" | "caution" | "danger";

export interface NodeMetadata {
  description?: string | null;
  chain?: string | null;
  symbol?: string | null;
  category?: string | null;
  quality?: string | null;
  pegTargetTokenId?: string | null;
  /** pool-owning protocol for a lending-market node (e.g. "Morpho Blue", "Aave V3", "Spark") */
  venue?: string | null;
  /** standardized node role: shock|asset|collateral_market|vault|position_bucket|cdp_ilk|amm_pool|loss_sink|oracle */
  role?: string | null;
  /** live|subgraph|registry|pendle_live|pendle_fallback|fallback_nav — provenance of this node's numbers */
  data_source?: string | null;
  /** true = approximation (e.g. top-N account scan, curated balances), not exact */
  approx?: boolean | null;
  /** issuer of the collateral token (e.g. "Pendle" for a PT-collateral Morpho market) */
  collateral_protocol?: string | null;
}

export interface GraphNode {
  id: string;
  type: NodeType;
  label: string;
  metadata: NodeMetadata;
  position?: { x: number; y: number } | null;
  active: boolean;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  weight: number;
  /** cross-protocol bridge tier: potential | latent | realized */
  tier?: string;
  /** 고래 행동 기반 bridge 여부 */
  bridge?: boolean;
  sharedWhales?: number;
}

export interface TopologyResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface NodeTickState {
  riskLevel: RiskLevel;
  falseNegative: boolean;
  liquidated: boolean;
  pegRatio: number | null;
  tvl: number | null;
  note: string | null;
}

export interface ContagionScore {
  nodeId: string;
  label: string;
  type: NodeType;
  impactScore: number;
  vulnerabilityScore: number;
  downstreamCount: number;
  tvlAtRiskUsd: number;
}

export interface ExposureMember {
  nodeId: string;
  label: string;
  channel: string;
  amountUSD: number | null;
}

export interface ExposureCluster {
  tokenId: string;
  label: string;
  totalExposureUsd: number;
  members: ExposureMember[];
}

// ─────────────────────────────────────────────────────────────
// Simulator backend types (Python API response shapes)
// ─────────────────────────────────────────────────────────────

interface SimNodeData {
  category?: string | null;
  description?: string | null;
  risk_level?: string | null;
  symbol?: string | null;
  chain?: string | null;
  launched?: string | null;
  shutdown?: string | null;
}

interface SimGraphNode {
  id: string;
  type: string; // 'chain' | 'token' | 'protocol' | 'bridge' | 'oracle'
  label: string;
  data: SimNodeData;
  position: { x: number; y: number };
}

interface SimGraphEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  edge_type?: string;
  tier?: string;
  bridge?: boolean;
  shared_whales?: number;
}

interface SimGraphResponse {
  nodes: SimGraphNode[];
  edges: SimGraphEdge[];
}

export interface SimRound {
  round: number;
  dex_price: number;
  oracle_price: number;
  sell_pressure_usd: number;
  bad_debt_usd: number;
  positions_liquidated: number;
  price_impact_pct: number;
  affected_nodes: string[];
  affected_edges: string[];
  round_description: string;
}

export interface SimResult {
  scenario: string;
  shock_description: string;
  initial_price: number;
  final_dex_price: number;
  depeg_pct: number;
  total_liquidated_usd: number;
  total_bad_debt_usd: number;
  total_bad_debt_usd_calibrated?: number | null;
  calibration_factor?: number | null;
  converged: boolean;
  rounds: SimRound[];
  data_source?: string | null;
  market_note?: string | null;
  calibration_note?: string | null;
  calibration_validated?: boolean | null;
  scenario_meta?: { confidence: string; source: string; rationale: string } | null;
}

export interface ThreatConfig {
  shock_pct: number;
  oracle_failure?: {
    mode: "frozen" | "lagging" | "manipulated" | "capo_cap";
    oracle_ids: string[];
    catchup_rate?: number;
  };
  issuance_breach?: {
    type: "uncapped_mint" | "index_inflation" | "key_compromise";
    bridge_ids?: string[];
    direct_rseth?: number;
  };
  liquidity_evaporation?: {
    type: "dex_drain" | "withdrawal_queue" | "pool_imbalance";
    residual_usd: number;
  };
  restaking_slash?: {
    slash_pct: number;
    nav_rate: number;
  };
  governance_failure?: {
    type: "no_intervention" | "delayed" | "wrong_params";
    response_block?: number;
  };
  lending_conditions?: {
    emode_ratio: number;
  };
}

export interface LivePositionStats {
  total_collateral_atoken: number;
  total_collateral_usd: number;
  oracle_price_usd: number;
  lt_normal: number;
  lt_emode: number;
  dex_liquidity_usd: number;
  block_number: number;
  data_source: string;
  error?: string | null;
}

export interface WalletScenarioRisk {
  scenario: string;
  name: string;
  shock_pct: number;
  new_hf: number;
  liquidated: boolean;
}

export interface WalletPosition {
  address: string;
  has_position: boolean;
  message?: string;
  total_collateral_usd?: number;
  total_debt_usd?: number;
  rseth_collateral?: number;
  rseth_collateral_usd?: number;
  health_factor?: number;
  lt_weighted?: number;
  liq_oracle_price?: number | null;
  drop_to_liq_pct?: number | null;
  zone?: "safe" | "warning" | "critical" | "liquidatable";
  scenario_risks?: WalletScenarioRisk[];
  oracle_price_usd?: number;
}

export interface PortfolioHolding {
  symbol: string;
  balance: number;
  price_usd: number;
  value_usd: number;
  category: string;
  graph_nodes: string[];
  source: string;
}

export interface WalletPortfolio {
  address: string;
  holdings: PortfolioHolding[];
  total_lst_lrt_usd: number;
  exposed_graph_nodes: string[];
  data_source: string;
}

// ─────────────────────────────────────────────────────────────
// Adapter: simulator graph → graph component types
// ─────────────────────────────────────────────────────────────

const TYPE_MAP: Record<string, NodeType> = {
  token: "Token",
  bridge: "Bridge",
  oracle: "Oracle",
};

function mapNodeType(simType: string, category?: string | null): NodeType {
  if (TYPE_MAP[simType]) return TYPE_MAP[simType];
  // 'protocol' and 'chain' → distinguish by category
  if (simType === "protocol" || simType === "chain") {
    const cat = category?.toLowerCase() ?? "";
    if (cat.includes("issuer") || cat.includes("lst") || cat.includes("lrt") || cat.includes("restaking"))
      return "TokenProtocol";
    return "DefiProtocol";
  }
  return "DefiProtocol";
}

export function mapSimulatorGraph(raw: SimGraphResponse): TopologyResponse {
  const nodes: GraphNode[] = raw.nodes.map((n) => ({
    id: n.id,
    type: mapNodeType(n.type, n.data?.category),
    label: n.label,
    metadata: {
      description: n.data?.description ?? null,
      chain: n.data?.chain ?? null,
      symbol: n.data?.symbol ?? null,
      category: n.data?.category ?? null,
    },
    position: n.position ?? null,
    active: !n.data?.shutdown,
  }));

  const edges: GraphEdge[] = raw.edges.map((e, i) => ({
    id: e.id ?? `edge-${i}`,
    source: e.source,
    target: e.target,
    type: e.edge_type ?? e.label ?? "unknown",
    weight: 1,
    tier: e.tier,
    bridge: e.bridge,
    sharedWhales: e.shared_whales,
  }));

  return { nodes, edges };
}

// ─────────────────────────────────────────────────────────────
// Per-round node state computation
// ─────────────────────────────────────────────────────────────

export const SAFE_NODE_STATE: NodeTickState = {
  riskLevel: "safe",
  falseNegative: false,
  liquidated: false,
  pegRatio: null,
  tvl: null,
  note: null,
};


// ─────────────────────────────────────────────────────────────
// API fetch functions
// ─────────────────────────────────────────────────────────────

export async function fetchGraph(): Promise<TopologyResponse> {
  const raw = await apiFetch<SimGraphResponse>("/api/graph");
  return mapSimulatorGraph(raw);
}


export interface PortfolioSimulateScenario {
  scenario: string;
  display_name: string;
  confidence: string;
  applied_multipliers: Record<string, number>;
  base_hf: number | null;
  new_hf: number | null;
  delta_hf: number | null;
  liquidated: boolean;
  post_shock_collateral_usd: number;
  post_shock_lt_weighted_usd: number;
}

export interface PortfolioSimulateResult {
  address: string;
  has_simulatable_position: boolean;
  message?: string;
  primary_asset?: string;
  primary_family?: string;
  aave_account?: {
    total_collateral_usd: number;
    total_debt_usd: number;
    lt_weighted: number;
    live_hf: number | null;
    is_likely_emode: boolean;
  };
  multi_position_summary?: {
    collaterals: Array<{
      symbol: string;
      amount: number;
      price_usd: number;
      value_usd: number;
      effective_lt: number;
      in_emode: boolean;
    }>;
    total_debt_usd: number;
    computed_hf: number | null;
  };
  scenarios?: PortfolioSimulateScenario[];
  data_quality?: Record<string, string>;
}

export async function fetchPortfolioSimulate(
  address: string,
): Promise<PortfolioSimulateResult> {
  return apiFetch<PortfolioSimulateResult>(`/api/wallet/${address}/portfolio-simulate`);
}

// ─────────────────────────────────────────────────────────────
// Fork-simulator (Anvil) endpoints — high-fidelity per-shock recipes
// ─────────────────────────────────────────────────────────────


export async function fetchWalletPosition(address: string): Promise<WalletPosition> {
  return apiFetch<WalletPosition>(`/api/wallet/${address}/position`);
}

export async function fetchWalletPortfolio(address: string): Promise<WalletPortfolio> {
  return apiFetch<WalletPortfolio>(`/api/wallet/${address}/portfolio`);
}

// ─────────────────────────────────────────────────────────────
// Phase 4 — Focus (통합 검색)
// ─────────────────────────────────────────────────────────────

export type FocusKind = "address" | "token" | "tx" | "empty";

export interface FocusEventEdge {
  edge_id: string;
  edge_type: string;
  from_address: string;
  to_address: string;
  asset: string | null;
  amount_decimal: number | null;
  block_number: number;
  tx_hash: string;
  protocol: string;
  metadata: Record<string, unknown>;
}

export interface FocusGraphNode {
  id: string;
  type: string;
  label: string;
  data?: Record<string, unknown>;
  position?: { x: number; y: number };
}

export interface FocusResult {
  kind: FocusKind;
  query: string;
  graph_node?: FocusGraphNode | null;
  canonical_id?: string;
  center_node_ids?: string[];
  related_node_ids?: string[];
  related_by_type?: Record<string, Array<{ id: string; label?: string; category?: string }>>;
  recent_events?: FocusEventEdge[];
  event_count?: number;
  event_counterparties?: string[];
  asset_address?: string | null;
  error?: string;
}

export async function fetchFocus(query: string): Promise<FocusResult> {
  return apiFetch<FocusResult>(`/api/focus?q=${encodeURIComponent(query)}`);
}

export interface FocusSuggestion {
  id: string;
  label: string;
  type?: string;
  symbol?: string | null;
  category?: string | null;
  score: number;
}

export async function fetchFocusSuggestions(q: string, limit = 8): Promise<{ q: string; suggestions: FocusSuggestion[] }> {
  return apiFetch(`/api/focus/suggestions?q=${encodeURIComponent(q)}&limit=${limit}`);
}

// ─────────────────────────────────────────────────────────────
// Formatters
// ─────────────────────────────────────────────────────────────

export function formatUsd(value: number | null | undefined): string {
  if (value == null) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `$${(value / 1e3).toFixed(1)}K`;
  return `$${value.toFixed(2)}`;
}

// ─────────────────────────────────────────────────────────────
// Backtest types
// ─────────────────────────────────────────────────────────────

export interface BacktestSnapshot {
  asset: string;
  atoken_supply: number;
  oracle_price: number;
  dex_liquidity_usd: number;
  lt_normal: number;
  ltv_emode: number;
  lt_emode: number;
  liq_bonus_emode: number;
  market_frozen: boolean;
  attacker_rseth_deposited?: number;
  attacker_ltv?: number;
}

export interface BacktestPredicted {
  bad_debt_usd: number;
  depeg_pct: number;
  liquidated_usd: number;
  rounds: number;
  converged: boolean;
}

export interface BacktestActual {
  bad_debt_usd: number;
  depeg_pct: number;
  total_loss_usd: number;
  bad_debt_weth?: number;
  bad_debt_block?: number;
  source?: string;
}

export interface BacktestAccuracy {
  bad_debt_error_pct: number;
  depeg_error_pct: number;
  calibration_factor: number;
}

export interface BacktestResult {
  incident_id: string;
  date: string;
  scenario: string;
  description: string;
  data_source: string;
  fetch_duration_s: number;
  snapshot: BacktestSnapshot;
  predicted: BacktestPredicted;
  actual: BacktestActual;
  accuracy: BacktestAccuracy;
  rounds: SimRound[];
  is_hypothetical: boolean;
  calibration_validated: boolean;
  actual_from_onchain: boolean;
  data_note: string;
  // Second-order ground-truth verification: how many LiquidationCall events
  // fired on-chain in the 30 days after the incident vs how many our sim
  // predicted. Both are independent of bad_debt $.
  predicted_liquidation_count?: number;
  actual_liquidation_count_30d?: number | null;
}


export interface BacktestIncident {
  id: string;
  date: string;
  asset: string;
  description: string;
  is_hypothetical: boolean;
  /** "cascade" (rsETH CascadeSimulator) | "contagion" (DebtRank graph) */
  type?: string;
}

export async function fetchBacktestIncidents(): Promise<{ incidents: BacktestIncident[] }> {
  return apiFetch<{ incidents: BacktestIncident[] }>("/api/backtest/incidents");
}

// ── Cross-protocol contagion backtest (DebtRank on the Morpho dependency graph) ──
export interface ContagionVaultPrediction {
  node: string; label: string; address?: string;
  total_usd: number; h: number; predicted_loss_usd: number;
}
export interface ContagionMarketRow {
  node: string; label: string; marketId?: string;
  supply_usd: number; h: number; implied_bad_debt_usd: number;
}
export interface ContagionComparison {
  n_predicted_victims: number; n_actual_victims: number;
  matched: string[]; recall: number | null; precision: number;
  false_positives: { label: string; predicted_loss_usd: number }[];
  missed: { name: string; loss_usd: number }[];
  predicted_loss_total_usd: number;
}
export interface ContagionMode {
  mode: string;
  asset_deltas: Record<string, number>;
  market_bad_debt: ContagionMarketRow[];
  vault_predictions: ContagionVaultPrediction[];
}
export interface ContagionMagnitudeRow {
  label: string; predicted_usd: number | null; actual_usd: number | null; error_pct: number | null;
  /** "usd" (default) | "pct" — how to format predicted/actual (channel backtests use pct) */
  unit?: string;
}
export interface LiveImpact {
  total_bad_debt_usd: number;
  morpho_bad_debt_usd?: number;
  /** subset of morpho_bad_debt attributable to Pendle PT collateral */
  pendle_pt_bad_debt_usd?: number;
  aave_bad_debt_usd?: number;
  /** DEX depth used for the shocked asset's fire-sale (0 = NAV/CAPO, fire-sale off) */
  shock_dex_depth_usd?: number;
  /** per-venue data-source/approximation notes */
  data_quality?: Record<string, string>;
  total_vault_loss_usd: number;
  n_markets: number;
  n_vaults: number;
  top_markets: { node: string; label: string; supply_usd: number; h: number; bad_debt_usd: number;
                 utilization?: number; available_usd?: number }[];
  top_vaults: { node: string; label: string; total_usd: number; h: number; loss_usd: number }[];
  position_venues?: {
    venue: string;
    n_liquidatable?: number;
    n_accounts_scanned?: number;
    total_bad_debt_usd?: number;
    bad_debt_by_asset?: Record<string, number>;
  }[];
  systemic_impact_score?: number;   // 0-100, relative (DebtRank centrality)
  n_downstream_nodes?: number;
  lambda_max?: number;              // Λ spectral radius (Bardoscia): >1 = amplifying
  stable?: boolean;
  shock_oracle_type?: string;       // "nav" (fire-sale OFF) | "dex" | "liquidity" | "common_mode"
  // ── liquidity channel ──
  channel?: string;                 // "depeg" | "liquidity"
  total_frozen_usd?: number;        // capital that can't be withdrawn (not lost)
  market_frozen_usd?: number;
  vault_frozen_usd?: number;
  // ── depeg cascade: per-mechanism decomposition (M1–M4) ──
  naive?: boolean;                  // true = M1-only floor (no amplification)
  mechanisms?: string[];            // active mechanisms, e.g. ["absorption","firesale",...]
  mech_absorption_usd?: number;     // M1 overcollateralization absorption (floor)
  mech_firesale_usd?: number;       // M2 DEX fire-sale contribution
  mech_oracle_lag_usd?: number;     // M3 oracle-lag arbitrage contribution
  mech_run_feedback_usd?: number;   // M4 withdrawal-run secondary-depeg contribution
  naive_floor_usd?: number;         // = M1; the no-amplification baseline
  amplification_x?: number | null;  // total / naive_floor (how much mechanisms added)
  oracle_lag_drain_usd?: number;    // loan liquidity drained while feed is stale (M3)
  queue_depeg?: number;             // LST withdrawal-queue secondary depeg (M4)
  price_delta_effective?: number;   // δ after queue-depeg amplification (M4)
  run_intensity?: number;           // ρ (M4)
  // ── event-discovered hidden cross-protocol bridges (behavioral tier) ──
  n_hidden_paths?: number;          // # of behavioral bridges surfaced by this shock
  discovered_bridge_usd?: number;   // at-risk $ via hidden shared-whale paths (behavioral, not exact)
  hidden_paths?: {
    from_venue: string; to_venue: string; tier: string;
    kind?: string; asset?: string | null; quantified?: boolean;
    shared_whales: number; exposure_usd: number; at_risk_usd: number;
    w: number; source: string;
  }[];
  liq_top_markets?: { node: string; label: string; supply_usd: number; h: number;
                      bad_debt_usd: number; utilization?: number; available_usd?: number }[];
}

export interface ContagionResult {
  incident_id: string;
  /** "vault_recall" | "magnitude" | "live" */
  kind?: string;
  /** live channel: "depeg" | "liquidity" */
  channel?: string;
  event: { id: string; date: string; delta: number; shock_node: string;
           pre_shock_date?: string; usr_pre_price?: number; usr_trough_price?: number;
           description?: string };
  impact?: LiveImpact;
  ground_truth?: {
    headline: string;
    // vault_recall (Resolv)
    solvency_loss_total_usd?: number;
    solvency_victims?: { name: string; address: string; impairment_frac: number; loss_usd: number }[];
    liquidity_only_drops?: { name: string; totalassets_drop_usd: number }[];
    channel_note?: string;
    // magnitude (kelp)
    aave_bad_debt_usd?: number;
    morpho_bad_debt_usd_est?: number;
    distribution_note?: string;
  };
  comparison?: { solvency: ContagionComparison; naive: ContagionComparison };
  comparison_rows?: ContagionMagnitudeRow[];
  distribution?: { predicted_aave_pct: number | null; actual_aave_pct: number };
  modes: { solvency: ContagionMode; naive?: ContagionMode };
  headline: string;
  render: {
    topology: TopologyResponse;
    node_states_by_round: Record<string, NodeTickState>[];
    n_rounds: number;
  };
  render_mode: string;
}

export async function fetchContagion(incidentId: string, mode = "solvency"): Promise<ContagionResult> {
  return apiFetch<ContagionResult>(`/api/contagion/${incidentId}?mode=${mode}`);
}

// ── Live what-if contagion (current Morpho state, user-chosen asset + severity) ──
export interface ShockableAsset {
  symbol: string; address: string | null; n_markets: number; supply_usd: number; borrow_usd: number;
  venues?: string[];
  /** loan-asset utilization (liquidity-run target list only) */
  utilization?: number;
  /** "oracle" = shared-oracle common-mode shock target (vs a plain collateral asset) */
  kind?: string;
  /** display name for oracle targets (symbol holds the oracle id, e.g. "oracle:chainlink_eth_usd") */
  label?: string;
  provider?: string;
  note?: string;
  /** symbols this oracle prices (blast radius) */
  affected?: string[];
}
export async function fetchLiveShockableAssets(): Promise<{ assets: ShockableAsset[] }> {
  return apiFetch<{ assets: ShockableAsset[] }>("/api/contagion-live/assets");
}
// Shared oracles (common-mode shock targets) — searched separately from tokens.
export async function fetchShockableOracles(): Promise<{ assets: ShockableAsset[] }> {
  return apiFetch<{ assets: ShockableAsset[] }>("/api/contagion-live/oracles");
}
// Supplied (loan) assets — selectable targets for a LIQUIDITY run.
export async function fetchRunnableAssets(): Promise<{ assets: ShockableAsset[] }> {
  return apiFetch<{ assets: ShockableAsset[] }>("/api/contagion-live/runnable-assets");
}
export interface LiveContagionParams {
  venues?: ("morpho" | "aave" | "spark" | "skycdp")[];
  recovery?: number;
  downstream?: boolean;
  channel?: "depeg" | "liquidity";
  /** depeg channel: true = M1-only naive floor (no amplification) */
  naive?: boolean;
  /** inject event-discovered hidden cross-protocol dependencies (shared-whale bridges) */
  includeDiscovered?: boolean;
  /** csv of collateral symbols to freeze (governance blocker) */
  freeze?: string;
}
export async function fetchLiveContagion(
  asset: string, delta: number, params: LiveContagionParams = {},
): Promise<ContagionResult> {
  const q = new URLSearchParams({ asset, delta: String(delta) });
  if (params.venues) q.set("venues", params.venues.join(","));
  if (params.recovery != null) q.set("recovery", String(params.recovery));
  if (params.downstream != null) q.set("downstream", String(params.downstream));
  if (params.channel) q.set("channel", params.channel);
  if (params.naive) q.set("naive", "true");
  if (params.includeDiscovered) q.set("include_discovered", "true");
  if (params.freeze) q.set("freeze", params.freeze);
  return apiFetch<ContagionResult>(`/api/contagion-live?${q.toString()}`);
}

