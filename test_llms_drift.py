"""Doc-drift guard for tiny-config's llms.txt.

On 2026-11-17 `llms.txt` advertised `Version: 0.3.0` against a package at
0.4.2 and never mentioned a single thing added in 0.4.x:

  - `to_json_schema`, the entire reason to hand this library to an agent
  - `mask_secrets`, `get_secret`, `interpolate_env`, `load_profile`,
    `FrozenConfig`
  - the 0.4.2 masking rule (equality-or-suffix, pointers kept)

So the file described the library as it was two minor versions ago, and
omitted the safety behaviour that is the reason to trust it with a config.

The API list is checked in both directions, and the masking table is
asserted against the real function rather than trusted.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import tiny_config as tc

ROOT = Path(__file__).parent
LLMS = ROOT / "llms.txt"
PYPROJECT = ROOT / "pyproject.toml"

DOCUMENTED_API = [
    "load", "load_file", "load_profile", "from_env", "merge",
    "get", "set", "get_int", "get_bool", "get_str", "get_list", "get_float",
    "get_secret", "interpolate_env", "snapshot",
    "ConfigWatcher", "FrozenConfig",
    "to_dict", "to_json", "to_json_schema", "mask_secrets", "validate",
]


def _text() -> str:
    assert LLMS.is_file(), "llms.txt is missing"
    return LLMS.read_text(encoding="utf-8")


def _pyproject_version() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.M)
    assert m, "pyproject.toml has no [project].version"
    return m.group(1)


def _python_floor() -> str:
    m = re.search(r'^requires-python\s*=\s*"([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.M)
    assert m, "pyproject.toml has no requires-python"
    return m.group(1).lstrip(">=~^ ")


def test_version_header_matches_pyproject():
    m = re.search(r"^- Version:\s*(\S+)\s*$", _text(), re.M)
    assert m, "llms.txt has no '- Version:' line"
    assert m.group(1) == _pyproject_version(), (
        f"llms.txt says {m.group(1)}, pyproject.toml says {_pyproject_version()}"
    )


def test_header_matches_module_and_pyproject():
    header = re.search(r"^- Version:\s*(\S+)\s*$", _text(), re.M).group(1)
    assert header == tc.__version__ == _pyproject_version()


def test_python_floor_matches_pyproject():
    m = re.search(r"^- Language:\s*Python \(([^)]+)\)", _text(), re.M)
    assert m, "llms.txt has no '- Language: Python (...)' line"
    assert m.group(1).rstrip("+") == _python_floor(), (
        f"llms.txt claims Python {m.group(1)}, requires-python is {_python_floor()}"
    )


@pytest.mark.parametrize("name", DOCUMENTED_API)
def test_documented_api_present(name):
    assert re.search(rf"\b{re.escape(name)}\b", _text()), (
        f"llms.txt never mentions `{name}`, which this version exports"
    )


@pytest.mark.parametrize("name", DOCUMENTED_API)
def test_listed_names_are_real(name):
    assert hasattr(tc, name), (
        f"llms.txt documents `{name}` but `tiny_config` does not export it"
    )


def test_masking_table_matches_reality():
    """The documented table is the safety contract; assert it, do not trust it."""
    out = tc.mask_secrets({
        "db_password": "hunter2",
        "github_token": "ghp_x",
        "secret_ref": "vault://prod/db-pass",
        "tokenizer": "bpe-50k",
        "password": "vault://prod/db",
    })
    # suffix match: masked even though the key is not exactly "password"
    assert out["db_password"] == "***"
    assert out["github_token"] == "***"
    # substring is the wrong operator: pointers and non-credentials survive
    assert out["secret_ref"] == "vault://prod/db-pass"
    assert out["tokenizer"] == "bpe-50k"
    # an explicitly named secret that is a pointer still survives
    assert out["password"] == "vault://prod/db"


def test_schema_export_is_valid_and_marker_free():
    schema = tc.to_json_schema({"db": {"port": 5432}, "debug": False})
    flat = str(schema)
    assert "$schema" in schema
    assert "nullable" not in flat, "nullable is OpenAPI 3, not draft 2020-12"
    assert "_present" not in flat, "a private marker leaked into the document"
    assert schema["properties"]["db"]["properties"]["port"]["type"] == "integer"
