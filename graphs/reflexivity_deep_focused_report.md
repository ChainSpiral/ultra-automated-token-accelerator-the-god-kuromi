# Deep Reflexivity Report

Snapshot block: `25242078`

## Ranked Candidates

- **sUSDe** `0x9d39a5de30e57443bff2a8307a4256c8797a3497`: STOCK_NEGATIVE_FLOW_UNTESTED | rho(stock)=0.0000, rho(flow)=0.0000, inflation=1.0, depth=0, vaults=5, usd_hint=163590548, flow_status=not-run, confidence=MEDIUM
  - R/D: D / self-NAV (VAULT=SELF)
- **syrupUSDC** `0x80ac24aa929eaf5013f6436cda2a7ba190f5cc0b`: STOCK_NEGATIVE_FLOW_UNTESTED | rho(stock)=0.0000, rho(flow)=0.0000, inflation=1.0, depth=0, vaults=3, usd_hint=148640226, flow_status=not-run, confidence=MEDIUM
  - R/D: D / self-NAV (VAULT=SELF)
- **sUSDS** `0xa3931d71877c0e7a3148cb7eb4463524fec27fbd`: STOCK_NEGATIVE_FLOW_UNTESTED | rho(stock)=0.0000, rho(flow)=0.0000, inflation=1.0, depth=0, vaults=9, usd_hint=79305524, flow_status=not-run, confidence=HIGH
  - R/D: D / oracle-mismatch (VAULT=SELF, FEED:DAI / USD | feed asset does not match collateral symbol/underlying)
- **wsrUSD** `0xd3fd63209fa2d55b07a0f6db36c2f43900be3094`: STOCK_NEGATIVE_FLOW_UNTESTED | rho(stock)=0.0000, rho(flow)=0.0000, inflation=1.0, depth=0, vaults=6, usd_hint=48932839, flow_status=not-run, confidence=MEDIUM
  - R/D: D / self-NAV (VAULT=SELF)
- **siUSD** `0xdbdc1ef57537e34680b898e1febd3d68c7389bcb`: STOCK_NEGATIVE_FLOW_UNTESTED | rho(stock)=0.0000, rho(flow)=0.0000, inflation=1.0, depth=0, vaults=8, usd_hint=33088090, flow_status=not-run, confidence=HIGH
  - R/D: R / market-feed (VAULT=SELF, FEED:Chainlink-formatted InfiniFi RT Oracle)
- **stcUSD** `0x88887be419578051ff9f4eb6c858a951921d8888`: STOCK_NEGATIVE_FLOW_UNTESTED | rho(stock)=0.0000, rho(flow)=0.0000, inflation=1.0, depth=0, vaults=8, usd_hint=31002686, flow_status=not-run, confidence=MEDIUM
  - R/D: D / bespoke/NAV (VAULT=SELF, FEED:RedStone Price Feed for cUSD_FUNDAMENTAL)

## Not Resolvable
- Multi-hop crawl expansion was disabled in this saved run; rerun with `--crawl-mode cached` or `--crawl-mode live` to resolve holder/ledger paths for discovered non-control tokens.
- No opaque crawl edges were emitted by the enabled paths.
