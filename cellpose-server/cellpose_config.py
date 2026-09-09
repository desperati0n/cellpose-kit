"""Load the shared Cellpose client and service configuration."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path


CONFIG_ROOT = Path(__file__).resolve().parent
EXAMPLE_CONFIG_PATH = CONFIG_ROOT / ".env.example"
LOCAL_CONFIG_PATH = CONFIG_ROOT / ".env"


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE configuration file without modifying the process environment."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise RuntimeError(f"Invalid configuration line {line_number} in {path}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise RuntimeError(f"Empty configuration key on line {line_number} in {path}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def load_config(required: Iterable[str]) -> dict[str, str]:
    """Load template defaults, local configuration, and environment overrides in precedence order."""
    values = _read_env_file(EXAMPLE_CONFIG_PATH)
    values.update(_read_env_file(LOCAL_CONFIG_PATH))
    for key in set(values) | set(required):
        if key in os.environ:
            values[key] = os.environ[key]
    missing = [key for key in required if key not in values]
    if missing:
        names = ", ".join(sorted(missing))
        raise RuntimeError(f"Missing Cellpose configuration values: {names}")
    return values


def config_bool(values: dict[str, str], key: str) -> bool:
    """Convert one named configuration value to a strict boolean."""
    normalized = values[key].strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{key} must be true or false, got {values[key]!r}")


def config_optional_float(values: dict[str, str], key: str) -> float | None:
    """Convert one named configuration value to a float while treating an empty value as unset."""
    value = values[key].strip()
    return None if not value else float(value)
