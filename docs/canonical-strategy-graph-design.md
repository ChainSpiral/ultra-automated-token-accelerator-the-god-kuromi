# Canonical Strategy Graph Design

Updated: 2026-06-18

This graph is not a drawing format. It is the data contract that crawler and
adapter output must satisfy before the UI renders anything.

## Core Rule

Nodes represent durable things. Edges represent proven semantic state changes or
proven structural relationships between those things.

Do not create a node for an intermediate "event" or a one-off action. Bridges,
swaps, deposits, borrows, stakes, and redeems are edges. A bridge contract,
router, vault, pool, or market can be a node only when it is the durable surface
that the actor interacted with.

## Node Kinds

Use only these high-level `kind` values in frontend payloads:

- `cluster`: a deterministic actor cluster. This can include EOAs, Safes, and
  contract wallets. It must exclude known protocols, CEXs, bridges, routers, and
  solvers.
- `protocol`: a durable protocol surface: vault, staking contract, mint/redeem
  contract, router endpoint, bridge endpoint, or protocol controller.
- `market`: a protocol market or pool with its own asset pair and accounting:
  lending market, DEX pool, LP vault, Morpho market id, Aave reserve, etc.
- `token`: an asset node. Use this for ERC20 assets, receipt/share tokens, debt
  tokens, wrapper tokens, and chain-specific bridged versions.
- `infra`: CEX, bridge, router, solver, or message endpoint when the endpoint
  itself matters and is not part of an actor cluster.
- `system`: mint/burn/null-address style system node.

## Node Categories

Categories are lower-level and should stay stable enough for styling and
filters:

- Actor categories: `actor_cluster`, `operator`, `wallet_cluster`,
  `lender_cluster`, `borrower_cluster`
- Protocol surface categories: `mint_surface`, `staking_vault`,
  `erc4626_vault`, `bridge_endpoint`, `router`, `solver`, `dex_router`
- Market categories: `lending`, `dex_pool`, `lp_vault`, `vault_strategy`
- Token categories: `liquid_asset`, `receipt_asset`, `debt_asset`,
  `collateral_asset`, `wrapper_asset`, `bridged_asset`
- Edge endpoint categories: `cex`, `bridge`, `router`, `solver`,
  `mint_burn`

If a category is unknown, emit a gap. Do not invent a category based on a
research story.

## Edge Kinds

Edges must be typed by what actually happened or what a direct contract read
proves:

- Historical value flow:
  `transfer`, `bridge`, `swap`, `cex_deposit`, `cex_withdraw`,
  `router_exec`, `mint`, `burn`
- Lending:
  `supply`, `withdraw`, `borrow`, `repay`, `collateralize`,
  `liquidate`, `market_supply_snapshot`, `market_borrow_snapshot`
- Vault or wrapper:
  `deposit`, `withdraw`, `redeem`, `stake`, `unstake`, `vault_asset`,
  `receipt_token`, `convert_to_assets`, `share_snapshot`
- DEX/LP:
  `lp_add`, `lp_remove`, `pool_swap`, `pool_liquidity_snapshot`
- Cluster:
  `funded`, `deployed`, `owned_by`, `safe_owner`, `same_actor_cluster`
- Structural market facts:
  `loan_asset`, `collateral_asset`, `pool_token0`, `pool_token1`,
  `underlying_asset`

## Evidence

Every edge must reference evidence ids. Evidence must include the source method
and adapter. Accepted sources:

- receipt logs
- traces
- direct contract reads at a fixed block
- protocol API/indexer rows with source metadata
- local registries with evidence pointers

No evidence means no edge. Emit a gap instead.

## Token and Wrapper Modeling

Asset relationships should be explicit. For a staking or ERC4626 wrapper, do
not connect token A directly to token B. Use a protocol surface:

```text
token:ethereum:deusd
  --vault_asset / direct asset() read-->
protocol:ethereum:elixir:sdeusd-staking-vault
  --receipt_token / name-symbol-contract read-->
token:ethereum:sdeusd
```

For Stream, this means `sdeUSD` collateral is not just a label on a Morpho edge.
The graph should show that sdeUSD is a receipt/wrapper token over deUSD, and
then show the Morpho market accepting sdeUSD as collateral.

## Bridge Modeling

Bridge activity is normally an edge, not a node:

```text
cluster:stream
  --bridge xUSD via LayerZero OFT-->
market:plume:morpho:xusd-usdc
```

If the bridge endpoint itself is under analysis, it can appear as an `infra`
node, but the value movement remains a `bridge` edge.

## Adapter Contract

Adapters must emit normalized semantic records before graph construction:

```json
{
  "semantic_type": "collateralize",
  "actor": "cluster:stream",
  "surface": "market:morpho:...",
  "asset": "token:ethereum:sdeusd",
  "amount": "13860000",
  "position_effect": "collateral_increase",
  "time_scope": "historical_flow",
  "evidence_ids": ["ev:..."]
}
```

The graph builder then maps the record to a canonical edge. UI-specific layout
must not alter semantic meaning.

## Visual Layout Rule

The UI should prefer this radial order:

1. actor clusters in the center
2. protocol surfaces and markets around the actors
3. asset/token nodes outside protocol surfaces
4. infra endpoints on the far edge

This keeps the question readable: who controlled the funds, which surface was
used, which asset/position changed, and what proof backs the edge.
