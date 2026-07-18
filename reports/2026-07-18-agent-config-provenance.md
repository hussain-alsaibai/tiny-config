# Agent Config Provenance Pattern - July 18, 2026

## Signal

Production agent stacks increasingly need explainable configuration: which repos
were scanned, which thresholds were used, which destination received the report,
which token budget applied, and which kill switches were active. When that state
lives only in prompts or shell environment, audits become guesswork.

## Pattern

Use `tiny-config` as a layered configuration ledger for autonomous workflows:

```python
from tiny_config import Config

cfg = Config("defaults.json")
cfg.merge("workspace.json")
cfg.load_env(prefix="OPENCLAW_")

repos = cfg.get("developer_tools.repos", [])
thread_id = cfg.get("telegram.projects_thread_id")
min_score = cfg.get("bounty.min_score", 50)
```

Recommended layer order:

1. repo defaults,
2. workspace profile,
3. private machine overrides,
4. environment variables,
5. explicit CLI flags.

## Config Domains

For developer productivity agents, keep these sections separate:

```json
{
  "developer_tools": {
    "repos": ["snapdb", "fast-cache", "tiny-router"],
    "daily_report_count": 3
  },
  "bounty": {
    "min_score": 50,
    "skip_saturated": true
  },
  "messages": {
    "projects_thread_id": 17,
    "failures_thread_id": 14
  },
  "budgets": {
    "cron_usd": 0.05,
    "web_searches": 3
  }
}
```

This keeps route decisions, work selection, and budget limits inspectable.

## Provenance Checklist

- Log the flattened effective config at the start of each run.
- Redact secrets before writing evidence bundles.
- Record which layer last changed a high-impact key.
- Treat message destinations as configuration, not prompt prose.
- Keep bounty scoring thresholds in config so experiments are reviewable.

## Why `tiny-config`

Autonomous workflows benefit from plain files and environment overrides more
than from a settings service. `tiny-config` is small enough to inspect in one
sitting, supports the formats agents already generate, and has dot-notation for
clear access paths.

## Companion Tools

- `tiny-cli` for explicit operator overrides.
- `tiny-log` for effective-config evidence.
- `tiny-secret` for secret loading and redaction.
- `tiny-policy` for enforcing who can change sensitive config domains.

## Last Verified

2026-07-18 - created during the developer tool reports cron after reviewing
production-agent governance trends around configuration, routing, and budgets.
