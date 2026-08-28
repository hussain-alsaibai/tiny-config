"""tiny-config: Zero-dependency configuration loader for Python.

Loads from multiple sources with a clear precedence order:
  defaults < file (json/yaml/ini/env) < profile < env vars < CLI overrides

v0.2.0 adds: schema validation, Docker secrets, profile loading, ${env:VAR}
interpolation, ${secret:NAME} interpolation.

Single file, no deps, MIT, 100% typed, public API in 10 functions.
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

__version__ = "0.3.0"


# ---------- Config Errors ----------


class ConfigError(Exception):
    """Raised when config validation fails or required keys are missing."""
    pass


__all__ = [
    "load", "load_file", "get", "set", "merge", "from_env",
    "validate", "get_secret", "load_profile", "ConfigError",
]


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


def _set_nested(cfg: Dict[str, Any], key: str, value: Any) -> None:
    """Set a nested key in a dict, creating intermediate dicts as needed."""
    _set_dotted(cfg, key, value)


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


# ---------------------------------------------------------------------------
# Typed accessors (v0.3.0)
# ---------------------------------------------------------------------------


def get_int(cfg: Mapping[str, Any], key: str, default: int = 0) -> int:
    """Get an int by dotted key, coercing strings/numbers."""
    val = get(cfg, key, default)
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def get_bool(cfg: Mapping[str, Any], key: str, default: bool = False) -> bool:
    """Get a bool by dotted key. Accepts 'true'/'false'/'1'/'0'/'yes'/'no'."""
    val = get(cfg, key, default)
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on", "y", "t"}
    return default


def get_str(cfg: Mapping[str, Any], key: str, default: str = "") -> str:
    """Get a str by dotted key, coercing numbers."""
    val = get(cfg, key, default)
    return str(val) if val is not None else default


def get_list(cfg: Mapping[str, Any], key: str, default: Optional[list] = None) -> list:
    """Get a list by dotted key, splitting comma-separated strings."""
    val = get(cfg, key, default if default is not None else [])
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        return [item.strip() for item in val.split(",") if item.strip()]
    return default if default is not None else []


def get_float(cfg: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    """Get a float by dotted key, coercing strings/numbers."""
    val = get(cfg, key, default)
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Config watching / auto-reload (v0.3.0)
# ---------------------------------------------------------------------------


class ConfigWatcher:
    """Watch a config file for changes and auto-reload.

    Polls mtime periodically (cheap) and re-loads + re-merges when the file
    changes. Useful for agents that need live config without restarting.

    Example:
        from tiny_config import ConfigWatcher, load_file

        watcher = ConfigWatcher("app.json", interval_sec=1.0)
        watcher.start()   # begins polling in a background thread
        cfg = watcher.current()
        # ... edit app.json on disk ...
        cfg = watcher.current()   # picks up changes automatically
        watcher.stop()
    """

    def __init__(self, path: str, *, interval_sec: float = 1.0,
                 on_change: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.path = path
        self.interval_sec = interval_sec
        self.on_change = on_change
        self._cfg: Dict[str, Any] = {}
        self._mtime: Optional[float] = None
        self._stop = False
        self._thread = None

    def start(self) -> "ConfigWatcher":
        """Start the background polling thread."""
        if self._thread and self._thread.is_alive():
            return self
        self._cfg = load_file(self.path)
        self._mtime = self._current_mtime()
        self._stop = False
        import threading
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop = True
        if self._thread:
            self._thread.join(timeout=self.interval_sec * 2 + 0.1)
            self._thread = None

    def current(self) -> Dict[str, Any]:
        """Return the latest config, reloading if the file changed."""
        new_mtime = self._current_mtime()
        if new_mtime is not None and new_mtime != self._mtime:
            self._cfg = load_file(self.path)
            self._mtime = new_mtime
            if self.on_change:
                self.on_change(self._cfg)
        return self._cfg

    def _current_mtime(self) -> Optional[float]:
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return None

    def _poll(self) -> None:
        import time as _t
        while not self._stop:
            _t.sleep(self.interval_sec)
            try:
                self.current()
            except Exception:
                pass


def snapshot(cfg: Mapping[str, Any]) -> Dict[str, Any]:
    """Deep-copy a config dict for safe mutation or comparison."""
    return json.loads(json.dumps(dict(cfg)))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(
    cfg: Dict[str, Any],
    schema: Dict[str, Any],
    *,
    strict: bool = False,
) -> List[Dict[str, Any]]:
    """Validate a config dict against a simple schema.

    Schema format:
        {
            "db.host": {"type": str, "required": True},
            "db.port": {"type": int, "default": 5432},
            "debug": {"type": bool, "default": False},
            "allowed_origins": {"type": list, "required": False},
        }

    Supported spec keys per field:
      - ``type``: Python type to check (e.g. ``str``, ``int``, ``bool``, ``list``).
      - ``required``: bool. If missing and required, an error is reported.
      - ``default``: value to set when the key is missing (optional).
      - ``choices``: iterable of allowed values.
      - ``min`` / ``max``: numeric bounds (inclusive).

    Returns:
        List of errors: [{"key": "db.host", "message": "required but missing"}]

    Raises:
        Nothing — errors are returned so callers can decide how to react.

    Usage:
        errors = validate(cfg, {
            "db.host": {"type": str, "required": True},
            "db.port": {"type": int, "default": 5432},
        })
        if errors:
            for e in errors:
                print(f"Config error: {e['key']}: {e['message']}")
    """
    errors: List[Dict[str, Any]] = []

    def _get_nested(c: Dict[str, Any], key: str) -> tuple[Any, bool]:
        parts = key.split(".")
        val: Any = c
        for part in parts:
            if isinstance(val, dict) and part in val:
                val = val[part]
            else:
                return None, False
        return val, True

    for key, spec in schema.items():
        val, found = _get_nested(cfg, key)
        req = spec.get("required", False)
        typ = spec.get("type")
        default = spec.get("default")

        if not found:
            if req:
                errors.append({"key": key, "message": "required but missing"})
            elif default is not None:
                # Set default via dotted path
                _set_nested(cfg, key, default)
            continue

        if typ and val is not None:
            if not isinstance(val, typ):
                errors.append({
                    "key": key,
                    "message": f"expected {typ.__name__}, got {type(val).__name__}",
                })

        choices = spec.get("choices")
        if choices and val not in choices:
            errors.append({
                "key": key,
                "message": f"value '{val}' not in allowed choices: {list(choices)}",
            })

        min_val = spec.get("min")
        max_val = spec.get("max")
        if min_val is not None and isinstance(val, (int, float)) and not isinstance(val, bool) and val < min_val:
            errors.append({"key": key, "message": f"value {val} below minimum {min_val}"})
        if max_val is not None and isinstance(val, (int, float)) and not isinstance(val, bool) and val > max_val:
            errors.append({"key": key, "message": f"value {val} above maximum {max_val}"})

    return errors


# ---------------------------------------------------------------------------
# Secrets loading
# ---------------------------------------------------------------------------


def get_secret(
    key: str,
    *,
    path: str = "/run/secrets",
    env_fallback: bool = True,
    raise_if_missing: bool = False,
) -> str:
    """Load a secret from Docker secrets or environment.

    Checks, in order:
    1. File at ``{path}/{key}`` (Docker secrets format)
    2. Environment variable ``{KEY}`` (uppercase, underscores)
    3. Environment variable ``{key}`` (as-is)

    Usage:
        secret = get_secret("openai_api_key")
        secret = get_secret("db_password", path="/var/secrets")
    """
    # Docker secret file
    if path:
        secret_file = os.path.join(path, key)
        if os.path.isfile(secret_file):
            with open(secret_file, "r", encoding="utf-8") as f:
                return f.read().strip()

    # Environment variable (uppercase)
    env_key = key.upper().replace("-", "_").replace(".", "_")
    if env_fallback and env_key in os.environ:
        return os.environ[env_key]

    # Environment variable (as-is)
    if env_fallback and key in os.environ:
        return os.environ[key]

    if raise_if_missing:
        raise ConfigError(f"Secret '{key}' not found in {path} or environment")

    return ""


# ---------------------------------------------------------------------------
# Profile loading
# ---------------------------------------------------------------------------


def load_profile(
    name: str,
    *,
    base: str = "config",
    profiles_dir: Optional[str] = None,
    exts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Load a named config profile (e.g. dev, staging, prod).

    Looks for profiles in this order:
    - ``{profiles_dir}/{base}.{name}.{ext}``
    - ``{profiles_dir}/{name}.{ext}``

    If ``profiles_dir`` is None, uses the directory of ``base`` if ``base`` is a path.

    Usage:
        cfg = load_profile("production",
            base="config.yaml",
            profiles_dir=".",
        )
    """
    if exts is None:
        exts = ["yaml", "yml", "json", "ini", "env"]

    base_path = os.path.dirname(base) or "."
    base_name = os.path.splitext(os.path.basename(base))[0]

    candidates = [
        os.path.join(profiles_dir or base_path, f"{base_name}.{name}.{ext}")
        for ext in exts
    ] + [
        os.path.join(profiles_dir or base_path, f"{name}.{ext}")
        for ext in exts
    ]

    for candidate in candidates:
        if os.path.isfile(candidate):
            return load_file(candidate)

    raise ConfigError(
        f"Profile '{name}' not found. Looked in: {candidates}"
    )


