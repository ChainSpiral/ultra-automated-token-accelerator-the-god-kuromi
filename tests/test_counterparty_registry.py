import unittest
from unittest.mock import patch

from feeder.counterparty_registry import (
    classify_counterparty,
    classify_token_for_graph,
    counterparty_graph_node,
    should_expand_wallet_cluster,
)
from feeder import eoa_timeline


AAVE_V3_POOL = "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2"
POLONIEX_9 = "0x176f3dab24a159341c0509bb36b833e7fdd0a132"
SEED = "0x1000000000000000000000000000000000000001"
CHILD = "0x2000000000000000000000000000000000000002"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
UNKNOWN_TOKEN = "0x3000000000000000000000000000000000000003"


class CounterpartyRegistryTest(unittest.TestCase):
    def test_protocol_counterparty_is_endpoint_only(self):
        classified = classify_counterparty(AAVE_V3_POOL)

        self.assertTrue(classified["is_known"])
        self.assertEqual(classified["category"], "protocol_contract")
        self.assertTrue(classified["exclude_from_wallet_cluster"])
        self.assertTrue(classified["retain_as_endpoint"])
        self.assertTrue(classified["evidence"])
        self.assertFalse(should_expand_wallet_cluster(AAVE_V3_POOL, "contract"))

        node = counterparty_graph_node(AAVE_V3_POOL)
        self.assertIsNotNone(node)
        self.assertEqual(node["data"]["kind"], "protocol_contract")
        self.assertTrue(node["data"]["evidence"])

    def test_cex_eoa_label_is_not_cluster_expandable(self):
        classified = classify_counterparty(POLONIEX_9)

        self.assertEqual(classified["category"], "cex")
        self.assertTrue(classified["exclude_from_wallet_cluster"])
        self.assertFalse(should_expand_wallet_cluster(POLONIEX_9, "EOA"))

    def test_token_filter_is_deterministic_and_evidence_labeled(self):
        allowed = classify_token_for_graph(WETH, symbol="WETH")
        spoof = classify_token_for_graph(UNKNOWN_TOKEN, symbol="Fake WETH", name="Fake WETH")
        unknown = classify_token_for_graph(UNKNOWN_TOKEN, symbol="TOKEN")

        self.assertTrue(allowed["allowed_for_wallet_cluster"])
        self.assertEqual(allowed["reason"], "local_allowlist")
        self.assertTrue(allowed["evidence"])

        self.assertFalse(spoof["allowed_for_wallet_cluster"])
        self.assertIn("blocked_label_term", spoof["reason"])
        self.assertTrue(spoof["evidence"])

        self.assertFalse(unknown["allowed_for_wallet_cluster"])
        self.assertEqual(unknown["reason"], "low_signal_label")

    def test_dfs_retains_cex_endpoint_without_expanding_it(self):
        visited = []

        def fake_wallet_kind(address, resolve_safe_name=True):
            return "EOA"

        def fake_neighbors(address, start_block, end_block, *, directions, max_neighbors):
            visited.append(address)
            if address == SEED:
                return [
                    {
                        "address": POLONIEX_9,
                        "relation": "out",
                        "symbols": ["WETH"],
                        "transfer_count": 1,
                        "first_block": 1,
                        "last_block": 1,
                        "sample_tx": "0xaaa",
                        "transfers": [],
                    },
                    {
                        "address": CHILD,
                        "relation": "out",
                        "symbols": ["WETH"],
                        "transfer_count": 1,
                        "first_block": 2,
                        "last_block": 2,
                        "sample_tx": "0xbbb",
                        "transfers": [],
                    },
                ]
            if address == CHILD:
                return []
            raise AssertionError(f"DFS should not expand endpoint {address}")

        with patch.object(eoa_timeline, "wallet_kind", side_effect=fake_wallet_kind):
            with patch.object(eoa_timeline, "discover_wallet_neighbors", side_effect=fake_neighbors):
                discovery = eoa_timeline.discover_wallet_dfs(
                    [SEED],
                    1,
                    10,
                    max_depth=2,
                    max_addresses=10,
                    max_neighbors=10,
                    directions="both",
                )

        nodes = {node["address"]: node for node in discovery["nodes"]}
        self.assertEqual(nodes[POLONIEX_9]["cluster_role"], "endpoint")
        self.assertFalse(nodes[POLONIEX_9]["expand_wallet_cluster"])
        self.assertEqual(nodes[POLONIEX_9]["counterparty"]["category"], "cex")
        self.assertEqual(nodes[CHILD]["cluster_role"], "wallet")
        self.assertNotIn(POLONIEX_9, visited)

        view = eoa_timeline.build_eoa_discovery_flow_view(discovery)
        self.assertIn(f"counterparty:{POLONIEX_9}", {node["id"] for node in view["nodes"]})
        self.assertTrue(any(edge.get("counterparty", {}).get("category") == "cex" for edge in view["edges"]))


if __name__ == "__main__":
    unittest.main()
