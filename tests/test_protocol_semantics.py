import unittest

from feeder.protocol_semantics import (
    ERC4626_SELECTORS,
    adapter_gap_catalog,
    event_topic,
    parse_aave_spark_api_rows,
    parse_aave_spark_logs,
    parse_erc4626_logs,
    parse_metamorpho_api_rows,
    parse_morpho_api_rows,
    parse_morpho_blue_logs,
    read_erc4626_snapshot,
)


POOL = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
USDC = "0x1111111111111111111111111111111111111111"
AUSDC = "0x1212121212121212121212121212121212121212"
VDUSDC = "0x1313131313131313131313131313131313131313"
COLLATERAL = "0x4444444444444444444444444444444444444444"
USER = "0x2222222222222222222222222222222222222222"
ON_BEHALF = "0x3333333333333333333333333333333333333333"
CALLER = "0x5555555555555555555555555555555555555555"
VAULT = "0x6666666666666666666666666666666666666666"
MORPHO = "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb"
MARKET_ID = "0x" + "ab" * 32
TX = "0x" + "cd" * 32


def topic_addr(addr):
    return "0x" + addr.lower().replace("0x", "").rjust(64, "0")


def word_addr(addr):
    return addr.lower().replace("0x", "").rjust(64, "0")


def word_uint(value):
    return f"{int(value):064x}"


def data_words(*values):
    parts = []
    for value in values:
        if isinstance(value, str) and value.startswith("0x") and len(value) == 42:
            parts.append(word_addr(value))
        else:
            parts.append(word_uint(value))
    return "0x" + "".join(parts)


def reserve_meta():
    return {
        USDC: {
            "symbol": "USDC",
            "decimals": 6,
            "aTokenAddress": AUSDC,
            "variableDebtTokenAddress": VDUSDC,
        }
    }


