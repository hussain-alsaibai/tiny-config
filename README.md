# tiny-config

> Zero-dependency configuration loader for Python. JSON / YAML / INI / .env / CLI / Docker secrets — one call.

```bash
# From GitHub (recommended -- not yet on PyPI)
pip install git+https://github.com/hussain-alsaibai/tiny-config.git
```

Or copy `tiny_config.py` into your project — one file, zero dependencies.

![version 0.2.0](https://img.shields.io/badge/version-0.2.0-blue)

## Why?

- **`pydantic-settings`** — 6 deps, 200 KB
- **`python-dotenv`** — only env files
- **`dynaconf`** — 4 deps, full-featured but heavy

**tiny-config** does the 90% case in a single 550-line file. JSON, YAML (subset), INI, .env, OS env vars, CLI flags, Docker secrets, profile loading, `${env:VAR}` interpolation — all merged with clear precedence: `defaults < file < profile < env < CLI`.

## Features

- ✅ Multiple file formats: JSON, YAML, INI, .env
- ✅ Layered precedence: defaults < file < profile < env < CLI
- ✅ Schema validation
- ✅ Docker secrets loading (`/run/secrets` compatible)
- ✅ Profile loading (dev/staging/prod)
- ✅ `${env:VAR}` interpolation
- ✅ `${secret:NAME}` interpolation
- ✅ CLI flag overrides (`--key=value`)
- ✅ Zero dependencies

## Usage

```python
import tiny_config as tc

# One call: defaults < file < env < CLI
cfg = tc.load(
    file="config.yaml",
    env_prefix="MYAPP",
    defaults={"db": {"port": 5432}, "debug": False},
)

tc.get(cfg, "db.host")       # dotted access
tc.get(cfg, "db__host")      # double-underscore also works
tc.set(cfg, "db.port", 3306)
```

### Schema validation

```python
import tiny_config as tc

cfg = tc.load(
    file="config.yaml",
    validate_schema={
        "db.host": {"type": str, "required": True},
        "db.port": {"type": int, "min": 1, "max": 65535},
        "debug":   {"type": bool, "default": False},
        "level":   {"type": str, "choices": ["info", "warn", "error"]},
    },
)

# Raises ConfigError on validation failure:
# Config validation failed:
#   db.host: required but missing
#   db.port: value 70000 above maximum 65535
```

### Profile loading (dev / staging / prod)

```python
import tiny_config as tc

# Looks for config.production.yaml, config.production.yml, etc.
cfg = tc.load(
    file="config.yaml",
    profile="production",
)
```

Files searched (in order):
- `config.production.yaml`
- `config.production.yml`
- `config.production.json`
- `production.yaml`
- `production.yml`
- ...

### Docker secrets

```python
import tiny_config as tc

# Reads /run/secrets/openai_api_key, then OPENAI_API_KEY env var
api_key = tc.get_secret("openai_api_key")

# Custom path
db_pw = tc.get_secret("db_password", path="/var/secrets")
```

### `${env:VAR}` interpolation

```yaml
# config.yaml
db:
  host: ${env:DB_HOST}
  port: 5432
api_key: ${secret:openai_api_key}
```

```python
cfg = tc.load(file="config.yaml")
# cfg["db"]["host"] is resolved from $DB_HOST
# cfg["api_key"] is resolved from /run/secrets/openai_api_key
```

### CLI as source of truth

```python
# load() automatically reads --key=value from sys.argv
# python myapp.py --db.host=db.example.com --debug=true
cfg = tc.load(file="config.yaml", env_prefix="MYAPP")
```

### Inspect a config file

```bash
$ tiny-config config.yaml
db.host=localhost
db.port=5432
debug=false

$ tiny-config config.yaml db.port
5432
```

## API

| Function | Description |
|----------|-------------|
| `load(file, env_prefix, cli, defaults, validate_schema, profile, interpolate)` | One-call layered loader |
| `load_file(path)` | Auto-detect format by extension |
| `from_env(prefix, separator)` | Read OS env vars as nested dict |
| `merge(*dicts)` | Deep-merge multiple dicts |
| `get(cfg, key, default)` | Get by dotted key (`a.b.c` or `a__b__c`) |
| `set(cfg, key, value)` | Set by dotted key |
| `validate(cfg, schema)` | Validate config against a schema dict |
| `get_secret(key, path)` | Load from Docker secrets or env |
| `load_profile(name, base)` | Load a named profile (dev/staging/prod) |
| `interpolate_env(cfg)` | Replace `${env:VAR}` / `${secret:NAME}` in values |
| `ConfigError` | Exception raised on validation failure |

## Format support

| Format | Extension | Notes |
|--------|-----------|-------|
| JSON   | `.json`   | full support |
| YAML   | `.yaml`/`.yml` | subset: mappings, lists, scalars (no anchors) |
| INI    | `.ini`    | full support, sections become nested dicts |
| .env   | `.env`    | full support, `KEY=VALUE`, comments with `#` |

## Precedence

```
defaults  <  file (lowest index wins)  <  profile  <  env vars  <  CLI flags
```

## Benchmarks

```
== tiny-config benchmarks (n=10,000) ==
  get (3-level)                       2.147 µs/op
  set (3-level)                       0.371 µs/op
  merge (shallow)                     3.718 µs/op
  load_file (json)                   35.292 µs/op
```

## Tests

```bash
python -m pytest test_tiny_config.py -q
# Ran 15 tests in 0.04s — OK
```

## Reports

- [Agent configuration drift: July 2026 field note](reports/2026-07-10-agent-config-drift.md) — why effective-config inspection and clear precedence rules are becoming safety features for autonomous developer workflows.

## Ecosystem

Part of the **tiny-*** zero-dependency toolkit for Python agent infrastructure:

- [**tiny-router**](https://github.com/hussain-alsaibai/tiny-router) — HTTP router, 76K req/s
- [**tiny-log**](https://github.com/hussain-alsaibai/tiny-log) — structured logging
- [**tiny-validator**](https://github.com/hussain-alsaibai/tiny-validator) — input validation, 247K val/s (v0.2.0: JSON Schema import, batch validation)
- [**tiny-config**](https://github.com/hussain-alsaibai/tiny-config) — layered config loader (v0.2.0: validation, secrets, profiles, interpolation)
- [**tiny-cli**](https://github.com/hussain-alsaibai/tiny-cli) — CLI builder with colors
- [**fast-cache**](https://github.com/hussain-alsaibai/fast-cache) — LRU + TTL + SWR cache
- [**tiny-rate**](https://github.com/hussain-alsaibai/tiny-rate) — rate limiter (token / fixed / sliding)
- [**tiny-retry**](https://github.com/hussain-alsaibai/tiny-retry) — retry + backoff + circuit breaker
- [**tiny-pool**](https://github.com/hussain-alsaibai/tiny-pool) — ThreadPool + AsyncPool
- [**tiny-agent**](https://github.com/hussain-alsaibai/tiny-agent) — zero-dep agent framework
- [**tiny-mcp**](https://github.com/hussain-alsaibai/tiny-mcp) — Model Context Protocol
- [**tiny-embed**](https://github.com/hussain-alsaibai/tiny-embed) — embeddings + vector search
- [**tiny-compose**](https://github.com/hussain-alsaibai/tiny-compose) — Stack any decorators in any order, declaratively
- [**tiny-trace**](https://github.com/hussain-alsaibai/tiny-trace) — OTel-compatible tracing, sync + async, W3C propagation
- [**tiny-secret**](https://github.com/hussain-alsaibai/tiny-secret) — Zero-dep secret loader + redacting printer
- [**snapdb**](https://github.com/hussain-alsaibai/snapdb) — embedded DB

15 repos, ~6,400 LOC, zero dependencies across the entire stack. All single-file, MIT, fully type-hinted. - [`tiny-metrics`](https://github.com/hussain-alsaibai/tiny-metrics) — Prometheus metrics
- [`tiny-timeout`](https://github.com/hussain-alsaibai/tiny-timeout) — timeouts that work
- [`tiny-idempotency`](https://github.com/hussain-alsaibai/tiny-idempotency) — idempotency keys

Built by [OpenClaw](https://github.com/hussain-alsaibai).
- [**tiny-cron**](https://github.com/hussain-alsaibai/tiny-cron) — cron-style scheduler + intervals
- [**tiny-flags**](https://github.com/hussain-alsaibai/tiny-flags) — feature flags, percentage rollout
- [**tiny-queue**](https://github.com/hussain-alsaibai/tiny-queue) — persistent FIFO queue, retries
- [**tiny-budget**](https://github.com/hussain-alsaibai/tiny-budget) — runtime cost + token enforcement for AI agents
- [**tiny-eventbus**](https://github.com/hussain-alsaibai/tiny-eventbus) — durable pub/sub with JSONL replay

## Reports

- [Agent Config Provenance Pattern](reports/2026-07-18-agent-config-provenance.md) —
  layered config, routing, thresholds, and budget provenance for autonomous
  developer-tool runs.

## License

MIT © 2026 OpenClaw (hussain-alsaibai)
