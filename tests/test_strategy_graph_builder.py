import json
import tempfile
import unittest
from pathlib import Path

from feeder.bridge_adapters import event_topic
from feeder.strategy_graph import build_for_address, build_for_entity
from feeder.strategy_graph_builder import TRANSFER_TOPIC, ZERO, build_strategy_graph as build_seed_strategy_graph
from feeder.strategy_graph_validator import validate_strategy_graph


SEED = "0x1597e4b7cf6d2877a1d690b6088668afdb045763"
XUSD = "0x1111111111111111111111111111111111111111"
TX = "0x" + "12" * 32
GUID = "0x45daa47d2b58ff8418a2ac6f74e7706cc037885a5bc3fca90fb0b8ca7c0f01b5"


def b32_addr(address):
    return "0x" + address.lower().replace("0x", "").rjust(64, "0")


def word_uint(value):
    return f"{int(value):064x}"


def data_words(*values):
    return "0x" + "".join(word_uint(value) for value in values)


class StrategyGraphBuilderTest(unittest.TestCase):
    def test_address_artifact_becomes_proof_backed_payload(self):
        with tempfile.TemporaryDirectory() as td:
            flow_dir = Path(td)
            address = "0x1111111111111111111111111111111111111111"
            artifact = {
                "nodes": [
                    {"id": f"eoa:{address}", "label": "EOA 0x1111...1111", "type": "eoa", "data": {"kind": "eoa", "address": address}},
                    {"id": "protocol:0x2222222222222222222222222222222222222222", "label": "Aave V3", "type": "protocol", "data": {"kind": "protocol", "address": "0x2222222222222222222222222222222222222222"}},
                ],
                "edges": [
                    {
                        "id": "edge:1",
                        "source": f"eoa:{address}",
                        "target": "protocol:0x2222222222222222222222222222222222222222",
                        "edge_type": "protocol_flow",
                        "category": "lending",
                        "label": "borrow 1 USDC",
                        "details": [
                            {
                                "event_id": "event:1",
                                "tx_hash": "0x" + "a" * 64,
                                "block_number": 123,
                                "category": "lending",
                                "protocol": "Aave V3",
                                "action": "borrow",
                                "transfers": [{"token": "0x3333333333333333333333333333333333333333", "symbol": "USDC", "amount": 1.0}],
                            }
                        ],
                    }
                ],
            }
            (flow_dir / "eoa.seed.0x11111111.d0.json").write_text(json.dumps(artifact), encoding="utf-8")

            payload = build_for_address(address, flow_dir, "0")
            self.assertEqual(validate_strategy_graph(payload), [])
            self.assertEqual(len(payload["edges"]), 1)
            self.assertEqual(len(payload["evidence"]), 1)

    def test_entity_legacy_narrative_edge_is_quarantined(self):
        with tempfile.TemporaryDirectory() as td:
            flow_dir = Path(td)
            legacy = {
                "nodes": [
                    {"id": "0x1111111111111111111111111111111111111111", "label": "A", "data": {"kind": "contract", "address": "0x1111111111111111111111111111111111111111"}},
                    {"id": "0x2222222222222222222222222222222222222222", "label": "B", "data": {"kind": "contract", "address": "0x2222222222222222222222222222222222222222"}},
                ],
                "edges": [
                    {
                        "id": "story-edge",
                        "source": "0x1111111111111111111111111111111111111111",
                        "target": "0x2222222222222222222222222222222222222222",
                        "role": "research_summary",
                    },
                    {
                        "id": "transfer-edge",
                        "source": "0x1111111111111111111111111111111111111111",
                        "target": "0x2222222222222222222222222222222222222222",
                        "asset": "USDC",
                        "token": "0x3333333333333333333333333333333333333333",
                        "amount": 2.0,
                        "count": 1,
                        "sample_tx": "0x" + "b" * 64,
                    },
                ],
                "metadata": {"source": "feeder/flow_trace.py (alchemy_getAssetTransfers)"},
            }
            (flow_dir / "flow.stream.json").write_text(json.dumps(legacy), encoding="utf-8")

            payload = build_for_entity("stream", flow_dir, "0")
            self.assertEqual(validate_strategy_graph(payload), [])
            self.assertEqual([edge["id"] for edge in payload["edges"]], ["legacy:transfer-edge"])
            self.assertTrue(any(gap["kind"] == "narrative_edge_blocked" for gap in payload["gaps"]))

    def test_seed_builder_turns_layerzero_receipt_log_into_bridge_edge(self):
        raw_transfer_logs = [
            {
                "address": XUSD,
                "transactionHash": TX,
                "blockNumber": hex(23_551_071),
                "transactionIndex": "0x1",
                "logIndex": "0x1",
                "topics": [TRANSFER_TOPIC, b32_addr(SEED), b32_addr(ZERO)],
                "data": hex(7_924_656 * 10**18),
            }
        ]
        raw_receipts = [
            {
                "transactionHash": TX,
                "blockNumber": hex(23_551_071),
                "transactionIndex": "0x1",
                "logs": [
                    raw_transfer_logs[0],
                    {
                        "address": XUSD,
                        "transactionHash": TX,
                        "blockNumber": hex(23_551_071),
                        "transactionIndex": "0x1",
                        "logIndex": "0x2",
                        "topics": [
                            event_topic("OFTSent(bytes32,uint32,address,uint256,uint256)"),
                            GUID,
                            b32_addr(SEED),
                        ],
                        "data": data_words(30370, 7_924_656 * 10**18, 7_924_656 * 10**18),
                    },
                ],
            }
        ]

        payload = build_seed_strategy_graph(
            SEED,
            23_551_071,
            23_551_071,
            raw_logs=raw_transfer_logs,
            raw_receipts=raw_receipts,
        )

        self.assertEqual(validate_strategy_graph(payload), [])
        bridge_edges = [edge for edge in payload["edges"] if edge.get("semanticType") == "bridge"]
        self.assertEqual(len(bridge_edges), 1)
        bridge_edge = bridge_edges[0]
        self.assertEqual(bridge_edge["kind"], "bridge_send")
        self.assertEqual(bridge_edge["bridge"], "layerzero_oft")
        self.assertEqual(bridge_edge["destinationChainId"], 98866)
        self.assertEqual(bridge_edge["dstEid"], 30370)
        self.assertEqual(bridge_edge["tokenAddress"], XUSD)
        self.assertEqual(payload["metadata"]["counts"]["bridgeRoutes"], 1)
        self.assertTrue(any(node["kind"] == "bridge_route" for node in payload["nodes"]))

    def test_seed_builder_finds_native_bridge_edge_without_erc20_transfer(self):
        recipient = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        native_bridge_log = {
            "address": "0x9999999999999999999999999999999999999999",
            "transactionHash": "0x" + "34" * 32,
            "blockNumber": hex(123),
            "transactionIndex": "0x1",
            "logIndex": "0x3",
            "topics": [
                event_topic("ETHBridgeInitiated(address,address,uint256,bytes)"),
                b32_addr(SEED),
                b32_addr(recipient),
            ],
            "data": data_words(1_000_000_000_000_000_000, 64, 0),
        }

        payload = build_seed_strategy_graph(
            SEED,
            123,
            123,
            raw_logs=[],
            raw_bridge_logs=[native_bridge_log],
        )

        self.assertEqual(validate_strategy_graph(payload), [])
        bridge_edges = [edge for edge in payload["edges"] if edge.get("semanticType") == "bridge"]
        self.assertEqual(len(bridge_edges), 1)
        self.assertEqual(bridge_edges[0]["kind"], "bridge_send")
        self.assertEqual(bridge_edges[0]["bridge"], "canonical_bridge")
        self.assertEqual(bridge_edges[0]["tokenAddress"], ZERO)
        self.assertEqual(bridge_edges[0]["rawAmount"], "1000000000000000000")
        self.assertFalse(any(gap.get("kind") == "no_erc20_transfer_logs" for gap in payload["gaps"]))


if __name__ == "__main__":
    unittest.main()
