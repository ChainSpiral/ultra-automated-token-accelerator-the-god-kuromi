# EOA Flow Agent Handoff

Updated: 2026-06-16
Branch: `grahahahahahahaha`
Repo remote: `ChainSpiral/ultra-automated-token-accelerator-the-god-kuromi`

Before extending vault/entity strategy graphs, also read
`docs/strategy-graph-handoff.md`. The current product direction is a
proof-backed strategy graph, not a research-summary graph.

## Repo Split

This repo, `/Users/link/defi-dagggg`, is the data/crawler/prototype engine. It
owns:

- `feeder/eoa_timeline.py`: EOA timeline, wallet DFS, Alchemy/Etherscan transfer
  collection, seed receive preservation.
- `mock_server.py`: local mock/data API on `127.0.0.1:8000`.
- `graphs/frontend/eoa.*.json`: generated graph artifacts used by the UI.
- the original token relationship crawler and generated token graph artifacts.

The paired repo, `/Users/link/risk-exposure-monitoring-flowmap`, is the main
Next.js UI and API-enrichment surface. It owns:

- `/frontend/app/eoa-flow/page.tsx`
- `/frontend/components/eoa-flow/EoaFlowGraph.tsx`
- `/frontend/app/api/eoa-flow/route.ts`
- `/frontend/app/api/wallet-portfolio/route.ts`
- wallet cluster, pseudo-DeBank, and known-counterparty enrichment.

Both repos are part of the same local EOA-flow feature. `defi-dagggg` generates
or serves raw graph data; `risk-exposure-monitoring-flowmap` renders it and adds
portfolio/protocol enrichment.

## What Was Built Here

- Added `feeder/eoa_timeline.py`.
- Added live `/api/eoa-flow` and `/api/eoa-flows` to `mock_server.py`.
- Added generated EOA graph JSON artifacts under `graphs/frontend/eoa.*.json`.
- Added an EOA-flow frontend page/components in this repo's legacy frontend.
- Preserved seed direct receive events even in `--dfs-only` mode, so the Kelp
  root wallet shows the initial `116,500 rsETH` receive.
- Filtered zero-value token transfers and fake/spoof low-signal tokens from DFS.
- Added native ETH transfer discovery.
- Changed wallet DFS discovery to prefer Alchemy `alchemy_getAssetTransfers`
  over Etherscan `tokentx`/`txlist`, with Etherscan fallback.
- Limited Alchemy transfer pagination for POC speed:
  - default `EOA_FLOW_ALCHEMY_MAX_PAGES=2`
  - can be raised in env for deeper scans.
- Added aggressive file caching in `feeder/cache/eoa_timeline`:
  - Alchemy transfer pages
  - Etherscan account calls
  - RPC calls
  - `eth_getCode`
  - wallet kind
  - token reputation
  - receipts/source-code lookups

## Kelp Exploiter Test Case

Seed/root distribution wallet used in the UI:

```text
0x8B1b6c9A6DB1304000412dd21Ae6A70a82d60D3b
```

First visible large receive:

```text
from: 0x85d456b2dff1fd8245387c0bfb64dfb700e98ef3
to:   0x8b1b6c9a6db1304000412dd21ae6a70a82d60d3b
tx:   0x1ae232da212c45f35c1525f851e4c41d529bf18af862d9ce9fd40bf709db4222
block: 24908285
asset: 116,500 rsETH
```

Do not describe `0x8b1b...0d3b` as proven first attacker. It is the seed/root
distribution wallet chosen for the graph. The upstream sender and exploit call
path need trace/receipt-level investigation before calling it the first exploit
caller.

## Local Run Commands

Backend/data API:

```bash
cd /Users/link/defi-dagggg
python3 mock_server.py
```

Direct graph generation:

```bash
cd /Users/link/defi-dagggg
python3 feeder/eoa_timeline.py \
  --addresses 0x8B1b6c9A6DB1304000412dd21Ae6A70a82d60D3b \
  --dfs-wallets \
  --dfs-depth 99 \
  --dfs-directions both \
  --max-addresses 20 \
  --max-neighbors-per-address 80 \
  --from-block 23990000 \
  --to-block 25242078 \
  --important-only \
  --keep-token-flows \
  --receipt-transfers none \
  --dfs-only \
  --frontend-flow \
  --max-events-per-address 80 \
  --out /tmp/eoa.kelp.json
```

Quick syntax check:

```bash
python3 -m py_compile feeder/eoa_timeline.py mock_server.py
```

## Performance Notes

Cold `maxAddresses=20` discovery can still be noticeably slower than cached
queries because each address needs transfer discovery and wallet-kind filtering.
After cache fill, repeated runs are near-instant. The Next UI should request
graph-only first and portfolio enrichment later.

Do not turn `EOA_FLOW_ALCHEMY_MAX_PAGES` too high by default. It improves
coverage but can make high-activity wallets slow because Alchemy will paginate
through many transfer pages.

## Current Branches Pushed

- `defi-dagggg`: `grahahahahahahaha`
- paired UI repo `risk-exposure-monitoring`: `grahahahahahahaha`

Keep both branches aligned for EOA-flow changes.
