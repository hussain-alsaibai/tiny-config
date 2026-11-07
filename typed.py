"""Schema-aware configuration loader for tiny-config.

Combines tiny-config's load() with tiny-validator's Schema validation:
    load_typed("app.toml", schema=app_schema) -> validated, defaulted, coerced dict.

Stdlib-only. Optional dependency on tiny-validator (only required when
`schema=` is used; otherwise this module is a no-op import).

Usage::
    from tiny_validator import Schema, String, Integer, Boolean
    from typed import load_typed

    app_schema = Schema({
        "name": String(min_length=1),
        "port": Integer(min_value=1, max_value=65535, default=8080),
        "debug": Boolean(default=False),
    })

    cfg = load_typed("app.toml", schema=app_schema)
    # cfg is a dict with name, port (int), debug (bool) - all defaults filled.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional, Sequence, Union

__all__ = ["load_typed", "load_with_schema", "ConfigError"]


class ConfigError(Exception):
    """Raised when config validation fails."""


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f"}


def _coerce_scalar(value: Any, field: Any) -> Any:
    """Coerce a raw string value to the type the field expects.

    Config files are text: a port arrives as the string "8080" and a flag as
    the string "true". The validator checks types, so the value has to be
    coerced first. A value that cannot be coerced is passed through and the
    validator reports it - coercing must not hide a bad value.
    """
    if value is None:
        return value

    # Already the right type - leave it alone.
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return value

    lowered = value.strip().lower()
    if _is_boolean_field(field):
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        return value

    if _is_integer_field(field):
        try:
            return int(value)
        except (TypeError, ValueError):
            return value

    if _is_float_field(field):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value

    if _is_list_field(field):
        # A list field given a bare string is a single-element list.
        return [value]

    return value


def _field_class_name(field: Any) -> str:
    return type(field).__name__


def _is_boolean_field(field: Any) -> bool:
    return _field_class_name(field) == "Boolean"


def _is_integer_field(field: Any) -> bool:
    return _field_class_name(field) == "Integer"


def _is_float_field(field: Any) -> bool:
    return _field_class_name(field) in ("Float", "Decimal_")


def _is_list_field(field: Any) -> bool:
    return _field_class_name(field) == "List"


def _schema_fields(schema: Any) -> Dict[str, Any]:
    """Return the field mapping of a schema, whatever shape it has.

    tiny-validator v0.6.0 exposes Schema.definition. Older Model classes
    exposed _fields. Both are accepted so this module keeps working if the
    validator API moves again.
    """
    definition = getattr(schema, "definition", None)
    if isinstance(definition, Mapping):
        return dict(definition)
    fields = getattr(schema, "_fields", None)
    if isinstance(fields, Mapping):
        return dict(fields)
    return {}


def _coerce_against_schema(raw: Mapping[str, Any], schema: Any) -> Dict[str, Any]:
    """Coerce each present field in raw to the type its field expects.

    Fields not present in raw are left out so the validator can fill
    defaults.
    """
    fields = _schema_fields(schema)
    if not fields:
        return dict(raw)

    out: Dict[str, Any] = dict(raw)
    for fname, field in fields.items():
        if fname in out:
            out[fname] = _coerce_scalar(out[fname], field)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_typed(
    file: Union[str, "os.PathLike[str]", Sequence[Union[str, "os.PathLike[str]"]]] = None,
    *,
    schema: Any = None,
    env_prefix: str = "",
    env_separator: str = "__",
    cli: bool = True,
    defaults: Optional[Mapping[str, Any]] = None,
    schema_keys: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Load config and validate it against a tiny-validator schema.

    Args:
        file: Path or list of paths (later overrides earlier).
        schema: A tiny-validator Schema. When provided, the merged config
            dict is validated and defaults are filled.
        env_prefix: Only env vars starting with this prefix are read.
        env_separator: Separator inside env var names.
        cli: If True, parse --key=value from sys.argv[1:].
        defaults: Default values to seed.
        schema_keys: Optional list of dotted keys to also expose as --key flags.

    Returns:
        Validated config dict.

    Raises:
        ConfigError: If schema validation fails.
    """
    # Local import to avoid a hard dependency on tiny_config.
    from tiny_config import load as _load

    # tiny_config.load() has its own `schema=` parameter (a list of dotted
    # keys to expose as CLI flags). We map our `schema_keys` onto it.
    cfg = _load(
        file=file,
        env_prefix=env_prefix,
        env_separator=env_separator,
        cli=cli,
        defaults=defaults,
        schema=schema_keys,
    )

    if schema is None:
        return dict(cfg)

    coerced = _coerce_against_schema(cfg, schema)
    errors = schema.validate(coerced)
    if errors:
        raise ConfigError(errors)

    # Materialize defaults for missing keys.
    result: Dict[str, Any] = dict(coerced)
    for key, field in _schema_fields(schema).items():
        if key not in result and getattr(field, "default", Ellipsis) is not Ellipsis:
            result[key] = field.default
    return result


def load_with_schema(
    file: Union[str, "os.PathLike[str]", Sequence[Union[str, "os.PathLike[str]"]]] = None,
    *,
    schema: Any = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Alias for load_typed, for callers who prefer the longer name."""
    return load_typed(file, schema=schema, **kwargs)
