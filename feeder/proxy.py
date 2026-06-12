"""Proxy detection helpers.

The proxy address remains the asset holder. Implementation metadata is only a
classification hint so balances and delegatecall-based probes keep using the
proxy address.
"""

EIP1967_IMPLEMENTATION_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
EIP1967_BEACON_SLOT = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"
S_IMPLEMENTATION = "0x5c60da1b"  # implementation()

GENERIC_PROXY_NAMES = (
    "proxy",
    "transparentupgradeableproxy",
    "erc1967proxy",
    "uupsproxy",
    "upgradeabilityproxy",
    "initializableadminupgradeabilityproxy",
    "initializableimmutableadminupgradeabilityproxy",
    "ossifiableproxy",
    "l1chugsplashproxy",
    "immutablebeaconproxy",
)


def _addr_from_word(word):
    if not word or word == "0x":
        return None
    h = word[2:] if word.startswith("0x") else word
    if len(h) < 40:
        return None
    addr = "0x" + h[-40:]
    return addr.lower() if int(addr, 16) else None


def _minimal_proxy_impl(code):
    if not code or code == "0x":
        return None
    h = code[2:].lower() if code.startswith("0x") else code.lower()
    # EIP-1167 canonical runtime:
    # 363d3d373d3d3d363d73 <20-byte impl> 5af43d82803e903d91602b57fd5bf3
    needle = "363d3d373d3d3d363d73"
    i = h.find(needle)
    if i < 0:
        return None
    start = i + len(needle)
    end = start + 40
    if len(h) < end:
        return None
    tail = h[end:end + 30]
    if "5af43d82803e903d91602b57fd5bf3"[:20] not in tail:
        return None
    return "0x" + h[start:end]


def _is_generic_proxy_name(name):
    low = (name or "").strip().lower()
    return any(p in low for p in GENERIC_PROXY_NAMES)


def _source_impl(source):
    if not isinstance(source, dict):
        return None
    impl = (source.get("Implementation") or "").strip()
    if impl.startswith("0x") and len(impl) == 42 and int(impl, 16):
        return impl.lower()
    return None


def resolve_proxy(addr, ctx):
    """Return proxy metadata or None.

    ctx keys:
      get_storage(addr, slot) -> hex word
      eth_call(addr, data) -> hex
      get_code(addr) -> hex
      etherscan_source(addr) -> dict
      etherscan_name(addr) -> str
    """
    source = ctx.get("etherscan_source", lambda _a: None)(addr) or {}
    source_name = source.get("ContractName") or ""
    source_proxy = str(source.get("Proxy") or "").strip() == "1"

    impl = _source_impl(source)
    kind = "etherscan" if impl else None

    if not impl:
        word = ctx["get_storage"](addr, EIP1967_IMPLEMENTATION_SLOT)
        impl = _addr_from_word(word)
        if impl:
            kind = "erc1967"

    if not impl:
        beacon_word = ctx["get_storage"](addr, EIP1967_BEACON_SLOT)
        beacon = _addr_from_word(beacon_word)
        if beacon:
            word = ctx["eth_call"](beacon, S_IMPLEMENTATION)
            impl = _addr_from_word(word)
            if impl:
                kind = "beacon"

    if not impl:
        impl = _minimal_proxy_impl(ctx["get_code"](addr))
        if impl:
            kind = "minimal"

    is_proxy = bool(impl or source_proxy or _is_generic_proxy_name(source_name))
    if not is_proxy:
        return None

    impl_label = ctx.get("etherscan_name", lambda _a: "")(impl) if impl else ""
    return {
        "is_proxy": True,
        "proxy_kind": kind or ("etherscan" if source_proxy else "label_hint"),
        "proxy_label": source_name or None,
        "implementation": impl,
        "implementation_label": impl_label or None,
    }
