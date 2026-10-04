# Changelog

## v0.4.0 — 2026-10-04

New features:
- `to_dict(cfg, redact=..., redact_secret_keys=True)` — JSON-safe deep copy
  with automatic secret-key masking for downstream logging or HTTP calls.
- `to_json(cfg, indent=2, redact=..., sort_keys=False)` — serialize with
  secret redaction. Safe to log without leaking API keys, tokens, or
  passwords.
- `mask_secrets(cfg, keys=..., replacement="***")` — recursive in-place
  redaction. Heuristic covers `password`, `secret`, `api_key`, `token`,
  `access_token`, `refresh_token`, `auth`, `credentials`, `private_key`,
  plus any custom keys you pass.
- `to_json_schema(cfg, required_keys=..., title=...)` — reverse of
  `validate()`. Infers a JSON Schema (draft 2020-12 subset) from a sample
  config. Round-trips with `tiny-validator.from_json_schema()`.
- `FrozenConfig(cfg)` — immutable read-only view. Exposes `.get`,
  `.get_str`, `.get_int`, `.get_bool`, `.get_float`, `.get_list`,
  `.to_dict`, `.to_json`, `.keys`. Blocks attribute writes with
  `ConfigError`. Independent of the source dict (snapshots on init).

Use case (typical):
```python
import tiny_config as tc

cfg = tc.load(file="config.yaml", env_prefix="MYAPP", defaults={...})
app_cfg = tc.FrozenConfig(cfg)
logger.info("config: %s", app_cfg.to_json(indent=2))  # secrets masked
```

Tests: 37 new tests in `test_v040_serialization.py`. Full suite 52 tests,
all passing.

## v0.3.0 — 2026-09

New features:
- Typed accessors: `get_int`, `get_str`, `get_bool`, `get_float`,
  `get_list` — coerce string/number to the expected type automatically.
- `ConfigWatcher` — background thread that polls a config file mtime and
  reloads + invokes an optional callback on change.
- `snapshot(cfg)` — deep copy for safe mutation or comparison.

## v0.2.0 — 2026-08

New features:
- Schema validation (`validate(cfg, schema)`).
- Docker secrets (`get_secret(key, path=...)`).
- Profile loading (`load_profile("prod", base="config.yaml")`).
- `${env:VAR}` and `${secret:NAME}` interpolation.

## v0.1.0 — 2026-07

Initial release. JSON / YAML (subset) / INI / .env parsing. Layered merge.
CLI flag overrides. Zero dependencies.
