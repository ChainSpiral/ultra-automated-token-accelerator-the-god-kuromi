import unittest

from feeder.bridge_adapters import (
    event_topic,
    parse_across_logs,
    parse_bridge_logs,
    parse_canonical_bridge_logs,
    parse_cctp_logs,
    parse_ccip_logs,
    parse_layerzero_oft_logs,
    parse_socket_logs,
    parse_stargate_logs,
    parse_wormhole_logs,
    match_bridge_routes,
)


ETH_XUSD = "0x1111111111111111111111111111111111111111"
PLUME_XUSD = "0x2222222222222222222222222222222222222222"
STREAM = "0x1597e4b7cf6d2877a1d690b6088668afdb045763"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
TX1 = "0x" + "11" * 32
TX2 = "0x" + "22" * 32
GUID = "0x45daa47d2b58ff8418a2ac6f74e7706cc037885a5bc3fca90fb0b8ca7c0f01b5"


def b32_addr(address):
    return "0x" + address.lower().replace("0x", "").rjust(64, "0")


def word_uint(value):
    return f"{int(value):064x}"


def data_words(*values):
    return "0x" + "".join(word_uint(value) for value in values)


class BridgeAdaptersTest(unittest.TestCase):
    def test_layerzero_oft_out_to_plume_emits_event_route_and_evidence(self):
        log = {
            "event": "OFTSent",
            "address": ETH_XUSD,
            "transactionHash": TX1,
            "blockNumber": 23_551_071,
            "logIndex": 12,
            "args": {
                "guid": GUID,
                "dstEid": 30370,
                "fromAddress": STREAM,
                "toAddress": b32_addr(STREAM),
                "amountSentLD": "7924656000000000000000000",
            },
        }

        parsed = parse_layerzero_oft_logs([log], chain_id=1)

        self.assertEqual(parsed["gaps"], [])
        self.assertEqual(len(parsed["events"]), 1)
        event = parsed["events"][0]
        route = parsed["routes"][0]
        evidence = parsed["evidence"][0]
        self.assertEqual(event["bridge"], "layerzero_oft")
        self.assertEqual(event["direction"], "out")
        self.assertEqual(event["dstEid"], 30370)
        self.assertEqual(event["destinationChainId"], 98866)
        self.assertEqual(event["recipient"], STREAM)
        self.assertEqual(event["rawAmount"], "7924656000000000000000000")
        self.assertEqual(route["destination_chain_id"], 98866)
        self.assertEqual(route["destination_eid"], 30370)
        self.assertEqual(route["source_tx"], TX1)
        self.assertEqual(route["reason"], "layerzero_oft_out")
        self.assertEqual(evidence["confidence"], "exact")
        self.assertEqual(evidence["adapter"], "bridge-layerzero-oft")

    def test_raw_layerzero_oft_log_is_decoded_before_parsing(self):
        log = {
            "address": ETH_XUSD,
            "transactionHash": TX1,
            "blockNumber": hex(23_551_071),
            "logIndex": hex(12),
            "topics": [
                event_topic("OFTSent(bytes32,uint32,address,uint256,uint256)"),
                GUID,
                b32_addr(STREAM),
            ],
            "data": data_words(30370, 7_924_656 * 10**18, 7_924_656 * 10**18),
        }

        parsed = parse_bridge_logs([log], chain_id=1, source="eth_getTransactionReceipt")

        self.assertEqual(parsed["gaps"], [])
        event = parsed["events"][0]
        self.assertEqual(event["bridge"], "layerzero_oft")
        self.assertEqual(event["direction"], "out")
        self.assertEqual(event["actor"], STREAM)
        self.assertEqual(event["dstEid"], 30370)
        self.assertEqual(event["destinationChainId"], 98866)
        self.assertEqual(event["rawAmount"], str(7_924_656 * 10**18))

    def test_layerzero_oft_in_from_ethereum_matches_out_by_guid(self):
        outbound = parse_layerzero_oft_logs([{
            "event": "OFTSent",
            "address": ETH_XUSD,
            "transactionHash": TX1,
            "blockNumber": 23_551_071,
            "logIndex": 12,
            "args": {
                "guid": GUID,
                "dstEid": 30370,
                "fromAddress": STREAM,
                "toAddress": b32_addr(STREAM),
                "amountSentLD": "7924656000000000000000000",
            },
        }], chain_id=1)
        inbound = parse_layerzero_oft_logs([{
            "event": "OFTReceived",
            "address": PLUME_XUSD,
            "transactionHash": TX2,
            "blockNumber": 32_774_737,
            "logIndex": 20,
            "args": {
                "guid": GUID,
                "srcEid": 30101,
                "toAddress": STREAM,
                "amountReceivedLD": "7924656000000000000000000",
            },
        }], chain_id=98866)

        event = inbound["events"][0]
        self.assertEqual(event["direction"], "in")
        self.assertEqual(event["srcEid"], 30101)
        self.assertEqual(event["sourceChainId"], 1)
        matches = match_bridge_routes(outbound["events"], inbound["events"])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["sourceTx"], TX1)
        self.assertEqual(matches[0]["destinationTx"], TX2)
        self.assertEqual(matches[0]["destinationChainId"], 98866)

    def test_cctp_deposit_for_burn_emits_destination_route(self):
        parsed = parse_cctp_logs([{
            "event": "DepositForBurn",
            "address": "0xbd3fa81b58ba92a82136038b25adec7066af3155",
            "transactionHash": TX1,
            "blockNumber": 100,
            "logIndex": 1,
            "args": {
                "nonce": 7,
                "burnToken": USDC,
                "amount": 1_000_000,
                "depositor": STREAM,
                "mintRecipient": b32_addr(STREAM),
                "destinationDomain": 6,
            },
        }])

        self.assertEqual(parsed["gaps"], [])
        self.assertEqual(parsed["events"][0]["bridge"], "cctp")
        self.assertEqual(parsed["events"][0]["destinationChainId"], 8453)
        self.assertEqual(parsed["routes"][0]["destination_chain_id"], 8453)

    def test_wormhole_token_transfer_emits_route(self):
        parsed = parse_wormhole_logs([{
            "event": "TransferTokens",
            "address": "0x3333333333333333333333333333333333333333",
            "transactionHash": TX1,
            "blockNumber": 101,
            "logIndex": 2,
            "args": {
                "sender": STREAM,
                "recipient": b32_addr(STREAM),
                "targetChain": 30,
                "token": USDC,
                "amount": 2_000_000,
                "sequence": 9,
            },
        }])

        self.assertEqual(parsed["gaps"], [])
        self.assertEqual(parsed["events"][0]["bridge"], "wormhole")
        self.assertEqual(parsed["events"][0]["destinationChainId"], 8453)
        self.assertEqual(parsed["routes"][0]["reason"], "wormhole_token_transfer")

    def test_ccip_send_requested_emits_route(self):
        parsed = parse_ccip_logs([{
            "event": "CCIPSendRequested",
            "address": "0x4444444444444444444444444444444444444444",
            "transactionHash": TX1,
            "blockNumber": 102,
            "logIndex": 3,
            "args": {
                "message": {
                    "messageId": "0x" + "aa" * 32,
                    "sender": STREAM,
                    "receiver": b32_addr(STREAM),
                    "destChainSelector": 15971525489660198786,
                    "tokenAmounts": [{"token": USDC, "amount": 3_000_000}],
                }
            },
        }])

        self.assertEqual(parsed["gaps"], [])
        self.assertEqual(parsed["events"][0]["bridge"], "ccip")
        self.assertEqual(parsed["events"][0]["destinationChainId"], 8453)
        self.assertEqual(parsed["routes"][0]["reason"], "ccip_send_requested")

    def test_across_funds_deposited_emits_route(self):
        parsed = parse_across_logs([{
            "event": "FundsDeposited",
            "address": "0x5555555555555555555555555555555555555555",
            "transactionHash": TX1,
            "blockNumber": 103,
            "logIndex": 4,
            "args": {
                "depositor": STREAM,
                "recipient": STREAM,
                "inputToken": USDC,
                "inputAmount": 4_000_000,
                "destinationChainId": 42161,
                "depositId": 44,
            },
        }])

        self.assertEqual(parsed["gaps"], [])
        self.assertEqual(parsed["events"][0]["bridge"], "across")
        self.assertEqual(parsed["events"][0]["destinationChainId"], 42161)
        self.assertEqual(parsed["routes"][0]["destination_chain_id"], 42161)

    def test_stargate_swap_emits_receipt_confidence_route(self):
        parsed = parse_stargate_logs([{
            "event": "Swap",
            "address": "0x6666666666666666666666666666666666666666",
            "transactionHash": TX1,
            "blockNumber": 104,
            "logIndex": 5,
            "args": {
                "from": STREAM,
                "to": STREAM,
                "amountLD": 5_000_000,
                "dstChainId": 110,
            },
        }])

        self.assertEqual(parsed["gaps"], [])
        self.assertEqual(parsed["events"][0]["bridge"], "stargate")
        self.assertEqual(parsed["events"][0]["direction"], "out")
        self.assertEqual(parsed["evidence"][0]["confidence"], "inferred_from_receipt")

    def test_socket_and_canonical_bridge_decoded_shapes(self):
        socket = parse_socket_logs([{
            "event": "SocketBridge",
            "address": "0x7777777777777777777777777777777777777777",
            "transactionHash": TX1,
            "blockNumber": 105,
            "logIndex": 6,
            "args": {
                "sender": STREAM,
                "receiver": STREAM,
                "token": USDC,
                "amount": 6_000_000,
                "toChainId": 10,
            },
        }])
        canonical = parse_canonical_bridge_logs([{
            "event": "ERC20BridgeInitiated",
            "address": "0x8888888888888888888888888888888888888888",
            "transactionHash": TX2,
            "blockNumber": 106,
            "logIndex": 7,
            "args": {
                "from": STREAM,
                "to": STREAM,
                "l1Token": USDC,
                "l2Token": "0x9999999999999999999999999999999999999999",
                "amount": 7_000_000,
                "l2ChainId": 10,
            },
        }])

        self.assertEqual(socket["gaps"], [])
        self.assertEqual(socket["routes"][0]["destination_chain_id"], 10)
        self.assertEqual(canonical["gaps"], [])
        self.assertEqual(canonical["events"][0]["bridge"], "canonical_bridge")
        self.assertEqual(canonical["routes"][0]["reason"], "canonical_bridge_out")

    def test_raw_canonical_eth_bridge_log_decodes_without_transfer_log(self):
        parsed = parse_bridge_logs([{
            "address": "0x99C9fc46f92E8a1c0deC1b1747d010903E884bE1",
            "transactionHash": TX1,
            "blockNumber": 107,
            "logIndex": 8,
            "topics": [
                event_topic("ETHBridgeInitiated(address,address,uint256,bytes)"),
                b32_addr(STREAM),
                b32_addr("0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
            ],
            "data": data_words(123456789, 64, 0),
        }])

        self.assertEqual(parsed["gaps"], [])
        event = parsed["events"][0]
        self.assertEqual(event["bridge"], "canonical_bridge")
        self.assertEqual(event["direction"], "out")
        self.assertEqual(event["actor"], STREAM)
        self.assertEqual(event["recipient"], "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        self.assertEqual(event["tokenAddress"], "0x0000000000000000000000000000000000000000")
        self.assertEqual(event["rawAmount"], "123456789")
        self.assertEqual(event["destinationChainId"], 10)
        self.assertEqual(parsed["routes"][0]["destination_chain_id"], 10)

    def test_parse_bridge_logs_routes_supported_families_and_gaps_unknown_rows(self):
        parsed = parse_bridge_logs([
            {
                "event": "OFTSent",
                "address": ETH_XUSD,
                "transactionHash": TX1,
                "blockNumber": 23_551_071,
                "logIndex": 12,
                "args": {"guid": GUID, "dstEid": 30370, "fromAddress": STREAM, "toAddress": b32_addr(STREAM), "amountSentLD": 1},
            },
            {
                "event": "Swap",
                "address": ETH_XUSD,
                "transactionHash": TX2,
                "blockNumber": 23_551_072,
                "logIndex": 13,
                "args": {"sender": STREAM, "recipient": STREAM, "amount0": 1, "amount1": -1},
            },
        ])

        self.assertEqual(len(parsed["events"]), 1)
        self.assertEqual(len(parsed["routes"]), 1)
        self.assertEqual(len(parsed["gaps"]), 1)
        self.assertEqual(parsed["gaps"][0]["reason"], "unsupported_or_undecoded_bridge_log")


if __name__ == "__main__":
    unittest.main()
