"""tiny-config: Zero-dependency configuration loader for Python.

Loads from multiple sources with a clear precedence order:
  defaults < file (json/yaml/ini/env) < env vars < CLI overrides

Single file, no deps, MIT, 100% typed, public API in 6 functions.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union

__version__ = "0.1.0"
__all__ = ["load", "load_file", "get", "set", "merge", "from_env"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f"}


def _coerce(value: str) -> Any:
    """Best-effort string → Python type coercion.

    "true" / "false" → bool, "42" → int, "3.14" → float, rest → str.
    Empty strings are preserved as "" (not coerced to None).
    """
    if not isinstance(value, str):
        return value
    s = value.strip()
    low = s.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except ValueError:
            return value
    if re.fullmatch(r"-?\d+\.\d+(?:[eE][-+]?\d+)?", s) or re.fullmatch(
        r"-?\d+[eE][-+]?\d+", s
    ):
        try:
            return float(s)
        except ValueError:
            return value
    return value


def _set_dotted(d: Dict[str, Any], dotted_key: str, value: Any) -> None:
    """Set d["a"]["b"]["c"] = value, creating dicts on the way down."""
    parts = dotted_key.split(".")
    cur = d
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def _get_dotted(d: Mapping[str, Any], dotted_key: str, default: Any = None) -> Any:
    cur: Any = d
    for p in dotted_key.split("."):
        if not isinstance(cur, Mapping) or p not in cur:
            return default
        cur = cur[p]
    return cur


# ---------------------------------------------------------------------------
# File loaders
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level JSON must be an object")
    return data


def _load_ini(path: Path) -> Dict[str, Any]:
    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")
    out: Dict[str, Any] = {}
    if cp.defaults():
        for k, v in cp.defaults().items():
            _set_dotted(out, k, _coerce(v))
    for section in cp.sections():
        out[section] = {}
        for k, v in cp[section].items():
            out[section][k] = _coerce(v)
    return out


def _load_env_file(path: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip().lower()
            val = val.strip().strip('"').strip("'")
            _set_dotted(out, key, _coerce(val))
    return out


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Tiny YAML subset: only key: value mappings, no fancy types.

    Supports:
      key: value
      key:
        nested: value
      key: [a, b, c]
      key: 42
      # comments
    """
    text = path.read_text(encoding="utf-8")
    lines: List[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        lines.append(line)
    parsed, _ = _yaml_parse_block(lines, 0, 0)
    if not isinstance(parsed, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    return parsed


def _yaml_parse_block(lines: Sequence[str], start: int, indent: int) -> Any:
    """Parse a YAML-ish block starting at `start` with given indent.

    Returns (parsed_value, next_line_index).
    """
    # Decide whether this block is a list (starts with `- `) or a mapping.
    is_list = False
    for raw in lines[start:]:
        if not raw.strip():
            continue
        cur_indent = len(raw) - len(raw.lstrip(" "))
        if cur_indent < indent:
            return {}, start
        body = raw[indent:]
        is_list = body.lstrip().startswith("- ")
        break
    result: Any = [] if is_list else {}
    i = start
    while i < len(lines):
        raw = lines[i]
        if not raw.strip():
            i += 1
            continue
        cur_indent = len(raw) - len(raw.lstrip(" "))
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise ValueError(f"line {i + 1}: unexpected indent")
        body = raw[indent:]

        # list item
        if body.lstrip().startswith("- "):
            if not isinstance(result, list):
                raise ValueError(f"line {i + 1}: list under non-list")
            item = body.lstrip()[2:].strip()
            if not item or ":" not in item:
                result.append(_coerce(item))
                i += 1
                continue
            k, _, v = item.partition(":")
            v = v.strip()
            if v == "":
                sub, i = _yaml_parse_block(lines, i + 1, indent + cur_indent + 2)
                result.append({k.strip(): sub})
            else:
                if v.startswith("[") and v.endswith("]"):
                    inner = v[1:-1].strip()
                    result.append({k.strip(): [_coerce(x.strip()) for x in inner.split(",") if x.strip()]})
                else:
                    result.append({k.strip(): _coerce(v)})
                i += 1
            continue

        # key: value
        k, _, v = body.partition(":")
        k = k.strip()
        v = v.strip()
        if not isinstance(result, dict):
            raise ValueError(f"line {i + 1}: dict under non-dict")
        if v == "":
            sub, i = _yaml_parse_block(lines, i + 1, indent + 2)
            result[k] = sub
        else:
            if v.startswith("[") and v.endswith("]"):
                inner = v[1:-1].strip()
                result[k] = [_coerce(x.strip()) for x in inner.split(",") if x.strip()]
            else:
                result[k] = _coerce(v)
            i += 1
    return result, i


def _yaml_is_list_at(lines: Sequence[str], idx: int, indent: int) -> bool:
    for raw in lines[idx:]:
        if not raw.strip():
            continue
        cur_indent = len(raw) - len(raw.lstrip(" "))
        if cur_indent < indent:
            return False
        return raw[indent:].lstrip().startswith("- ")
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_file(path: Union[str, os.PathLike]) -> Dict[str, Any]:
    """Load a single config file, auto-detecting format by extension.

    Supports: .json, .yaml/.yml, .ini, .env
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    suffix = p.suffix.lower()
    if suffix == ".json":
        return _load_json(p)
    if suffix in (".yaml", ".yml"):
        return _load_yaml(p)
    if suffix == ".ini":
        return _load_ini(p)
    if suffix == ".env" or p.name.startswith(".env"):
        return _load_env_file(p)
    # fallback: try json, then env
    try:
        return _load_json(p)
    except json.JSONDecodeError:
        return _load_env_file(p)


def merge(*sources: Mapping[str, Any]) -> Dict[str, Any]:
    """Deep-merge multiple dicts. Later sources override earlier ones."""
    out: Dict[str, Any] = {}
    for src in sources:
        _deep_merge(out, dict(src))
    return out


def _deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> None:
    for k, v in src.items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v


def from_env(prefix: str = "", separator: str = "__") -> Dict[str, Any]:
    """Read env vars and turn them into a nested dict.

    MYAPP_DB__HOST=localhost → {"db": {"host": "localhost"}}
    """
    out: Dict[str, Any] = {}
    plen = len(prefix)
    for key, val in os.environ.items():
        if prefix and not key.startswith(prefix):
            continue
        body = key[plen:] if prefix else key
        body = body.lstrip("_")  # MYAPP__DB__HOST → db__host
        parts = [p.lower() for p in body.split(separator) if p]
        if not parts:
            continue
        d = out
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = _coerce(val)
    return out


def get(cfg: Mapping[str, Any], key: str, default: Any = None) -> Any:
    """Get a value by dotted key. 'a.b.c' or 'a__b__c'."""
    normalized = key.replace("__", ".")
    return _get_dotted(cfg, normalized, default)


def set(cfg: Dict[str, Any], key: str, value: Any) -> None:
    """Set a value by dotted key."""
    _set_dotted(cfg, key, value)


def load(
    file: Optional[Union[str, os.PathLike, Sequence[Union[str, os.PathLike]]]] = None,
    *,
    env_prefix: str = "",
    env_separator: str = "__",
    cli: bool = True,
    defaults: Optional[Mapping[str, Any]] = None,
    schema: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """One-call loader: defaults < file < env < CLI.

    Args:
        file: Path or list of paths to config files (later overrides earlier).
        env_prefix: Only env vars starting with this prefix are read.
        env_separator: Separator inside env var names (default "__" for OS safety).
        cli: If True, parse --key=value from sys.argv[1:].
        defaults: Default values to seed.
        schema: Optional list of dotted keys to also expose as --key flags.

    Returns:
        Merged config dict.
    """
    cfg: Dict[str, Any] = {}
    if defaults:
        _deep_merge(cfg, dict(defaults))
    if file:
        files = [file] if isinstance(file, (str, os.PathLike)) else list(file)
        for fp in files:
            if not Path(fp).exists():
                continue
            _deep_merge(cfg, load_file(fp))
    if env_prefix or env_separator != "__":
        _deep_merge(cfg, from_env(prefix=env_prefix, separator=env_separator))
    if cli:
        cli_overrides = _parse_cli(schema=schema)
        _deep_merge(cfg, cli_overrides)
    return cfg


def _parse_cli(schema: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Parse --key=value and --key value pairs from sys.argv[1:]."""
    out: Dict[str, Any] = {}
    argv = sys.argv[1:]
    allowed = set(schema) if schema else None
    i = 0
    while i < len(argv):
        a = argv[i]
        if not a.startswith("--"):
            i += 1
            continue
        body = a[2:]
        if "=" in body:
            k, _, v = body.partition("=")
        else:
            k = body
            v = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else ""
            if v:
                i += 1
        if allowed and k not in allowed:
            i += 1
            continue
        _set_dotted(out, k, _coerce(v))
        i += 1
    return out


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tiny-config",
        description="Inspect a config file: tiny-config <file> [key]",
    )
    parser.add_argument("file", help="Path to config file")
    parser.add_argument("key", nargs="?", help="Optional dotted key to print")
    parser.add_argument("--format", choices=["json", "flat"], default="flat")
    args = parser.parse_args(argv)
    try:
        cfg = load_file(args.file)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.key:
        v = get(cfg, args.key)
        if v is None:
            print("(not set)", file=sys.stderr)
            return 1
        print(json.dumps(v) if not isinstance(v, str) else v)
        return 0
    if args.format == "json":
        print(json.dumps(cfg, indent=2))
    else:
        for k, v in _flatten(cfg):
            print(f"{k}={v}")
    return 0


def _flatten(d: Mapping[str, Any], prefix: str = "") -> List[str]:
    out: List[str] = []
    for k, v in d.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.extend(_flatten(v, full))
        else:
            out.append(f"{full}={v}")
    return out


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
