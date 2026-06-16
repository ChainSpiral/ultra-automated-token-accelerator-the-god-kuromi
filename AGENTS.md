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