class ProtocolSemanticsTest(unittest.TestCase):
    def test_aave_borrow_log_tracks_receiver_on_behalf_and_debt_token(self):
        log = {
            "address": POOL,
            "blockNumber": "0x64",
            "transactionHash": TX,
            "logIndex": "0x5",
            "topics": [
                event_topic("Borrow(address,address,address,uint256,uint8,uint256,uint16)"),
                topic_addr(USDC),
                topic_addr(ON_BEHALF),
                word_uint(0),
            ],
            "data": data_words(USER, 5_000_000, 2, 123),
        }

        parsed = parse_aave_spark_logs([log], reserve_meta=reserve_meta())

        self.assertEqual(parsed["gaps"], [])
        event = parsed["events"][0]
        evidence = parsed["evidence"][0]
        self.assertEqual(event["type"], "borrow")
        self.assertEqual(event["receiver"], USER)
        self.assertEqual(event["onBehalfOf"], ON_BEHALF)
        self.assertEqual(event["token"]["amount"], 5)
        self.assertEqual(event["position"]["kind"], "debt_position")
        self.assertEqual(event["position"]["debtToken"], VDUSDC)
        self.assertEqual(evidence["functionSignature"], "Borrow(address,address,address,uint256,uint8,uint256,uint16)")
        self.assertEqual(evidence["rawAmount"], "5000000")

    def test_aave_api_supply_row_tracks_receipt_token_snapshot(self):
        row = {
            "eventName": "Supply",
            "source": "aave-api-fixture",
            "reserve": USDC,
            "amount": "7000000",
            "user": USER,
            "onBehalfOf": ON_BEHALF,
            "pool": POOL,
            "blockNumber": 101,
        }

        parsed = parse_aave_spark_api_rows([row], reserve_meta=reserve_meta())

        event = parsed["events"][0]
        evidence = parsed["evidence"][0]
        self.assertEqual(event["type"], "supply")
        self.assertEqual(event["onBehalfOf"], ON_BEHALF)
        self.assertEqual(event["position"]["receiptToken"], AUSDC)
        self.assertEqual(evidence["confidence"], "inferred_from_snapshot")
        self.assertEqual(evidence["source"], "aave-api-fixture")

    def test_morpho_supply_collateral_log_uses_market_metadata(self):
        market_meta = {
            MARKET_ID: {
                "loanToken": USDC,
                "collateralToken": COLLATERAL,
                "symbol": "wstETH",
                "decimals": 18,
            }
        }
        log = {
            "address": MORPHO,
            "blockNumber": "0xc8",
            "transactionHash": TX,
            "logIndex": "0x2",
            "topics": [
                event_topic("SupplyCollateral(bytes32,address,address,uint256)"),
                MARKET_ID,
                topic_addr(CALLER),
                topic_addr(ON_BEHALF),
            ],
            "data": data_words(2 * 10**18),
        }

        parsed = parse_morpho_blue_logs([log], market_meta=market_meta)

        self.assertEqual(parsed["gaps"], [])
        event = parsed["events"][0]
        self.assertEqual(event["type"], "collateralize")
        self.assertEqual(event["marketId"], MARKET_ID)
        self.assertEqual(event["onBehalfOf"], ON_BEHALF)
        self.assertEqual(event["token"]["tokenAddress"], COLLATERAL)
        self.assertEqual(event["position"]["kind"], "collateral")

    def test_morpho_api_row_emits_supply_and_borrow_snapshot_events(self):
        market_meta = {MARKET_ID: {"loanToken": USDC, "decimals": 6, "symbol": "USDC"}}
        row = {
            "marketUniqueKey": MARKET_ID,
            "user": {"address": ON_BEHALF},
            "supplyAssets": "3000000",
            "supplyShares": "2990000",
            "borrowAssets": "1000000",
            "borrowShares": "1000001",
            "blockNumber": 300,
        }

        parsed = parse_morpho_api_rows([row], market_meta=market_meta)

        self.assertEqual([event["type"] for event in parsed["events"]], ["supply", "borrow"])
        self.assertTrue(all(ev["confidence"] == "inferred_from_snapshot" for ev in parsed["evidence"]))
        self.assertEqual(parsed["events"][1]["position"]["kind"], "borrow_shares")

    def test_metamorpho_api_row_emits_vault_allocation_snapshot(self):
        row = {
            "vault": {"address": VAULT},
            "market": {"uniqueKey": MARKET_ID, "loanAsset": {"address": USDC}},
            "supplyAssets": "9000000",
            "blockNumber": 400,
        }

        parsed = parse_metamorpho_api_rows([row])

        self.assertEqual(parsed["gaps"], [])
        event = parsed["events"][0]
        self.assertEqual(event["adapter"], "metamorpho")
        self.assertEqual(event["type"], "supply")
        self.assertEqual(event["actor"], VAULT)
        self.assertEqual(event["position"]["kind"], "vault_allocation")

    def test_erc4626_deposit_log_tracks_asset_share_relationship(self):
        log = {
            "address": VAULT,
            "blockNumber": "0x1f4",
            "transactionHash": TX,
            "logIndex": "0x1",
            "topics": [
                event_topic("Deposit(address,address,uint256,uint256)"),
                topic_addr(CALLER),
                topic_addr(ON_BEHALF),
            ],
            "data": data_words(11_000_000, 10_000_000),
        }

        parsed = parse_erc4626_logs(
            [log],
            vault_meta={"asset": USDC, "assetDecimals": 6, "assetSymbol": "USDC"},
        )

        event = parsed["events"][0]
        self.assertEqual(event["type"], "vault_share")
        self.assertEqual(event["owner"], ON_BEHALF)
        self.assertEqual(event["assetToken"], USDC)
        self.assertEqual(event["token"]["amount"], 11)
        self.assertEqual(event["position"]["sharesRaw"], "10000000")

    def test_erc4626_read_snapshot_emits_call_evidence(self):
        def eth_call(to, data, block):
            self.assertEqual(to, VAULT)
            self.assertEqual(block, 999)
            if data == ERC4626_SELECTORS["decimals"]:
                return "0x12"
            if data == ERC4626_SELECTORS["asset"]:
                return topic_addr(USDC)
            if data == ERC4626_SELECTORS["totalAssets"]:
                return hex(20_000_000)
            if data == ERC4626_SELECTORS["totalSupply"]:
                return hex(19_000_000)
            if data.startswith(ERC4626_SELECTORS["convertToAssets"]):
                return hex(1_100_000_000_000_000_000)
            return None

        parsed = read_erc4626_snapshot(VAULT, 999, eth_call)

        self.assertEqual(parsed["gaps"], [])
        event = parsed["events"][0]
        self.assertEqual(event["type"], "vault_share")
        self.assertEqual(event["assetToken"], USDC)
        self.assertEqual(event["totalAssetsRaw"], "20000000")
        self.assertEqual(len(parsed["evidence"]), 4)
        self.assertEqual(set(event["evidenceIds"]), {ev["id"] for ev in parsed["evidence"]})

    def test_unsupported_log_returns_gap_not_event(self):
        log = {
            "address": POOL,
            "blockNumber": "0x64",
            "transactionHash": TX,
            "logIndex": "0x9",
            "topics": [event_topic("ReserveDataUpdated(address,uint256,uint256,uint256,uint256,uint256)")],
            "data": "0x",
        }

        parsed = parse_aave_spark_logs([log])

        self.assertEqual(parsed["events"], [])
        self.assertEqual(parsed["gaps"][0]["reason"], "unsupported_aave_spark_event_signature")
        self.assertEqual(parsed["gaps"][0]["topic0"], log["topics"][0])

    def test_gap_catalog_exposes_exact_unsupported_topics(self):
        catalog = adapter_gap_catalog()

        self.assertIn("aave_spark", catalog)
        self.assertIn("morpho_blue", catalog)
        self.assertIn("erc4626", catalog)
        self.assertIn(
            {
                "signature": "Transfer(address,address,uint256)",
                "topic0": event_topic("Transfer(address,address,uint256)"),
            },
            catalog["erc4626"],
        )


if __name__ == "__main__":
    unittest.main()