# ---------------------------------------------------------------------------
# Expression evaluation in values
# ---------------------------------------------------------------------------


_ENV_RE = re.compile(r"\$\{env:([^}]+)\}")
_SECRET_RE = re.compile(r"\$\{secret:([^}]+)\}")


def interpolate_env(
    cfg: Any,
    *,
    secret_path: str = "/run/secrets",
) -> Any:
    """Recursively replace ``${env:VAR}`` and ``${secret:NAME}`` in config values.

    Returns a new structure with interpolations resolved. String values are
    scanned for ${env:VAR} and ${secret:NAME} tokens; dicts and lists are
    descended into. Other types are returned unchanged.

    Usage:
        cfg = interpolate_env({
            "db": {"host": "${env:DB_HOST}"},
            "api_key": "${secret:openai_api_key}",
        })
    """
    if isinstance(cfg, dict):
        return {k: interpolate_env(v, secret_path=secret_path) for k, v in cfg.items()}
    if isinstance(cfg, list):
        return [interpolate_env(v, secret_path=secret_path) for v in cfg]
    if isinstance(cfg, str):
        def _env_replace(m: "re.Match[str]") -> str:
            var = m.group(1)
            return os.environ.get(var, "")

        def _secret_replace(m: "re.Match[str]") -> str:
            name = m.group(1)
            return get_secret(name, path=secret_path) or os.environ.get(
                name.upper().replace("-", "_"), ""
            )

        cfg = _ENV_RE.sub(_env_replace, cfg)
        cfg = _SECRET_RE.sub(_secret_replace, cfg)
    return cfg


