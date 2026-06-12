"""Mellow vault semantic enrichment.

Mellow vaults use a parent Vault plus multiple Subvault execution accounts.
When a Subvault appears as a token holder, the useful label is usually the
parent share token, not the generic proxy/implementation name.
"""

S_VAULT = "0xfbfa77cf"          # vault()
S_SHARE_MANAGER = "0x5c60173d"  # shareManager()
S_SUBVAULTS = "0xa35f620a"      # subvaults()
S_HAS_SUBVAULT = "0x8333903b"   # hasSubvault(address)
S_NAME = "0x06fdde03"           # name()
S_SYMBOL = "0x95d89b41"         # symbol()

MELLOW_LABELS = {"subvault", "vault", "tokenizedsharemanager"}


def _int(h):
    return int(h, 16) if h and h != "0x" else 0


def _addr_from_word(h):
    if not h or h == "0x":
        return None
    a = "0x" + h[-40:]
    return a.lower() if int(a, 16) else None


def _addr_arg(addr):
    return addr.lower().replace("0x", "").rjust(64, "0")


def _read_str(ctx, addr, selector):
    h = ctx["eth_call"](addr, selector)
    if not h or h == "0x":
        return None
    try:
        b = bytes.fromhex(h[2:])
        if len(b) >= 64:
            n = int.from_bytes(b[32:64], "big")
            if 0 < n <= 200:
                return b[64:64 + n].decode("utf8", "ignore").strip("\x00") or None
        return b.rstrip(b"\x00").decode("utf8", "ignore") or None
    except Exception:
        return None


def _share_info(ctx, share_manager):
    if not share_manager:
        return {}
    return {
        "share_manager": share_manager,
        "share_name": _read_str(ctx, share_manager, S_NAME),
        "share_symbol": _read_str(ctx, share_manager, S_SYMBOL),
    }


def _display(product, role):
    return f"{product} {role}" if product else f"Mellow {role}"


def _product(info):
    name = info.get("share_name")
    symbol = info.get("share_symbol")
    if name and symbol:
        return f"{name} / {symbol}"
    return name or symbol


def resolve(addr, label, ctx):
    """Return Mellow metadata for Vault/Subvault/share-manager addresses."""
    low = (label or "").lower()
    if low not in MELLOW_LABELS:
        return None

    if low == "subvault":
        parent = _addr_from_word(ctx["eth_call"](addr, S_VAULT))
        if not parent:
            return None
        share_manager = _addr_from_word(ctx["eth_call"](parent, S_SHARE_MANAGER))
        info = _share_info(ctx, share_manager)
        product = _product(info)
        if not product:
            return None
        has = bool(_int(ctx["eth_call"](parent, S_HAS_SUBVAULT + _addr_arg(addr))))
        n_subvaults = _int(ctx["eth_call"](parent, S_SUBVAULTS))
        return {
            "protocol": "Mellow",
            "role": "subvault",
            "parent_vault": parent,
            "is_registered_subvault": has,
            "subvault_count": n_subvaults,
            **info,
            "display_label": _display(product, "Subvault"),
        }

    if low == "vault":
        share_manager = _addr_from_word(ctx["eth_call"](addr, S_SHARE_MANAGER))
        info = _share_info(ctx, share_manager)
        product = _product(info)
        if not product:
            return None
        return {
            "protocol": "Mellow",
            "role": "vault",
            "parent_vault": addr.lower(),
            "subvault_count": _int(ctx["eth_call"](addr, S_SUBVAULTS)),
            **info,
            "display_label": _display(product, "Vault"),
        }

    # TokenizedShareManager
    parent = _addr_from_word(ctx["eth_call"](addr, S_VAULT))
    info = _share_info(ctx, addr.lower())
    product = _product(info)
    if not parent or not product:
        return None
    return {
        "protocol": "Mellow",
        "role": "share_manager",
        "parent_vault": parent,
        **info,
        "display_label": _display(product, "ShareManager"),
    }
