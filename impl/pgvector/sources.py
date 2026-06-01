#!/usr/bin/env python3
"""URI-scheme registry — reads `~/.abra/sources.yaml`.

Per `arch_notes.md`, abra binds names to entries in external systems via
`target_ref` strings shaped like `crm:odoo/contact/12345`. The scheme
prefix (`crm:odoo`) identifies which external system. This module loads
the registry that maps schemes to their `display_name`, `resolver_url`,
embed component, and credential reference.

Source-agnostic on purpose: every scheme — amebo, taiga, odoo, file,
rss, whatever — registers in the same shape with no special-casing.

File location:
  - $ABRA_SOURCES_FILE  if set
  - else ~/.abra/sources.yaml
  - if neither exists, returns an empty registry.

This module knows nothing about any particular scheme. URI splitting is
a pure string helper that callers can use or not.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

# Avoid hard PyYAML dep at import time — only loaded when needed and a
# clear error tells the operator what's missing.
try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None


def _sources_file_path() -> Path:
    env = os.getenv("ABRA_SOURCES_FILE")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".abra" / "sources.yaml"


@lru_cache(maxsize=1)
def load_sources() -> dict:
    """Read and parse the sources file. Cached for the process lifetime.
    Returns the parsed dict; `{}` if no file exists.
    Raises ImportError if PyYAML is not installed but a file exists."""
    path = _sources_file_path()
    if not path.exists():
        return {}
    if yaml is None:
        raise ImportError(
            f"PyYAML is required to read {path}. "
            f"Install it: pip install pyyaml"
        )
    with path.open("r") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a YAML mapping at the top level")
    return data


def schemes() -> dict[str, dict]:
    """All registered scheme entries. Empty dict if none configured."""
    return load_sources().get("schemes", {}) or {}


def get_scheme(scheme_key: str) -> Optional[dict]:
    """Returns the registry entry for a scheme key (e.g. 'amebo:goal'),
    or None if not registered."""
    return schemes().get(scheme_key)


def split_target_ref(target_ref: str) -> tuple[str, str]:
    """Split a target_ref into (scheme_key, path).

      'amebo:goal/42'              → ('amebo:goal', '42')
      'crm:odoo/contact/12345'     → ('crm:odoo', 'contact/12345')
      'amebo:digest'               → ('amebo:digest', '')
      'file:/var/log/foo'          → ('file', '/var/log/foo')

    Pure string utility. Knows NO scheme semantics. Optional — callers
    can use it or parse however they prefer.

    Convention: the scheme key is everything before the first '/' after
    the last ':'. If there is no '/', the whole ref is the scheme. The
    path is whatever follows the first '/', or '' if none.
    """
    if "/" not in target_ref:
        return target_ref, ""
    scheme, _, path = target_ref.partition("/")
    return scheme, path


def reset_cache() -> None:
    """Clear the cached parse. Use after editing the file in a long-running
    process. Tests call this between cases."""
    load_sources.cache_clear()


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1:
        ref = sys.argv[1]
        scheme, path = split_target_ref(ref)
        entry = get_scheme(scheme)
        print(json.dumps({
            "target_ref": ref,
            "scheme": scheme,
            "path": path,
            "registry_entry": entry,
        }, indent=2))
    else:
        print(json.dumps(schemes(), indent=2))
