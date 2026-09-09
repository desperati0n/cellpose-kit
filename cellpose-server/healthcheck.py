"""Check whether the Cellpose API reports itself as healthy."""

from __future__ import annotations

import json
import urllib.request

from cellpose_config import load_config


def main() -> None:
    """Fail unless the configured health endpoint returns an OK service state."""
    config = load_config(("CELLPOSE_HEALTHCHECK_URL", "CELLPOSE_HEALTHCHECK_TIMEOUT_SECONDS"))
    with urllib.request.urlopen(
        config["CELLPOSE_HEALTHCHECK_URL"],
        timeout=float(config["CELLPOSE_HEALTHCHECK_TIMEOUT_SECONDS"]),
    ) as response:
        payload = json.load(response)
    if payload.get("status") != "ok":
        raise RuntimeError(f"Cellpose service is not ready: {payload}")


if __name__ == "__main__":
    main()
