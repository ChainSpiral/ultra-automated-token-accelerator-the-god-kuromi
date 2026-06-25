# Strategy Graph Handoff

Updated: 2026-06-18
Branch: `grahahahahahahaha`

## Product Target

Build an automatically inferred vault/entity strategy graph backed by machine
evidence.

This repo is the producer side. It should collect raw onchain/API data, parse it
with adapters, reconcile snapshots, and emit graph payloads. The paired UI/API
repo is `/Users/link/risk-exposure-monitoring-flowmap`.

## Non-Negotiable Rule

Research summaries can choose what to inspect, but cannot create graph facts.

No graph node or edge should exist because an article, incident writeup, or
manual note says it exists. A graph edge must come from normalized events or
reconciled snapshots, with evidence ids pointing to raw proof.

Suspected but unproven relationships must be emitted as `gaps`, never as
connective graph edges.

## Required Producer Output

Read `docs/canonical-strategy-graph-design.md` before modifying producers. It
defines the fixed graph contract: durable actor clusters, protocol surfaces,
markets, pools, and tokens are nodes; bridges/swaps/borrows/stakes/redeems are
proof-backed edges.

Entity/vault strategy graph output must be:

- `nodes`: concrete addresses, clusters, protocol markets, pools, vaults,
  receipt/share/debt surfaces, bridge/CEX/router/solver endpoints
- `edges`: proof-backed semantic relationships
- `evidence`: raw proof records referenced by `edges[].evidenceIds`
- `gaps`: unsupported chains, missing adapters, unresolved registries, missing
  traces, or unverified relationships
- `notes`: optional non-connective context

Use `feeder/strategy_graph_validator.py` to fail fast when an edge lacks proof.

## Evidence Sources

Allowed sources for graph edges:

- decoded receipt logs
- traces when logs do not identify the semantic actor
- direct contract reads at the configured block
- protocol APIs/indexers with source metadata
- local registries with explicit evidence pointers

Not allowed as edge sources:

- research prose
- manually drawn incident context
- hardcoded company relationships without contract or registry proof
- UI labels that are not backed by parser output

## Deterministic Pipeline

1. Resolve seed:
   - address, token, vault, protocol market, or named entity
   - proxy implementation, Safe metadata, creation tx/deployer, registry label
2. Discover clusters:
   - wallet transfers, mutual funding, deployer relation, ownership where proven
   - exclude known protocols, CEX, bridges, routers, solvers from wallet DFS
3. Collect raw data:
   - native/ERC20/ERC721/ERC1155 transfers
   - protocol receipt logs
   - traces where required
   - balances, share balances, debt balances, collateral snapshots
4. Parse adapters:
   - Aave/Spark: supply, withdraw, borrow, repay, liquidation, aToken, debt
     token, collateral, `onBehalfOf`
   - Morpho/MetaMorpho: market id, collateral, supply shares, borrow shares,
     vault allocator/curator positions
   - ERC-4626/vaults: asset/share, totalAssets, convertToAssets,
     deposit/withdraw/redeem, parent/subvault/strategy
   - DEX/LP: pool, pair, swaps, LP add/remove, LP exposure
   - bridge/CEX/router/solver: endpoint classification, not wallet cluster
5. Normalize semantic events.
6. Reconcile event accumulation with current snapshots.
7. Emit graph payload only from normalized events and reconciled snapshots.

## Immediate TODO After Compact

1. Replace static `/flow?entity=stream`-style preset graphs with generated
   payloads.
2. Quarantine any existing `incident_context`, `issues`, or narrative edges.
3. Make every generated edge include `evidenceIds`.
4. Add missing adapter output as `needs_adapter` gaps.
5. Generate one proof-backed test graph for Stream, f(x), or Yield Basis.
6. Confirm the UI can click every edge and show raw proof.

## Acceptance Test

Before handing off any graph JSON, run:

```bash
python3 feeder/strategy_graph_validator.py <graph.json>
python3 -m unittest tests/test_strategy_graph_validator.py
```

The validator must reject:

- edges with no `evidenceIds`
- edges whose evidence ids are missing
- evidence without source/adapter/confidence
- narrative-only edge categories such as `incident_context`, `issues`, or
  `research_summary`
