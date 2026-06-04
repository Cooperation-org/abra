#!/usr/bin/env python3
"""Component registry — reads `~/.abra/components.yaml`.

abra owns the *catalog* of web components the user trusts on their
view: name, icon, description, where to load the script from, what
schemes (if any) the component handles. Paired with `sources.py`
(the scheme → resolver/embed/auth mapping).

This module is pure config loading. It knows nothing about any
particular component or provider. It does not fetch anything over the
network. The view picks up entries and renders the picker.

File location:
  - $ABRA_COMPONENTS_FILE if set
  - else ~/.abra/components.yaml
  - if neither exists, returns an empty registry.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None


def _components_file_path() -> Path:
    env = os.getenv("ABRA_COMPONENTS_FILE")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".abra" / "components.yaml"


# Mtime-keyed cache: long-running processes pick up yaml edits without
# a restart. lru_cache outlives the file and was a footgun in the view
# shim — chooser served stale entries after every edit.
_LOAD_CACHE: dict = {"mtime": None, "data": {}}


def load_components() -> dict:
    """Read and parse the components file. Re-reads on file mtime change.
    Returns the parsed dict; `{}` if no file exists.
    Raises ImportError if PyYAML is not installed but a file exists."""
    path = _components_file_path()
    if not path.exists():
        if _LOAD_CACHE["mtime"] is not None:
            _LOAD_CACHE["mtime"] = None
            _LOAD_CACHE["data"] = {}
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    if _LOAD_CACHE["mtime"] == mtime:
        return _LOAD_CACHE["data"]
    if yaml is None:
        raise ImportError(
            f"PyYAML is required to read {path}. "
            f"Install it: pip install pyyaml"
        )
    with path.open("r") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a YAML mapping at the top level")
    _LOAD_CACHE["mtime"] = mtime
    _LOAD_CACHE["data"] = data
    return data


def components() -> dict[str, dict]:
    """All registered component entries, keyed by custom-element tag."""
    return load_components().get("components", {}) or {}


def get_component(tag: str) -> Optional[dict]:
    """Returns the registry entry for a custom-element tag (e.g. 'amebo-goal'),
    or None if not registered."""
    return components().get(tag)


def components_for_scheme(scheme_key: str) -> list[dict]:
    """All components that declare they render `scheme_key`. Empty list if
    none. Self-contained components (empty `schemes`) are excluded."""
    out = []
    for tag, entry in components().items():
        schemes = entry.get("schemes") or []
        if scheme_key in schemes:
            row = dict(entry)
            row["tag"] = tag
            out.append(row)
    return out


def reset_cache() -> None:
    """Clear the cached parse. Tests call this between cases. The
    mtime-keyed cache auto-invalidates on file edits, so callers no
    longer need to invoke this in normal operation."""
    _LOAD_CACHE["mtime"] = None
    _LOAD_CACHE["data"] = {}


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1:
        arg = sys.argv[1]
        # If it looks like a scheme key (contains ':' but no '-'), query by scheme.
        if ":" in arg and "-" not in arg:
            print(json.dumps(components_for_scheme(arg), indent=2))
        else:
            print(json.dumps(get_component(arg), indent=2))
    else:
        print(json.dumps(components(), indent=2))
