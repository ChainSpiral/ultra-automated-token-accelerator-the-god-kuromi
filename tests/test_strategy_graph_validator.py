import unittest

from feeder.strategy_graph_validator import validate_strategy_graph


def valid_payload():
    return {
        "nodes": [
            {"id": "cluster:stream", "kind": "cluster", "label": "Stream cluster"},
            {"id": "market:morpho-weeth-usdc", "kind": "market", "label": "Morpho weETH/USDC"},
        ],
        "evidence": [
            {
                "id": "ev:1",
                "source": "eth_getLogs",
                "adapter": "morpho-blue",
                "confidence": "exact",
                "chainId": 1,
                "blockNumber": 25200000,
                "txHash": "0xabc",
                "logIndex": 7,
                "contractAddress": "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
                "eventName": "SupplyCollateral",
                "tokenAddress": "0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
                "symbol": "weETH",
                "decimals": 18,
                "rawAmount": "1000000000000000000",
                "amount": 1,
            }
        ],
        "edges": [
            {
                "id": "edge:1",
                "source": "cluster:stream",
                "target": "market:morpho-weeth-usdc",
                "kind": "collateralize",
                "evidenceIds": ["ev:1"],
            }
        ],
        "gaps": [],
        "notes": [],
    }


class StrategyGraphValidatorTest(unittest.TestCase):
    def test_accepts_proof_backed_payload(self):
        self.assertEqual(validate_strategy_graph(valid_payload()), [])

    def test_rejects_edge_without_evidence(self):
        payload = valid_payload()
        payload["edges"][0]["evidenceIds"] = []
        errors = validate_strategy_graph(payload)
        self.assertIn("must reference at least one evidence id", "\n".join(errors))

    def test_rejects_missing_evidence_reference(self):
        payload = valid_payload()
        payload["edges"][0]["evidenceIds"] = ["ev:missing"]
        errors = validate_strategy_graph(payload)
        self.assertIn("references missing evidence id", "\n".join(errors))

    def test_rejects_narrative_edge_kind(self):
        payload = valid_payload()
        payload["edges"][0]["kind"] = "incident_context"
        errors = validate_strategy_graph(payload)
        self.assertIn("narrative-only", "\n".join(errors))

    def test_rejects_bad_evidence(self):
        payload = valid_payload()
        payload["evidence"] = [{"id": "ev:bad", "confidence": "manual_research"}]
        payload["edges"][0]["evidenceIds"] = ["ev:bad"]
        errors = "\n".join(validate_strategy_graph(payload))
        self.assertIn("source is required", errors)
        self.assertIn("adapter is required", errors)
        self.assertIn("confidence is invalid", errors)


if __name__ == "__main__":
    unittest.main()
