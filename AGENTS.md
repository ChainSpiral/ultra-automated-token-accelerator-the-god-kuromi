# defi-dagggg Agent Notes

## Current EOA Flow Handoff

- For the current `grahahahahahahaha` branch, read
  `docs/eoa-flow-agent-handoff.md` first.
- This repo is the data/crawler/mock-API side of the EOA-flow work. The paired
  UI/API repo is `/Users/link/risk-exposure-monitoring-flowmap`.
- Do not print API keys. Local keys are loaded from `/Users/link/podotree/.env`
  or process env.

## Vault Entity Registry

- Before classifying a vault-like holder, borrower, receipt token, or strategy
  account, check `registry/vault_entities.json` and
  `registry/vault_entities.md`.
- Do not stop at generic labels such as `PlasmaVaultBase`, `Subvault`,
  `BoringVault`, `Vault`, or `MetaMorphoV1_1`. Resolve the framework to the
  concrete project/operator when the registry has evidence.
- If a vault is not in the registry, classify conservatively as `vault_unknown`
  or `contract_unknown`, save the evidence, and add a new registry entry only
  after source/onchain support exists.
- For borrow-flow interpretation, distinguish:
  - the debt event (`Borrow`, debt shares, debt token balance)
  - the receiver that got the borrowed token
  - the first-hop token holder/protocol after the borrow
  - same-transaction reallocation across lending venues
- PlasmaVault/IPOR Fusion example: `0xb8a451107a9f87fde481d4d686247d6e43ed715e`
  is `Fusion stETH looping Ethereum` (`fusnstETH`), an IPOR Fusion
  PlasmaVault. Treat repeated Aave/Spark/Morpho movements as managed vault
  strategy rebalancing unless fresh evidence shows an external user flow.
- Mellow example: Subvaults such as
  `0x893aa69fbaa1ee81b536f0fbe3a3453e86290080` and
  `0x3883d8cdcdda03784908cfa2f34ed2cf1604e4d7` should be rolled up to parent
  `0x277c6a642564a91ff78b008022d65683cee5ccc5`.

## Onchain-Proven Vault/Entity Strategy Graph

The goal is an automatically inferred strategy graph for vaults, entities, and
wallet clusters. This repo must produce proof-backed data. It must not generate
story graphs from research summaries.

Before changing any strategy graph producer, read
`docs/canonical-strategy-graph-design.md`. It is the fixed node/edge/cluster
contract that crawlers and adapters must emit into. Bridges, swaps, borrows,
stakes, redeems, and other actions are edges; durable actor clusters, protocol
surfaces, markets, pools, and tokens are nodes.

### Hard Boundary

- Research can choose targets and adapters, but cannot create graph facts.
- A graph fact exists only if code derived it from one of:
  - decoded receipt logs
  - traces when logs are insufficient
  - direct contract reads at a fixed block
  - protocol API/indexer rows with source metadata
  - locally versioned registries that include evidence pointers
- Narrative-only relationships such as `incident_context`, `issues`,
  `company exposure`, or `known strategy` are not graph edges.
- If a relationship is suspected but not machine-proven, emit a `gap`, not an
  edge.

### Required Evidence Object

Every generated edge must reference one or more evidence objects containing:

- chain id and block number
- tx hash when event/trace-based
- log index or trace path when applicable
- contract address
- decoded event name or function signature
- token address, symbol, decimals, raw amount, normalized amount, and USD value
  when available
- source API or RPC method
- parser/adapter name and version
- confidence: `exact`, `inferred_from_receipt`, `inferred_from_snapshot`,
  `registry_backed`, or `low_confidence_gap`

If the evidence object cannot be constructed, do not emit the edge.

### Deterministic Inference Pipeline

Implement vault/entity strategy graph generation in this order:

1. Seed resolution:
   - accept address, token, vault, protocol market, or named entity
   - resolve proxies, implementation, Safe metadata, creation tx/deployer, and
     known registry labels
2. Cluster discovery:
   - cluster EOAs/Safes/contract-wallets by deterministic transfer/deployer/
     ownership rules
   - exclude known protocols, CEX, bridges, routers, and solvers from wallet DFS
     expansion
   - preserve excluded counterparties as infra/protocol endpoints
3. Raw event collection:
   - native and ERC20/ERC721/ERC1155 transfers
   - receipt logs for protocol actions
   - traces for calls where logs do not identify the semantic actor
   - direct balances/share/debt/collateral snapshots at the configured block
4. Adapter parsing:
   - Aave/Spark: supply, withdraw, borrow, repay, liquidation, aToken, debt
     token, collateral usage, `onBehalfOf`
   - Morpho/MetaMorpho: market id, supply shares, borrow shares, collateral,
     vault allocator/curator behavior
   - ERC-4626/vault frameworks: asset/share, totalAssets, convertToAssets,
     deposit/withdraw/redeem, parent/subvault/strategy links
   - DEX/LP: pool, token pair, add/remove liquidity, swaps, LP holder exposure
   - staking/LST/LRT: mint, redeem, queue, claim, withdrawal credentials where
     available
   - bridge/CEX/router/solver: classify as endpoints and value sinks/routes,
     not wallet-cluster members
5. Semantic normalization:
   - convert raw logs/traces/snapshots into typed events:
     `token_transfer`, `supply`, `withdraw`, `borrow`, `repay`,
     `collateralize`, `swap`, `lp_add`, `lp_remove`, `stake`, `unstake`,
     `queue`, `claim`, `redeem`, `bridge`, `cex_deposit`, `router_exec`,
     `vault_share`, `debt_position`, `cluster_membership`
6. Snapshot reconciliation:
   - reconcile historical event accumulation against current balances and
     protocol positions
   - separate historical flow from current position
   - label debt as debt, receipt/share as receipt/share, collateral as
     collateral, and liquid token as liquid token
7. Graph emission:
   - output nodes, edges, evidence, gaps, and notes separately
   - edges must point to evidence ids
   - gaps must never affect graph connectivity

### Current Implementation TODO

1. Replace static/preset entity-flow graphs with generated graphs from address
   or entity seeds.
2. Delete or quarantine any preset edge that came from a research summary rather
   than normalized events or reconciled snapshots.
3. Add schema checks that fail generation when an edge lacks evidence.
4. Build adapters before adding visuals. Missing adapter means `needs_adapter`,
   not a guessed edge.
5. For Stream, f(x), Yield Basis, and similar vault entities, generate:
   - cluster node for the entity/wallet set
   - protocol market/pool/vault nodes actually touched onchain
   - edges for supply/borrow/swap/LP/bridge/CEX/router flows with proof
   - current snapshot totals by token, debt, collateral, shares, redeemability
   - gap list for unsupported chains, missing traces, or unknown contracts
6. Keep block number fixed per run for cacheability. Cache raw API/RPC results,
   decoded events, wallet kind, proxy resolution, token reputation, snapshots,
   and adapter outputs with source timestamps/block numbers.

### Acceptance Test

A generated graph is acceptable only if a downstream UI can click every edge
and show the exact data that produced it. For any edge, the data API must answer:

- what semantic action happened
- which tx/log/trace/contract read/API row proves it
- which actor and counterparty were used
- which token and amount moved or which position changed
- whether it is historical flow, current position, debt, collateral, share,
  receipt token, or cluster membership
- which adapter produced the interpretation

If this cannot be answered, emit a gap instead of an edge.
