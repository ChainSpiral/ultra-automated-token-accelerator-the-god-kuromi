# Vault Entity Registry Notes

This folder pins vault identities that recur in holder graphs and borrow-flow
graphs. Treat this as evidence-backed context, not as a guarantee that every
future balance or owner is unchanged.

## IPOR Fusion / PlasmaVault

Observed instance:

- `0xb8a451107a9f87fde481d4d686247d6e43ed715e`
- Contract label: `PlasmaVaultBase`
- Proxy label: `PlasmaVault`
- Implementation: `0x2de7320004f837925ba31326ff66210be90171ab`
- Onchain name: `Fusion stETH looping Ethereum`
- Symbol: `fusnstETH`
- Asset: `stETH` (`0xae7ab96520de3a18e5e111b5eaab095312d7fe84`)
- External product label: IPOR / `Fusion stETH looping Ethereum`
- Curator label from vaults.fyi: `IPOR DAO`

Interpretation:

This is not a random wallet. It is an IPOR Fusion PlasmaVault strategy vault.
The large WETH borrow-flow samples show the vault receiving/borrowing WETH and
then allocating through Morpho Blue, Aave WETH, Aave Lido WETH and Spark WETH
receipt tokens inside one transaction. Read it as a managed leverage/looping
strategy vault unless newer evidence contradicts that.

Representative tx from local borrow-flow work:

- `0xa518377ca19b676144c4c0b2a6a81f50cc6a5ffee87b206364ed519e630ca39c`
- Pattern: `Morpho Blue -> PlasmaVaultBase`, then `PlasmaVaultBase -> aEthWETH`,
  `aEthLidoWETH`, `spWETH`, followed by Morpho borrow and Morpho reallocation.

What IPOR docs imply for tracing:

- Fuses are protocol-specific actions, such as supplying to Aave.
- Markets are venue IDs such as Aave, Spark or Morpho.
- Substrates restrict the specific assets, market IDs or pool IDs a vault can
  interact with.
- Therefore a PlasmaVault tx often looks like several lending movements in one
  receipt; do not classify it as simple EOA borrowing.

Fame / relevance:

IPOR Fusion is a public vault infrastructure project with official docs and an
SDK, and this exact vault is listed on IPOR and vaults.fyi. It is known enough to
pin as an entity. The individual stETH looping vault is not Aave/Morpho-scale;
its vault TVL is much smaller than the gross lending positions it touches.

Risk note:

There are public reports of a January 2026 IPOR Fusion PlasmaVault-related
exploit involving a legacy EIP-7702 issue. Keep that as a caution flag, but do
not generalize it to every PlasmaVault without checking the affected component.

Sources:

- https://app.ipor.io/fusion/ethereum/0xb8a451107a9f87fde481d4d686247d6e43ed715e
- https://app.vaults.fyi/opportunity/mainnet/0xB8a451107A9f87FDe481D4D686247D6e43Ed715e
- https://github.com/IPOR-Labs/ipor-fusion.py
- https://docs.ipor.io/build-on-fusion/atomists/vault-configuration-step-by-step/substrates
- https://www.cryptotimes.io/2026/01/07/ipors-fusion-plasmavault-hit-by-336k-exploit-via-eip-7702-flaw/

## Mellow

Observed parent vault:

- `0x277c6a642564a91ff78b008022d65683cee5ccc5`
- Label: `Mellow stRATEGY / strETH Vault`
- Share manager: `0xcd3c0f51798d1daa92fb192e57844ae6cee8a6c7`
- Known subvaults seen in current graphs:
  - `0x893aa69fbaa1ee81b536f0fbe3a3453e86290080`
  - `0x3883d8cdcdda03784908cfa2f34ed2cf1604e4d7`

Interpretation:

Mellow uses parent Vault plus Subvault execution accounts. If a Subvault appears
as a token holder, roll it up to the parent vault/product before explaining the
graph.

Local implementation:

- `feeder/mellow.py`

## Ether.fi BoringVault / liquidETH

Observed instance:

- `0xf0bb20865277abd641a307ece5ee04e79073416c`
- Label: `BoringVault`
- Name/symbol from prior local work: `Ether.fi Liquid ETH` / `liquidETH`

Interpretation:

Treat as a managed vault receipt/product, not a simple wallet. Re-read authority
and current holdings before making governance or custody claims.

## Veda / Lido Golden Goose Vault

Observed instance:

- `0xef417fce1883c6653e7dc6af7c6f85ccde84aa09`
- Contract label: `BoringVault`
- Onchain name/symbol: `Golden Goose Vault` / `GG`
- Local snapshot observation: at block `25242078`, this vault held about
  `70,518 aEthweETH` in the Aave weETH market.

Interpretation:

GG is the receipt token for Lido GGV, a Golden Goose Vault product curated by
Veda. Lido's public GGV page describes it as a vault for ETH and (w)stETH
deposits that optimizes opportunities across chains. In the holder graph, the
managed vault product is the meaningful exposure. Expanding GG token holders
adds shareholder noise and should be skipped unless the research question is
specifically about GG ownership.

Sources:

- https://stake.lido.fi/earn/ggv/deposit
- https://etherscan.io/address/0xef417fce1883c6653e7dc6af7c6f85ccde84aa09

## InheritableVault Custody Wallet

Observed instance:

- `0x000000000073f8f0541e942d85ef5fb5d0e84844`
- Proxy label: `ERC1967Proxy`
- Implementation: `0x87f93115e313cba3e9d7a559424d1be5cac01b4d`
- Implementation label: `InheritableVault`
- Local snapshot observation: at block `25242078`, this address held about
  `182,418 stETH` directly and no wstETH or WETH.

Interpretation:

This is not an Aave/Spark/Morpho strategy vault. The verified implementation
describes itself as a UUPS-upgradeable general wallet with dead-man-switch
ownership transfer. It has owner-only arbitrary execution plus ERC20/ETH
transfer functions, and an inheritor/timelock mechanism. Read it as a controlled
custody wallet unless separate evidence identifies the real-world controller.

Control caveat:

Owner/inheritor addresses can change and should be re-read at the relevant block
before making current custody claims.

Sources:

- https://etherscan.io/address/0x000000000073f8f0541e942d85ef5fb5d0e84844
- https://etherscan.io/address/0x87f93115e313cba3e9d7a559424d1be5cac01b4d#code
