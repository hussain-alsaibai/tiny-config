# tiny-config

> Zero-dependency configuration loader for Python. JSON / YAML / INI / .env / CLI — one call.

```bash
pip install tiny-config   # coming soon
```

## Why?

- **`pydantic-settings`** — 6 deps, 200 KB
- **`python-dotenv`** — only env files
- **`dynaconf`** — 4 deps, full-featured but heavy

**tiny-config** does the 90% case in a single 350-line file. JSON, YAML (subset), INI, .env, OS env vars, CLI flags — all merged with clear precedence: `defaults < file < env < CLI`.

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
| `load(file, env_prefix, cli, defaults)` | One-call layered loader |
| `load_file(path)` | Auto-detect format by extension |
| `from_env(prefix, separator)` | Read OS env vars as nested dict |
| `merge(*dicts)` | Deep-merge multiple dicts |
| `get(cfg, key, default)` | Get by dotted key (`a.b.c` or `a__b__c`) |
| `set(cfg, key, value)` | Set by dotted key |

## Format support

| Format | Extension | Notes |
|--------|-----------|-------|
| JSON   | `.json`   | full support |
| YAML   | `.yaml`/`.yml` | subset: mappings, lists, scalars (no anchors) |
| INI    | `.ini`    | full support, sections become nested dicts |
| .env   | `.env`    | full support, `KEY=VALUE`, comments with `#` |

## Precedence

```
defaults  <  file (lowest index wins)  <  env vars  <  CLI flags
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
python test_tiny_config.py
# Ran 21 tests in 0.002s — OK
```

## Ecosystem

Part of the **tiny-*** zero-dependency toolkit for Python agent infrastructure:

- [**tiny-router**](https://github.com/hussain-alsaibai/tiny-router) — HTTP router, 76K req/s
- [**tiny-log**](https://github.com/hussain-alsaibai/tiny-log) — structured logging
- [**tiny-validator**](https://github.com/hussain-alsaibai/tiny-validator) — input validation, 247K val/s
- [**tiny-config**](https://github.com/hussain-alsaibai/tiny-config) — layered config loader
- [**tiny-cli**](https://github.com/hussain-alsaibai/tiny-cli) — CLI builder with colors
- [**fast-cache**](https://github.com/hussain-alsaibai/fast-cache) — LRU + TTL + SWR cache
- [**tiny-rate**](https://github.com/hussain-alsaibai/tiny-rate) — rate limiter (token / fixed / sliding)
- [**tiny-retry**](https://github.com/hussain-alsaibai/tiny-retry) — retry + backoff + circuit breaker
- [**tiny-pool**](https://github.com/hussain-alsaibai/tiny-pool) — ThreadPool + AsyncPool
- [**tiny-agent**](https://github.com/hussain-alsaibai/tiny-agent) — zero-dep agent framework
- [**tiny-mcp**](https://github.com/hussain-alsaibai/tiny-mcp) — Model Context Protocol
- [**tiny-embed**](https://github.com/hussain-alsaibai/tiny-embed) — embeddings + vector search
- [**snapdb**](https://github.com/hussain-alsaibai/snapdb) — embedded DB

12 repos, ~5,200 LOC, zero dependencies across the entire stack. All single-file, MIT, fully type-hinted. Built by [OpenClaw](https://github.com/hussain-alsaibai).
## License

MIT © 2026 OpenClaw (hussain-alsaibai)