def load(
    file: Optional[Union[str, os.PathLike, Sequence[Union[str, os.PathLike]]]] = None,
    *,
    env_prefix: str = "",
    env_separator: str = "__",
    cli: bool = True,
    defaults: Optional[Mapping[str, Any]] = None,
    validate_schema: Optional[Dict[str, Any]] = None,
    profile: Optional[str] = None,
    interpolate: bool = True,
    secret_path: str = "/run/secrets",
    schema: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Load configuration from multiple sources with layered precedence.

    Precedence (lowest to highest):
        defaults < file < profile < env < CLI args

    Args:
        file: Path to config file (JSON, YAML, INI, .env)
        env_prefix: Prefix for env vars (e.g. "MYAPP" → MYAPP_DEBUG__HOST)
        env_separator: Separator inside env var names (default "__" for OS safety).
        cli: If True, parse --key=value from sys.argv[1:].
        defaults: Default values to seed.
        validate_schema: Schema dict for validation (see :func:`validate`).
        profile: Named profile to load (dev, staging, prod).
        interpolate: Expand ``${env:VAR}`` and ``${secret:NAME}`` in values.
        secret_path: Path to Docker secrets directory.
        schema: Optional list of dotted keys to also expose as ``--key`` flags.

    Returns:
        Merged config dict.

    Usage:
        cfg = load(
            file="config.yaml",
            env_prefix="MYAPP",
            defaults={"db": {"port": 5432}},
            validate_schema={
                "db.host": {"type": str, "required": True},
                "db.port": {"type": int, "min": 1, "max": 65535},
            },
            profile="production",
        )
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
    if profile:
        try:
            base_path = str(file) if isinstance(file, (str, os.PathLike)) else "config.yaml"
            profile_cfg = load_profile(profile, base=base_path)
            _deep_merge(cfg, profile_cfg)
        except ConfigError:
            # Profile not found — surface as validation error during validation
            raise
    if env_prefix or env_separator != "__":
        _deep_merge(cfg, from_env(prefix=env_prefix, separator=env_separator))
    if cli:
        cli_overrides = _parse_cli(schema=schema)
        _deep_merge(cfg, cli_overrides)
    if validate_schema:
        errors = validate(cfg, validate_schema)
        if errors:
            msg = "\n".join(f"  {e['key']}: {e['message']}" for e in errors)
            raise ConfigError(f"Config validation failed:\n{msg}")
    if interpolate:
        cfg = interpolate_env(cfg, secret_path=secret_path)
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
