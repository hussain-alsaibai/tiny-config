"""Tests for the schema-aware config loader (typed.py).

These run against tiny-validator v0.6.0, whose API is Schema-based.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from typed import ConfigError, load_typed, load_with_schema

try:
    from tiny_validator import Boolean, Integer, Schema, String
except ImportError:  # pragma: no cover
    Boolean = Integer = Schema = String = None


@unittest.skipIf(Schema is None, "tiny-validator not installed")
class TestLoadTyped(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def write(self, name, content):
        p = os.path.join(self.tmp, name)
        with open(p, "w") as f:
            f.write(content)
        return p

    def test_no_schema_returns_raw_config(self):
        p = self.write("app.toml", "name = demo\n")
        cfg = load_typed(p, cli=False)
        self.assertEqual(cfg.get("name"), "demo")

    def test_validates_and_returns_dict(self):
        p = self.write("app.toml", 'name = "demo"\nport = "8080"\n')
        schema = Schema({"name": String(), "port": Integer()})
        cfg = load_typed(p, schema=schema, cli=False)
        self.assertEqual(cfg["name"], "demo")
        self.assertEqual(cfg["port"], 8080)
        self.assertIsInstance(cfg["port"], int)

    def test_coerces_boolean_strings(self):
        p = self.write("app.toml", 'debug = "true"\n')
        schema = Schema({"debug": Boolean()})
        cfg = load_typed(p, schema=schema, cli=False)
        self.assertIs(cfg["debug"], True)

    def test_coerces_false_boolean_strings(self):
        p = self.write("app.toml", 'debug = "off"\n')
        schema = Schema({"debug": Boolean()})
        cfg = load_typed(p, schema=schema, cli=False)
        self.assertIs(cfg["debug"], False)

    def test_fills_defaults_for_missing_fields(self):
        p = self.write("app.toml", 'name = "demo"\n')
        schema = Schema({"name": String(), "port": Integer(default=8080)})
        cfg = load_typed(p, schema=schema, cli=False)
        self.assertEqual(cfg["port"], 8080)

    def test_raises_config_error_on_validation_failure(self):
        p = self.write("app.toml", 'port = "not a number"\n')
        schema = Schema({"port": Integer()})
        with self.assertRaises(ConfigError):
            load_typed(p, schema=schema, cli=False)

    def test_config_error_carries_the_errors(self):
        p = self.write("app.toml", 'port = "not a number"\n')
        schema = Schema({"port": Integer()})
        with self.assertRaises(ConfigError) as ctx:
            load_typed(p, schema=schema, cli=False)
        self.assertTrue(ctx.exception.args)
        self.assertIsInstance(ctx.exception.args[0], list)

    def test_missing_required_field_raises(self):
        p = self.write("app.toml", "")
        schema = Schema({"port": Integer()})
        with self.assertRaises(ConfigError):
            load_typed(p, schema=schema, cli=False)

    def test_load_with_schema_is_an_alias(self):
        p = self.write("app.toml", 'port = "8080"\n')
        schema = Schema({"port": Integer()})
        cfg = load_with_schema(p, schema=schema, cli=False)
        self.assertEqual(cfg["port"], 8080)


@unittest.skipIf(Schema is None, "tiny-validator not installed")
class TestCoercion(unittest.TestCase):
    def test_coerces_against_schema(self):
        from typed import _coerce_against_schema

        schema = Schema({"port": Integer(), "debug": Boolean()})
        out = _coerce_against_schema({"port": "80", "debug": "yes"}, schema)
        self.assertEqual(out["port"], 80)
        self.assertIs(out["debug"], True)

    def test_does_not_mutate_source(self):
        from typed import _coerce_against_schema

        src = {"port": "80"}
        schema = Schema({"port": Integer()})
        _coerce_against_schema(src, schema)
        self.assertEqual(src, {"port": "80"})

    def test_uncoercible_value_is_passed_through(self):
        from typed import _coerce_against_schema

        schema = Schema({"port": Integer()})
        out = _coerce_against_schema({"port": "abc"}, schema)
        self.assertEqual(out["port"], "abc")

    def test_missing_fields_are_left_out(self):
        from typed import _coerce_against_schema

        schema = Schema({"port": Integer(default=1)})
        out = _coerce_against_schema({}, schema)
        self.assertNotIn("port", out)

    def test_schema_fields_reads_definition(self):
        from typed import _schema_fields

        schema = Schema({"port": Integer()})
        self.assertIn("port", _schema_fields(schema))


if __name__ == "__main__":
    unittest.main()
