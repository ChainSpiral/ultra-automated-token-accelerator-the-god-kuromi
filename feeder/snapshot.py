"""Shared snapshot block for cache-friendly POC runs."""
import os


# Keep the default aligned with the existing cached crawl artifacts.
DEFAULT_SNAPSHOT_BLOCK = int(
    os.environ.get("DEFI_DAG_SNAPSHOT_BLOCK")
    or os.environ.get("SNAPSHOT_BLOCK")
    or "25242078"
)
