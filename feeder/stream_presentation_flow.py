#!/usr/bin/env python3
"""Build an English presentation graph focused on Stream <-> Elixir evidence.

Input is the proof-backed historical Stream artifact. This script does not add
offchain narrative edges. Most edges are aggregated from flow.stream.historical.json;
the Plume private-market edges are fixed, block-pinned onchain evidence from
Plume RPC/Dune logs collected during incident verification. Cross-chain bridge
activity is represented as an edge, not as an intermediate actor node.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "graphs" / "frontend" / "flow.stream.historical.json"
DEFAULT_OUT = ROOT / "graphs" / "frontend" / "flow.stream.presentation.json"

ZERO = "0x0000000000000000000000000000000000000000"
STREAM_CLUSTER = "semantic:stream-observed-actors"
ELIXIR_CLUSTER = "semantic:elixir-observed-actors"
STREAM_MINT_SURFACE = "semantic:stream-xusd-minting-surface"
DEX_ROUTING = "semantic:presentation-dex-routing"
MORPHO_SDEUSD_USDC = "market:morpho:0x0f9563442d64ab3bd3bcb27058db0b0d4046a4c46f0acd811dacae9551d2b129"
MORPHO_DEUSD_USDC = "market:morpho:0xbd1ad3b968f5f0552dbd8cf1989a62881407c5cccf9e49fb3657c8731caf0c1f"
METAMORPHO_SUPPLIER_VAULTS = "semantic:presentation-metamorpho-supplier-vaults"
ELIXIR_USDC_VAULT = "0x1265a81d42d513df40d0031f8f2e1346954d665a"
PLUME_ELIXIR_FUNDER = "0x1bdb4c119225abaca0bfe12610789902851221ab"
PLUME_ELIXIR_SAFE = "0xaf8d3fc487261b04256a1cc433856cc808eeb070"
PLUME_MORPHO_XUSD_USDC = "market:plume:morpho:0x82e7ab8ccabaac59b5f397507ed031ebf19a9a5b2657c00c93bc2423cd0a890d"
ELIXIR_SDEUSD_STAKING_VAULT = "protocol:ethereum:elixir:sdeusd-staking-vault"
STREAM_OWNER_SAFE = "0x14bcd9da052cdc6fe0b9446d5a616d5b7b4d4550"
STREAM_STABLE_WRAPPER = "0x6eaf19b2fc24552925db245f9ff613157a7dbb4c"
STREAM_BRIDGE_BOUNDARY = "semantic:presentation-crosschain-bridges"
STREAM_MEV_ROUTING = "semantic:presentation-mev-routing"
STREAM_AAVE_USDC = "semantic:presentation-aave-usdc-position"
STREAM_PUSD_MINTER = "semantic:presentation-pusd-minter"
STREAM_OPAQUE_EXTERNAL = "semantic:presentation-opaque-external-outflows"
DEUSD_TOKEN = "token:ethereum:deusd"
SDEUSD_TOKEN = "token:ethereum:sdeusd"
XUSD_ETH_TOKEN = "token:ethereum:xusd"
XUSD_PLUME_TOKEN = "token:plume:xusd"
USDC_ETH_TOKEN = "token:ethereum:usdc"
USDT_ETH_TOKEN = "token:ethereum:usdt"
USDC_PLUME_TOKEN = "token:plume:usdc"
ETHEREUM_READ_BLOCK = 25_344_736

STREAM_ACTORS = {
    "0x1597e4b7cf6d2877a1d690b6088668afdb045763": "Stream/deUSD observed actor",
    "0xcb4a7b790edb7fa3e2731efd7ed85275f92fc74a": "deUSD/sdeUSD observed actor",
    "0x33a47b816cf4fc6698b4cf1b876da9783b18b325": "Stream/deUSD routing actor",
    "0x25e028a45a6012763a76145d7ceea3587015e990": "deUSD mint receiver",
    STREAM_OWNER_SAFE: "xUSD owner Safe / custody surface",
}
ELIXIR_ACTORS = {
    "0x69088d25a635d22dcbe7c4a5c7707b9cc64bd114": "Elixir mint/redeem proxy",
    "0x738744237b7fd97af670d9ddf54390c24263cea8": "Elixir Safe actor",
}

BRIDGE_TARGETS = {
    "0x6c96de32cea08842dcc4058c14d3aaad7fa41dee": "USDT0 OAdapterUpgradeable",
    "0x674cb5133a2deaa4abe86ed56cb7555960966320": "Interport CCTP v2 Bridge",
    "0x53e82abbb12638f09d9e624578ccb666217a765e": "Agglayer vbUSDC Token",
    "0x3a23f943181408eac424116af7b7790c94cb97a5": "SocketGateway",
}
MEV_TARGETS = {
    "0x8c864d0c8e476bf9eb9d620c10e1296fb0e2f940": "Etherscan-labeled MEV Bot 0x8c86...f940",
}
AAVE_TARGETS = {
    "0x98c23e9d8f34fefb1b7bd6a91b7ff122f4e16f5c": "Aave Ethereum USDC V3 aToken",
}
PUSD_MINTER_TARGETS = {
    "0x6104fe10ca937a086ba7adbd0910a4733d380cb6": "Plume pUSD TellerWithMultiAssetSupportPredicateProxy",
}
OPAQUE_EXTERNAL_TARGETS = {
    "0xd629edc5f1ff4cb7d9dd0a5be72c1d9fc5d02709": "unlabeled deUSD holder contract",
    "0xa65e4b8af4d325838d68fd9ddf925ea3ca96f167": "unlabeled EOA receiving USDC",
}

ROLE_LABELS = {
    "stream_stablecoin_funding": "SELF-MINT step 1: Stream actors sent stablecoins into the xUSD mint surface",
    "xusd_mint_to_stream": "SELF-MINT step 2: xUSD was minted back to Stream actors",
    "xusd_burn_by_stream": "SELF-MINT unwind: Stream actors burned xUSD",
    "stream_to_elixir_transfer": "TOKEN FLOW: Stream actors sent tokens to Elixir actors",
    "elixir_to_stream_transfer": "TOKEN FLOW: Elixir actors sent tokens back to Stream actors",
    "elixir_swap_paid": "Elixir paid into DEX / solver routing",
    "elixir_swap_received": "Elixir received from DEX / solver routing",
    "elixir_token_burn": "Elixir-side redeem / burn flow",
    "elixir_token_mint": "Elixir-side mint / issuance flow",
    "stream_router_swap_paid": "STREAM execution: Stream paid into DEX / solver routing",
    "stream_router_swap_received": "STREAM execution: Stream received from DEX / solver routing",
    "stream_stablewrapper_outflow": "STREAM redemption surface: Stream sent liquid assets to StableWrapper",
    "stream_bridge_outflow": "STREAM cross-chain/outside-chain exit: Stream sent assets to bridge or wrapper endpoints",
    "stream_mev_route_outflow": "STREAM external execution: Stream sent assets to MEV / solver counterparty",
    "stream_aave_usdc_position": "STREAM Aave surface: Stream moved USDC into Aave V3 USDC token surface",
    "stream_pusd_minter_outflow": "STREAM tokenized cash surface: Stream sent USDC into pUSD minter",
    "stream_opaque_external_outflow": "STREAM opaque external outflow: Stream sent assets to unlabeled non-protocol endpoints",
    "metamorpho_supply_sdeusd_usdc": "MORPHO lender side: MetaMorpho vaults supplied USDC",
    "elixir_vault_supply_deusd_usdc": "MORPHO lender side: MEV Capital Elixir USDC supplied USDC",
    "stream_sdeusd_collateral": "MORPHO collateral side: Stream posted sdeUSD",
    "stream_historical_usdc_borrow": "MORPHO borrow txs: Stream borrowed USDC",
    "stream_current_usdc_borrow": "MORPHO current snapshot: Stream still owes USDC",
    "deusd_sdeusd_wrapper_surface": "WRAPPER: deUSD is staked through Elixir's sdeUSD vault",
    "sdeusd_market_collateral_asset": "MARKET PARAM: Morpho sdeUSD/USDC treats sdeUSD vault shares as collateral",
    "deusd_market_collateral_asset": "MARKET PARAM: Morpho deUSD/USDC treats deUSD as collateral",
    "morpho_market_loan_asset": "MARKET PARAM: Morpho market loan side is USDC",
    "plume_elixir_safe_funding": "PLUME private-market step 1: Elixir signer funded the Safe with USDC",
    "plume_elixir_usdc_supply": "PLUME private-market step 2: Elixir-linked Safe supplied USDC",
    "plume_stream_xusd_layerzero_bridge": "BRIDGE: Stream moved xUSD from Ethereum to Plume via LayerZero OFT",
    "plume_stream_xusd_collateral": "PLUME private-market step 4: Stream posted xUSD collateral",
    "plume_stream_usdc_borrow": "PLUME private-market step 5: Stream borrowed USDC",
}

PLUME_PRIVATE_MARKET_EDGES = [
    {
        "source": PLUME_ELIXIR_FUNDER,
        "target": PLUME_ELIXIR_SAFE,
        "role": "plume_elixir_safe_funding",
        "asset": "USDC",
        "amount": 70_498_049.005,
        "count": 6,
        "block_range": [32766671, 35636955],
        "sample_tx": "0xc186168e12d5afd944b94cdd85e9ad37419dec89e0121ccb45e82b2275613327",
        "sample_txs": [
            "0xc186168e12d5afd944b94cdd85e9ad37419dec89e0121ccb45e82b2275613327",
            "0x56fe4133d2374f656dc40cee627006db49822577fbd2047c7e135e7e0663197c",
            "0xc186e6c8976c14e7f16d4d08195d38e2a98799ba51e7da74c6cec88a8e813c08",
            "0x6dc20ed3bd88bcb59a073e11b7aceb80c770a4a6df7f0d98d6267b002509e141",
            "0x4c3720b72c2c265a30736ad13aa6ea7774856d503732b02885a00bcd03a65834",
        ],
        "chain": "plume",
        "evidence_title": "Plume USDC Transfer logs: 0x1bdb...21ab funded Safe 0xaf8d...b070 with 70.498M USDC before the incident.",
    },
    {
        "source": PLUME_ELIXIR_SAFE,
        "target": PLUME_MORPHO_XUSD_USDC,
        "role": "plume_elixir_usdc_supply",
        "asset": "USDC",
        "amount": 68_016_782.80113,
        "count": 7,
        "block_range": [32778831, 36900000],
        "sample_tx": "0xd14c41ac6459119407c233dbb1f6ac757297fe7ab506e7e933f6a1d5f54a7830",
        "sample_txs": [
            "0xd14c41ac6459119407c233dbb1f6ac757297fe7ab506e7e933f6a1d5f54a7830",
            "0xd7d18f68784bd59e3d1e39813cfdae59d9d652ccf07f99d292aac1dcef4bb786",
            "0xe8e27e1062c8f175989fe93eb01c31c60dc4e19cbf5f0cff6e95732dfc024928",
            "0xcfbd232c430e19c1fbb092b8d693a7a1e355e43e5fc5d306401628cd509ae7ab",
        ],
        "chain": "plume",
        "market_id": "0x82e7ab8ccabaac59b5f397507ed031ebf19a9a5b2657c00c93bc2423cd0a890d",
        "evidence_block": 36900000,
        "evidence_title": "Plume Morpho market() at block 36,900,000: market supply was 68.0168M USDC; Safe 0xaf8d...b070 held essentially all supply shares.",
    },
    {
        "source": STREAM_CLUSTER,
        "target": PLUME_MORPHO_XUSD_USDC,
        "role": "plume_stream_xusd_layerzero_bridge",
        "category": "bridge",
        "asset": "xUSD",
        "amount": 65_740_387.095642,
        "count": 10,
        "block_range": [23551071, 23674856],
        "sample_tx": "0x67712a72adf1deb8315c0b5fbcddd7aba2dc66757dbbe45b07c2d9ce46899d51",
        "sample_txs": [
            "0x67712a72adf1deb8315c0b5fbcddd7aba2dc66757dbbe45b07c2d9ce46899d51",
            "0x0392876c26e4c192ee4a79f5d6c77bf20ee895a756a4c2e2a3bd0651a80ce9d4",
            "0xb3b96365b455c8a4ad59981e217a422bac655f16b17bb9fca7b63185746a67d4",
            "0x14a62c1377a087c253972478422649f6ddaf7b57ed36a660d7259714e0fe9c3c",
            "0xe2510ba261795ece09b477bcee2a66c19c18be2ae11411a5a0864e457008fa05",
            "0xa8651701cfa352619584177c337889a5739f93a86be043389a6c055ec82d3bb9",
        ],
        "chain": "ethereum",
        "market_id": "0x82e7ab8ccabaac59b5f397507ed031ebf19a9a5b2657c00c93bc2423cd0a890d",
        "evidence_title": (
            "LayerZero OFT receipt evidence: Ethereum xUSD OFTSent/Transfer logs burned xUSD from "
            "Stream actor 0x1597...5763, and matching Plume xUSD OFTReceived/Transfer logs minted "
            "the same bridge flow to 0x1597...5763 before the Plume Morpho collateral deposits."
        ),
    },
    {
        "source": STREAM_CLUSTER,
        "target": PLUME_MORPHO_XUSD_USDC,
        "role": "plume_stream_xusd_collateral",
        "asset": "xUSD",
        "amount": 65_840_102.0,
        "count": 11,
        "block_range": [32782416, 35704736],
        "sample_tx": "0x428f7a7d7e0485128ed236ef7b183b22c11b616142e6c870450cf3ca6acf5b88",
        "sample_txs": [
            "0x428f7a7d7e0485128ed236ef7b183b22c11b616142e6c870450cf3ca6acf5b88",
            "0xfed04a8c760934bab5f4a64e2aa1f32d7d3c3eb21ffd79e2bd09ea8f60d9bf81",
            "0xbb13be2f8797619636ffdc639b7b5fcfd539305b25b2d142ac1a14454689be45",
        ],
        "chain": "plume",
        "market_id": "0x82e7ab8ccabaac59b5f397507ed031ebf19a9a5b2657c00c93bc2423cd0a890d",
        "evidence_block": 36900000,
        "evidence_title": "Plume xUSD Transfer + Morpho SupplyCollateral logs: Stream actor posted 65.8401M xUSD as collateral.",
    },
    {
        "source": PLUME_MORPHO_XUSD_USDC,
        "target": STREAM_CLUSTER,
        "role": "plume_stream_usdc_borrow",
        "asset": "USDC",
        "amount": 68_011_177.445289,
        "count": 11,
        "block_range": [32783126, 36900000],
        "sample_tx": "0xd6fc5062dfaf4f00fb38ccf5475a58f03e203ceaacdaa8cee2f7c606f92b131e",
        "sample_txs": [
            "0xd6fc5062dfaf4f00fb38ccf5475a58f03e203ceaacdaa8cee2f7c606f92b131e",
            "0x7e96edfa3633d0daeacd22682d9e1f3406dad79ffec417058f0c3e08883c3e7a",
            "0xe4e7577d9ed3788566bb4d5ca2fbe68a1338f4e5d236c6ec19c67c36341ddb9f",
        ],
        "chain": "plume",
        "market_id": "0x82e7ab8ccabaac59b5f397507ed031ebf19a9a5b2657c00c93bc2423cd0a890d",
        "evidence_block": 36900000,
        "evidence_title": "Plume Morpho position() at block 36,900,000: Stream actor 0x1597...5763 owed 68.0112M USDC against 65.8401M xUSD collateral.",
    },
]

CANONICAL_STRUCTURE_EDGES = [
    {
        "source": ELIXIR_CLUSTER,
        "target": ELIXIR_SDEUSD_STAKING_VAULT,
        "role": "deusd_sdeusd_wrapper_surface",
        "category": "wrapper",
        "asset": "deUSD/sdeUSD",
        "count": 1,
        "chain": "ethereum",
        "evidence_block": ETHEREUM_READ_BLOCK,
        "evidence_title": (
            "Direct eth_call at Ethereum block 25,344,736: sdeUSD contract "
            "asset() returned deUSD 0x15700B564Ca08D9439C58cA5053166E8317aa138."
        ),
    },
    {
        "source": ELIXIR_SDEUSD_STAKING_VAULT,
        "target": MORPHO_SDEUSD_USDC,
        "role": "sdeusd_market_collateral_asset",
        "category": "market_asset",
        "asset": "sdeUSD",
        "count": 1,
        "chain": "ethereum",
        "evidence_title": (
            "Morpho adapter evidence for this market includes Stream sdeUSD collateral logs "
            "and a current sdeUSD collateral snapshot. Loan asset is USDC."
        ),
    },
]


def fmt(value: float) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs_value >= 1_000:
        return f"{value / 1_000:.1f}K"
    if abs_value >= 1:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{value:.4g}"


def presentation_nodes() -> dict[str, dict[str, Any]]:
    return {
        STREAM_CLUSTER: {
            "id": STREAM_CLUSTER,
            "type": "semantic",
            "label": "Stream-controlled actors",
            "data": {
                "kind": "cluster",
                "category": "actor_cluster",
                "is_seed": True,
                "in_cycle": False,
                "member_count": len(STREAM_ACTORS),
                "members": [f"{label} · {address}" for address, label in STREAM_ACTORS.items()],
            },
        },
        STREAM_MINT_SURFACE: {
            "id": STREAM_MINT_SURFACE,
            "type": "semantic",
            "label": "Stream xUSD mint/redeem surface",
            "data": {
                "kind": "protocol",
                "category": "mint_surface",
                "is_seed": True,
                "in_cycle": False,
                "members": [
                    "Durable protocol surface that receives stablecoin funding and issues or burns xUSD",
                    "Self-mint is the actor pattern inferred from edges around this surface, not this node itself",
                ],
            },
        },
        ELIXIR_CLUSTER: {
            "id": ELIXIR_CLUSTER,
            "type": "semantic",
            "label": "Elixir-related actors",
            "data": {
                "kind": "cluster",
                "category": "actor_cluster",
                "is_seed": True,
                "in_cycle": False,
                "member_count": len(ELIXIR_ACTORS),
                "members": [f"{label} · {address}" for address, label in ELIXIR_ACTORS.items()],
            },
        },
        ELIXIR_SDEUSD_STAKING_VAULT: {
            "id": ELIXIR_SDEUSD_STAKING_VAULT,
            "type": "semantic",
            "label": "Elixir sdeUSD staking vault",
            "data": {
                "kind": "protocol",
                "category": "staking_vault",
                "is_seed": True,
                "in_cycle": False,
                "address": "0x5C5b196aBE0d54485975D1Ec29617D42D9198326",
                "chain": "ethereum",
                "members": [
                    "The same contract is the staking vault surface and the sdeUSD receipt token contract",
                    "Direct read: asset() = deUSD 0x1570...a138",
                    "Direct read: convertToAssets(1 sdeUSD) = 1.070566728454991870 deUSD at block 25,344,736",
                ],
            },
        },
        PLUME_ELIXIR_FUNDER: {
            "id": PLUME_ELIXIR_FUNDER,
            "type": "address",
            "label": "Elixir signer / USDC funder",
            "data": {
                "kind": "eoa",
                "category": "operator",
                "is_seed": True,
                "in_cycle": False,
                "address": PLUME_ELIXIR_FUNDER,
                "chain": "plume",
                "members": [
                    "Sent 70.498M Plume USDC to Safe 0xaf8d...b070 before the Stream incident",
                    "Also appears as one owner of the 3-of-5 Safe",
                ],
            },
        },
        PLUME_ELIXIR_SAFE: {
            "id": PLUME_ELIXIR_SAFE,
            "type": "address",
            "label": "Elixir-linked Plume Safe",
            "data": {
                "kind": "safe",
                "category": "lender_cluster",
                "is_seed": True,
                "in_cycle": False,
                "address": PLUME_ELIXIR_SAFE,
                "chain": "plume",
                "members": [
                    "GnosisSafeProxy on Plume",
                    "Safe threshold: 3",
                    "Owners observed onchain: 0xa0d4...e2b5, 0x1bdb...21ab, 0xb42d...5229, 0x7373...4a5, 0xb7de...0357",
                    "Funded with USDC by 0x1bdb...21ab and supplied nearly all USDC into the private xUSD/USDC Morpho market",
                ],
            },
        },
        DEX_ROUTING: {
            "id": DEX_ROUTING,
            "type": "semantic",
            "label": "DEX / solver execution",
            "data": {
                "kind": "protocol",
                "category": "solver",
                "is_seed": True,
                "in_cycle": False,
                "members": ["CoW Protocol, Uniswap routing, and same-tx solver routes observed in receipts"],
            },
        },
        STREAM_BRIDGE_BOUNDARY: {
            "id": STREAM_BRIDGE_BOUNDARY,
            "type": "semantic",
            "label": "Bridge exits / cross-chain wrappers",
            "data": {
                "kind": "protocol",
                "category": "bridge",
                "is_seed": True,
                "in_cycle": False,
                "members": [f"{label} · {address}" for address, label in BRIDGE_TARGETS.items()],
            },
        },
        STREAM_MEV_ROUTING: {
            "id": STREAM_MEV_ROUTING,
            "type": "semantic",
            "label": "MEV / solver counterparties",
            "data": {
                "kind": "protocol",
                "category": "solver",
                "is_seed": True,
                "in_cycle": False,
                "members": [f"{label} · {address}" for address, label in MEV_TARGETS.items()],
            },
        },
        STREAM_AAVE_USDC: {
            "id": STREAM_AAVE_USDC,
            "type": "semantic",
            "label": "Aave V3 USDC position surface",
            "data": {
                "kind": "protocol",
                "category": "lending",
                "is_seed": True,
                "in_cycle": False,
                "members": [f"{label} · {address}" for address, label in AAVE_TARGETS.items()],
            },
        },
        STREAM_PUSD_MINTER: {
            "id": STREAM_PUSD_MINTER,
            "type": "semantic",
            "label": "pUSD minter / tokenized cash surface",
            "data": {
                "kind": "protocol",
                "category": "mint_surface",
                "is_seed": True,
                "in_cycle": False,
                "members": [f"{label} · {address}" for address, label in PUSD_MINTER_TARGETS.items()],
            },
        },
        STREAM_OPAQUE_EXTERNAL: {
            "id": STREAM_OPAQUE_EXTERNAL,
            "type": "semantic",
            "label": "Unlabeled external outflow addresses",
            "data": {
                "kind": "cluster",
                "category": "opaque_boundary",
                "is_seed": True,
                "in_cycle": False,
                "members": [
                    *[f"{label} · {address}" for address, label in OPAQUE_EXTERNAL_TARGETS.items()],
                    "No confirmed CEX deposit label is attached to these endpoints in the current artifact.",
                ],
            },
        },
        PLUME_MORPHO_XUSD_USDC: {
            "id": PLUME_MORPHO_XUSD_USDC,
            "type": "semantic",
            "label": "Plume Morpho xUSD/USDC private market",
            "data": {
                "kind": "market",
                "category": "lending",
                "is_seed": True,
                "in_cycle": False,
                "chain": "plume",
                "market_id": "0x82e7ab8ccabaac59b5f397507ed031ebf19a9a5b2657c00c93bc2423cd0a890d",
                "members": [
                    "Loan token: USDC 0x2223...a7af",
                    "Collateral token: xUSD 0x6eaf...bb4c",
                    "LLTV: 86%",
                    "Block 36,900,000 snapshot: 68.0168M USDC supplied, 68.0168M USDC borrowed, effectively zero idle liquidity",
                    "The material lender is Safe 0xaf8d...b070; the material borrower is Stream actor 0x1597...5763",
                ],
            },
        },
        MORPHO_SDEUSD_USDC: {
            "id": MORPHO_SDEUSD_USDC,
            "type": "semantic",
            "label": "Morpho sdeUSD/USDC market",
            "data": {
                "kind": "market",
                "category": "lending",
                "is_seed": True,
                "in_cycle": False,
                "members": [
                    "Market selected because Stream-controlled actor has onchain Morpho collateral/borrow logs here",
                    "Current Morpho snapshot shows the same Stream actor as the dominant USDC borrower",
                    "Collateral token: sdeUSD vault shares",
                    "Loan token: USDC",
                ],
            },
        },
        METAMORPHO_SUPPLIER_VAULTS: {
            "id": METAMORPHO_SUPPLIER_VAULTS,
            "type": "semantic",
            "label": "MetaMorpho USDC supplier vaults",
            "data": {
                "kind": "cluster",
                "category": "lender_cluster",
                "is_seed": True,
                "in_cycle": False,
                "members": [
                    "Top suppliers from Morpho marketPositions SupplyShares",
                    "Examples checked onchain: Relend USDC, Usual Boosted USDC, Adpend USDC",
                ],
            },
        },
        MORPHO_DEUSD_USDC: {
            "id": MORPHO_DEUSD_USDC,
            "type": "semantic",
            "label": "Morpho deUSD/USDC market",
            "data": {
                "kind": "market",
                "category": "lending",
                "is_seed": True,
                "in_cycle": False,
                "members": [
                    "Market included because the current top supplier is an Elixir-named MetaMorpho vault",
                    "Collateral token: deUSD",
                    "Loan token: USDC",
                ],
            },
        },
        ELIXIR_USDC_VAULT: {
            "id": ELIXIR_USDC_VAULT,
            "type": "address",
            "label": "MEV Capital Elixir USDC vault",
            "data": {
                "kind": "cluster",
                "category": "lender_cluster",
                "is_seed": True,
                "in_cycle": False,
                "address": ELIXIR_USDC_VAULT,
                "members": [
                    "Onchain name(): MEV Capital Elixir USDC",
                    "Onchain symbol(): MC.eUSDC",
                    f"Address: {ELIXIR_USDC_VAULT}",
                ],
            },
        },
    }


def block_range_merge(current: list[int] | None, edge: dict[str, Any]) -> list[int]:
    incoming = edge.get("block_range") or [0, 0]
    if not current or current == [0, 0]:
        return incoming
    if incoming == [0, 0]:
        return current
    return [min(current[0], incoming[0]), max(current[1], incoming[1])]


def add_aggregate(
    grouped: dict[tuple[str, str, str, str], dict[str, Any]],
    *,
    source: str,
    target: str,
    role: str,
    edge: dict[str, Any],
) -> None:
    asset = edge.get("asset") or "asset"
    key = (source, target, role, asset)
    out = grouped.setdefault(key, {
        "id": f"{source}->{target}:{role}:{asset}",
        "source": source,
        "target": target,
        "asset": asset,
        "token": edge.get("token"),
        "amount": 0.0,
        "count": 0,
        "role": role,
        "category": edge.get("category") or "presentation",
        "block_range": edge.get("block_range", [0, 0]),
        "sample_tx": edge.get("sample_tx"),
        "sample_txs": [],
        "semantic_routes": [],
        "method_ids": [],
        "function_names": [],
        "in_cycle": False,
        "morpho": False,
        "mint_burn": source == ZERO or target == ZERO,
        "presentation": True,
    })
    for key_name in ("chain", "market_id", "evidence_block", "source_label", "target_label"):
        if edge.get(key_name) is not None and out.get(key_name) is None:
            out[key_name] = edge.get(key_name)
    out["amount"] += float(edge.get("amount") or 0.0)
    out["count"] += int(edge.get("count") or 0)
    out["block_range"] = block_range_merge(out.get("block_range"), edge)
    for tx_hash in edge.get("sample_txs") or [edge.get("sample_tx")]:
        if tx_hash and tx_hash not in out["sample_txs"] and len(out["sample_txs"]) < 8:
            out["sample_txs"].append(tx_hash)
    if edge.get("sample_tx") and not out.get("sample_tx"):
        out["sample_tx"] = edge.get("sample_tx")
    route = edge.get("evidence_title") or (
        f"Aggregated from onchain evidence edge role={edge.get('role')}; "
        f"source={edge.get('source')}; target={edge.get('target')}; tx={edge.get('sample_tx')}"
    )
    if route not in out["semantic_routes"] and len(out["semantic_routes"]) < 8:
        out["semantic_routes"].append(route)
    for existing_route in edge.get("semantic_routes") or []:
        if existing_route not in out["semantic_routes"] and len(out["semantic_routes"]) < 8:
            out["semantic_routes"].append(existing_route)


def evidence_override(edge: dict[str, Any], *, category: str, title: str) -> dict[str, Any]:
    target = edge.get("target")
    source = edge.get("source")
    sample_tx = edge.get("sample_tx")
    return {
        **edge,
        "category": category,
        "evidence_title": f"{title}; raw source={source}; raw target={target}; sample tx={sample_tx}",
    }


def build_presentation(source: dict[str, Any]) -> dict[str, Any]:
    nodes = presentation_nodes()
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    for edge in source.get("edges") or []:
        role = edge.get("role")
        src = str(edge.get("source") or "").lower()
        dst = str(edge.get("target") or "").lower()
        if role == "possible_self_mint_funding":
            add_aggregate(grouped, source=STREAM_CLUSTER, target=STREAM_MINT_SURFACE, role="stream_stablecoin_funding", edge={**edge, "category": "self_mint_pattern"})
        elif role == "xusd_mint_to_actor":
            add_aggregate(grouped, source=STREAM_MINT_SURFACE, target=STREAM_CLUSTER, role="xusd_mint_to_stream", edge={**edge, "category": "self_mint_pattern"})
        elif role == "xusd_burn_by_actor":
            add_aggregate(grouped, source=STREAM_CLUSTER, target=STREAM_MINT_SURFACE, role="xusd_burn_by_stream", edge={**edge, "category": "self_mint_pattern"})
        elif role == "stream_to_elixir_observed_transfer":
            add_aggregate(grouped, source=STREAM_CLUSTER, target=ELIXIR_CLUSTER, role="stream_to_elixir_transfer", edge=edge)
        elif role == "elixir_to_stream_observed_transfer":
            add_aggregate(grouped, source=ELIXIR_CLUSTER, target=STREAM_CLUSTER, role="elixir_to_stream_transfer", edge=edge)
        elif role == "swap_paid" and src in ELIXIR_ACTORS:
            add_aggregate(grouped, source=ELIXIR_CLUSTER, target=DEX_ROUTING, role="elixir_swap_paid", edge=edge)
        elif role == "swap_received" and dst in ELIXIR_ACTORS:
            add_aggregate(grouped, source=DEX_ROUTING, target=ELIXIR_CLUSTER, role="elixir_swap_received", edge=edge)
        elif role == "burn" and src in ELIXIR_ACTORS:
            add_aggregate(
                grouped,
                source=ELIXIR_CLUSTER,
                target=ELIXIR_SDEUSD_STAKING_VAULT,
                role="elixir_token_burn",
                edge=evidence_override(edge, category="wrapper", title="Elixir actor burn/redeem transfer aggregate"),
            )
        elif role == "mint" and dst in ELIXIR_ACTORS:
            add_aggregate(
                grouped,
                source=ELIXIR_SDEUSD_STAKING_VAULT,
                target=ELIXIR_CLUSTER,
                role="elixir_token_mint",
                edge=evidence_override(edge, category="wrapper", title="Elixir actor mint/issuance transfer aggregate"),
            )
        elif role == "swap_paid" and src in STREAM_ACTORS:
            add_aggregate(grouped, source=STREAM_CLUSTER, target=DEX_ROUTING, role="stream_router_swap_paid", edge=edge)
        elif role == "swap_received" and dst in STREAM_ACTORS:
            add_aggregate(grouped, source=DEX_ROUTING, target=STREAM_CLUSTER, role="stream_router_swap_received", edge=edge)
        elif role == "actor_out" and src in STREAM_ACTORS and dst not in STREAM_ACTORS:
            if dst == STREAM_STABLE_WRAPPER:
                add_aggregate(
                    grouped,
                    source=STREAM_CLUSTER,
                    target=STREAM_MINT_SURFACE,
                    role="stream_stablewrapper_outflow",
                    edge=evidence_override(edge, category="mint_surface", title="Stream actor sent liquid assets to the StableWrapper / withdrawal surface"),
                )
            elif dst in BRIDGE_TARGETS:
                add_aggregate(
                    grouped,
                    source=STREAM_CLUSTER,
                    target=STREAM_BRIDGE_BOUNDARY,
                    role="stream_bridge_outflow",
                    edge=evidence_override(edge, category="bridge", title=f"Stream actor sent assets to {BRIDGE_TARGETS[dst]}"),
                )
            elif dst in MEV_TARGETS:
                add_aggregate(
                    grouped,
                    source=STREAM_CLUSTER,
                    target=STREAM_MEV_ROUTING,
                    role="stream_mev_route_outflow",
                    edge=evidence_override(edge, category="solver", title=f"Stream actor sent assets to {MEV_TARGETS[dst]}"),
                )
            elif dst in AAVE_TARGETS:
                add_aggregate(
                    grouped,
                    source=STREAM_CLUSTER,
                    target=STREAM_AAVE_USDC,
                    role="stream_aave_usdc_position",
                    edge=evidence_override(edge, category="lending", title=f"Stream actor sent USDC to {AAVE_TARGETS[dst]}"),
                )
            elif dst in PUSD_MINTER_TARGETS:
                add_aggregate(
                    grouped,
                    source=STREAM_CLUSTER,
                    target=STREAM_PUSD_MINTER,
                    role="stream_pusd_minter_outflow",
                    edge=evidence_override(edge, category="mint_surface", title=f"Stream actor sent assets to {PUSD_MINTER_TARGETS[dst]}"),
                )
            elif dst in OPAQUE_EXTERNAL_TARGETS:
                add_aggregate(
                    grouped,
                    source=STREAM_CLUSTER,
                    target=STREAM_OPAQUE_EXTERNAL,
                    role="stream_opaque_external_outflow",
                    edge=evidence_override(edge, category="opaque_boundary", title=f"Stream actor sent assets to {OPAQUE_EXTERNAL_TARGETS[dst]}"),
                )
        elif role == "morpho_current_supply_snapshot" and dst == MORPHO_SDEUSD_USDC:
            add_aggregate(grouped, source=METAMORPHO_SUPPLIER_VAULTS, target=MORPHO_SDEUSD_USDC, role="metamorpho_supply_sdeusd_usdc", edge=edge)
        elif role == "morpho_current_supply_snapshot" and dst == MORPHO_DEUSD_USDC:
            add_aggregate(grouped, source=ELIXIR_USDC_VAULT, target=MORPHO_DEUSD_USDC, role="elixir_vault_supply_deusd_usdc", edge=edge)
        elif role == "morpho_collateralize" and src in STREAM_ACTORS and dst == MORPHO_SDEUSD_USDC:
            add_aggregate(grouped, source=STREAM_CLUSTER, target=MORPHO_SDEUSD_USDC, role="stream_sdeusd_collateral", edge=edge)
        elif role == "morpho_borrow" and src == MORPHO_SDEUSD_USDC and dst in STREAM_ACTORS:
            add_aggregate(grouped, source=MORPHO_SDEUSD_USDC, target=STREAM_CLUSTER, role="stream_historical_usdc_borrow", edge=edge)
        elif role == "morpho_current_borrow_snapshot" and src == MORPHO_SDEUSD_USDC and dst in STREAM_ACTORS:
            add_aggregate(grouped, source=MORPHO_SDEUSD_USDC, target=STREAM_CLUSTER, role="stream_current_usdc_borrow", edge=edge)

    for edge in [*CANONICAL_STRUCTURE_EDGES, *PLUME_PRIVATE_MARKET_EDGES]:
        add_aggregate(
            grouped,
            source=edge["source"],
            target=edge["target"],
            role=edge["role"],
            edge=edge,
        )

    edges = list(grouped.values())
    for edge in edges:
        edge["amount"] = round(edge["amount"], 6)
        prefix = ROLE_LABELS.get(edge["role"], edge["role"])
        if edge["amount"]:
            edge["label"] = f"{prefix}: {fmt(edge['amount'])} {edge['asset']} across {edge['count']} transfers"
        else:
            edge["label"] = f"{prefix}: {edge['asset']}"

    stream_to_elixir = [edge for edge in edges if edge["role"] == "stream_to_elixir_transfer"]
    elixir_to_stream = [edge for edge in edges if edge["role"] == "elixir_to_stream_transfer"]
    findings = [
        {
            "id": "finding:presentation:direct-stream-elixir",
            "type": "direct_transfer_evidence",
            "confidence": "exact_onchain_transfer_aggregate",
            "message": "Direct token transfers between Stream observed actors and Elixir observed actors are present in the selected block window.",
            "source": "flow.stream.historical.json",
        },
        {
            "id": "finding:presentation:self-mint-surface",
            "type": "stream_self_mint_pattern",
            "confidence": "onchain_transfer_aggregate",
            "message": "Stream-controlled actors sent USDC/USDT into the xUSD mint surface and xUSD was minted back to Stream-controlled actors in the same scan window.",
            "source": "flow.stream.historical.json",
        },
        {
            "id": "finding:presentation:morpho-stream-borrow",
            "type": "morpho_sdeusd_usdc_borrow",
            "confidence": "receipt_logs_plus_morpho_snapshot",
            "message": "Stream-controlled actor posted sdeUSD collateral and borrowed USDC from the Morpho sdeUSD/USDC market; current Morpho snapshot shows a large remaining USDC borrow.",
            "source": "flow.stream.historical.json",
        },
        {
            "id": "finding:presentation:elixir-named-vault-supply",
            "type": "morpho_elixir_named_vault_supply",
            "confidence": "morpho_snapshot_plus_onchain_name",
            "message": "A MetaMorpho vault whose onchain name is MEV Capital Elixir USDC is the current top supplier in the Morpho deUSD/USDC market.",
            "source": "flow.stream.historical.json",
        },
        {
            "id": "finding:presentation:plume-private-market",
            "type": "plume_xusd_usdc_private_credit_line",
            "confidence": "block_pinned_rpc_plus_decoded_logs",
            "message": "On Plume, an Elixir-linked Safe supplied almost all USDC into a Morpho xUSD/USDC market, while the Stream actor posted xUSD and borrowed almost all USDC.",
            "source": "plume_rpc_and_dune_logs",
        },
        {
            "id": "finding:presentation:stream-xusd-bridge-to-plume",
            "type": "layerzero_oft_bridge_path",
            "confidence": "matching_oftsent_oftreceived_guid",
            "message": "Stream actor bridged xUSD from Ethereum to Plume via LayerZero OFT before posting it as Plume Morpho collateral.",
            "source": "ethereum_and_plume_receipt_logs",
        },
    ]
    return {
        "mode": "flow",
        "nodes": list(nodes.values()),
        "edges": sorted(edges, key=lambda item: (item["source"], item["target"], item["role"], item["asset"])),
        "metadata": {
            "seeds": [STREAM_CLUSTER, STREAM_MINT_SURFACE, ELIXIR_CLUSTER, PLUME_ELIXIR_SAFE, PLUME_MORPHO_XUSD_USDC],
            "from_block": (source.get("metadata") or {}).get("from_block"),
            "to_block": (source.get("metadata") or {}).get("to_block"),
            "plume_evidence_block": 36900000,
            "cycle_nodes": 0,
            "source": "feeder/stream_presentation_flow.py (historical artifact plus fixed block-pinned Plume onchain evidence)",
            "presentation": True,
            "excluded": [
                "Broad Morpho market discovery and unrelated top-position snapshots",
                "raw third-party wallet counterparties",
                "offchain incident narrative edges",
            ],
            "focus": "English presentation graph for Stream <-> Elixir transfers, Stream self-mint evidence, and the Plume Morpho xUSD/USDC private lending market",
            "findings": findings,
            "summary": {
                "stream_to_elixir_edges": len(stream_to_elixir),
                "elixir_to_stream_edges": len(elixir_to_stream),
                "plume_private_market_edges": len(PLUME_PRIVATE_MARKET_EDGES),
                "canonical_structure_edges": len(CANONICAL_STRUCTURE_EDGES),
                "nodes": len(nodes),
                "edges": len(edges),
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    source_path = Path(args.source)
    out_path = Path(args.out)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    payload = build_presentation(source)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"presentation nodes={len(payload['nodes'])} edges={len(payload['edges'])} -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
