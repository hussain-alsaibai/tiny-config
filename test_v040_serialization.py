"""Tests for tiny-config v0.4.0 — safe serialization, secret redaction,
frozen views, and JSON Schema export.

Run with: python -m pytest test_v040_serialization.py -q
"""

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tiny_config as tc


class TestToDict(unittest.TestCase):
    """Tests for tc.to_dict — JSON-safe deep copy + secret redaction."""

    def test_basic_copy(self):
        cfg = {"a": 1, "b": {"c": 2, "d": [3, 4]}}
        out = tc.to_dict(cfg)
        self.assertEqual(out, cfg)
        # Mutating the copy does not touch the source
        out["a"] = 99
        out["b"]["c"] = 99
        self.assertEqual(cfg["a"], 1)
        self.assertEqual(cfg["b"]["c"], 2)

    def test_nested_isolation(self):
        cfg = {"x": {"y": {"z": [1, 2]}}}
        out = tc.to_dict(cfg)
        out["x"]["y"]["z"].append(3)
        self.assertEqual(cfg["x"]["y"]["z"], [1, 2])

    def test_string_passthrough(self):
        cfg = {"name": "alice"}
        out = tc.to_dict(cfg)
        self.assertEqual(out["name"], "alice")

    def test_mask_known_secret_keys(self):
        cfg = {
            "db": {"password": "super-secret", "host": "localhost"},
            "api_key": "abc123",
            "token": "tok-456",
        }
        out = tc.to_dict(cfg)
        self.assertEqual(out["db"]["password"], "***")
        self.assertEqual(out["db"]["host"], "localhost")
        self.assertEqual(out["api_key"], "***")
        self.assertEqual(out["token"], "***")

    def test_mask_custom_keys(self):
        cfg = {"oauth": {"client_secret": "shh", "client_id": "id-1"}}
        out = tc.to_dict(cfg, redact=("oauth.client_secret",))
        self.assertEqual(out["oauth"]["client_secret"], "***")
        self.assertEqual(out["oauth"]["client_id"], "id-1")

    def test_disable_heuristic(self):
        cfg = {"api_key": "abc123"}
        out = tc.to_dict(cfg, redact_secret_keys=False)
        self.assertEqual(out["api_key"], "abc123")

    def test_list_of_dicts_masks_secrets(self):
        cfg = {"accounts": [{"name": "a", "token": "t1"}, {"name": "b", "token": "t2"}]}
        out = tc.to_dict(cfg)
        self.assertEqual(out["accounts"][0]["token"], "***")
        self.assertEqual(out["accounts"][1]["token"], "***")
        self.assertEqual(out["accounts"][0]["name"], "a")

    def test_empty_redact_is_noop(self):
        cfg = {"x": 1}
        self.assertEqual(tc.to_dict(cfg, redact=()), cfg)


class TestToJson(unittest.TestCase):
    """Tests for tc.to_json — JSON string with secret redaction."""

    def test_basic(self):
        cfg = {"a": 1, "b": [2, 3]}
        out = tc.to_json(cfg)
        self.assertEqual(json.loads(out), cfg)

    def test_indent(self):
        cfg = {"a": 1}
        out = tc.to_json(cfg, indent=2)
        self.assertIn("\n", out)

    def test_redaction_in_json(self):
        cfg = {"password": "hunter2", "user": "alice"}
        out = tc.to_json(cfg)
        self.assertNotIn("hunter2", out)
        self.assertIn("alice", out)
        self.assertIn("***", out)

    def test_sort_keys(self):
        cfg = {"b": 2, "a": 1}
        out = tc.to_json(cfg, sort_keys=True, indent=None)
        self.assertEqual(out, '{"a": 1, "b": 2}')


class TestMaskSecrets(unittest.TestCase):
    """Tests for tc.mask_secrets — in-place mutation + return."""

    def test_in_place_mutation(self):
        cfg = {"password": "x"}
        result = tc.mask_secrets(cfg)
        # Returns the same instance
        self.assertIs(result, cfg)
        self.assertEqual(cfg["password"], "***")

    def test_custom_keys(self):
        cfg = {"oauth": {"client_secret": "abc"}}
        tc.mask_secrets(cfg, keys=("oauth.client_secret",))
        self.assertEqual(cfg["oauth"]["client_secret"], "***")

    def test_replacement(self):
        cfg = {"api_key": "abc"}
        tc.mask_secrets(cfg, replacement="<REDACTED>")
        self.assertEqual(cfg["api_key"], "<REDACTED>")

    def test_does_not_descend_into_secrets(self):
        """When a key matches, the value is replaced regardless of its type."""
        cfg = {"password": {"nested": "still-secret"}}
        tc.mask_secrets(cfg)
        self.assertEqual(cfg["password"], "***")

    def test_list_descended(self):
        cfg = {"tokens": ["a", "b", "c"]}
        tc.mask_secrets(cfg)
        # 'tokens' is not in the default key set, only token-like keys
        # We test that nested list of dicts with token keys is masked
        cfg2 = {"items": [{"secret": "x"}, {"secret": "y"}]}
        tc.mask_secrets(cfg2)
        self.assertEqual(cfg2["items"][0]["secret"], "***")
        self.assertEqual(cfg2["items"][1]["secret"], "***")


class TestToJsonSchema(unittest.TestCase):
    """Tests for tc.to_json_schema — reverse of validate."""

    def test_simple_object(self):
        cfg = {"name": "alice", "age": 30, "active": True}
        schema = tc.to_json_schema(cfg)
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["properties"]["name"]["type"], "string")
        self.assertEqual(schema["properties"]["age"]["type"], "integer")
        self.assertEqual(schema["properties"]["active"]["type"], "boolean")

    def test_nested_object(self):
        cfg = {"db": {"host": "localhost", "port": 5432}}
        schema = tc.to_json_schema(cfg)
        self.assertIn("db", schema["properties"])
        db = schema["properties"]["db"]
        self.assertEqual(db["type"], "object")
        self.assertEqual(db["properties"]["host"]["type"], "string")
        self.assertEqual(db["properties"]["port"]["type"], "integer")

    def test_arrays(self):
        cfg = {"tags": ["a", "b"], "ports": [80, 443]}
        schema = tc.to_json_schema(cfg)
        self.assertEqual(schema["properties"]["tags"]["type"], "array")
        self.assertEqual(schema["properties"]["tags"]["items"]["type"], "string")
        self.assertEqual(schema["properties"]["ports"]["items"]["type"], "integer")

    def test_array_of_objects(self):
        cfg = {"users": [{"name": "alice", "age": 30}]}
        schema = tc.to_json_schema(cfg)
        items = schema["properties"]["users"]["items"]
        self.assertEqual(items["type"], "object")
        self.assertEqual(items["properties"]["name"]["type"], "string")
        self.assertEqual(items["properties"]["age"]["type"], "integer")

    def test_required_default(self):
        cfg = {"a": 1, "b": 2}
        schema = tc.to_json_schema(cfg)
        self.assertIn("required", schema)
        self.assertIn("a", schema["required"])
        self.assertIn("b", schema["required"])

    def test_required_explicit(self):
        cfg = {"a": 1, "b": 2}
        schema = tc.to_json_schema(cfg, required_keys={"a"})
        self.assertEqual(schema["required"], ["a"])

    def test_title(self):
        schema = tc.to_json_schema({}, title="MyConfig")
        self.assertEqual(schema["title"], "MyConfig")

    def test_null_value_marks_not_required(self):
        cfg = {"a": "hello", "b": None}
        schema = tc.to_json_schema(cfg)
        b_prop = schema["properties"]["b"]
        self.assertEqual(b_prop["type"], "null")
        self.assertTrue(b_prop.get("nullable"))
        # b should NOT be in required (it was None in the sample)
        self.assertNotIn("b", schema.get("required", []))

    def test_schema_version(self):
        schema = tc.to_json_schema({"x": 1})
        self.assertIn("$schema", schema)
        self.assertIn("draft", schema["$schema"])


class TestFrozenConfig(unittest.TestCase):
    """Tests for tc.FrozenConfig — immutable read-only view."""

    def test_get_works(self):
        cfg = {"db": {"host": "localhost", "port": 5432}}
        fc = tc.FrozenConfig(cfg)
        self.assertEqual(fc.get("db.host"), "localhost")
        self.assertEqual(fc.get_int("db.port"), 5432)
        self.assertEqual(fc.get_str("db.host"), "localhost")
        self.assertTrue(fc.get_bool("missing", default=True))

    def test_typed_accessors(self):
        cfg = {
            "int_v": 42,
            "str_v": "hi",
            "bool_v": True,
            "float_v": 3.14,
            "list_v": [1, 2, 3],
            "list_str": "a,b,c",
        }
        fc = tc.FrozenConfig(cfg)
        self.assertEqual(fc.get_int("int_v"), 42)
        self.assertEqual(fc.get_str("str_v"), "hi")
        self.assertIs(fc.get_bool("bool_v"), True)
        self.assertAlmostEqual(fc.get_float("float_v"), 3.14)
        self.assertEqual(fc.get_list("list_v"), [1, 2, 3])
        self.assertEqual(fc.get_list("list_str"), ["a", "b", "c"])

    def test_contains_and_iter(self):
        cfg = {"a": 1, "b": {"c": 2}}
        fc = tc.FrozenConfig(cfg)
        self.assertIn("a", fc)
        self.assertIn("b.c", fc)
        self.assertNotIn("x", fc)
        self.assertEqual(set(iter(fc)), {"a", "b"})

    def test_attribute_assignment_blocked(self):
        fc = tc.FrozenConfig({"a": 1})
        with self.assertRaises(tc.ConfigError):
            fc.new_attr = 1
        with self.assertRaises(tc.ConfigError):
            del fc._cfg

    def test_to_dict_redacts(self):
        cfg = {"password": "x", "name": "alice"}
        fc = tc.FrozenConfig(cfg)
        out = fc.to_dict()
        self.assertEqual(out["password"], "***")
        self.assertEqual(out["name"], "alice")

    def test_to_json_redacts(self):
        cfg = {"api_key": "xyz"}
        fc = tc.FrozenConfig(cfg)
        self.assertNotIn("xyz", fc.to_json())

    def test_keys(self):
        fc = tc.FrozenConfig({"a": 1, "b": 2})
        self.assertEqual(set(fc.keys()), {"a", "b"})

    def test_repr(self):
        fc = tc.FrozenConfig({"a": 1})
        r = repr(fc)
        self.assertIn("FrozenConfig", r)

    def test_independent_of_source(self):
        """Mutating the original dict after wrapping does not change the frozen view."""
        cfg = {"a": 1}
        fc = tc.FrozenConfig(cfg)
        cfg["a"] = 99
        cfg["b"] = 2
        # Snapshot was taken in __init__, so original changes do not leak in.
        self.assertEqual(fc.get("a"), 1)
        self.assertIsNone(fc.get("b"))


class TestIntegration(unittest.TestCase):
    """End-to-end: load → freeze → serialize → redact → log."""

    def test_full_flow(self):
        cfg = tc.load(
            defaults={"db": {"port": 5432, "host": "localhost"}},
        )
        fc = tc.FrozenConfig(cfg)
        # Safe to log
        log_safe = fc.to_json(indent=2)
        self.assertIn("localhost", log_safe)
        # Now mask a secret
        cfg_with_secret = {
            "db": {"host": "localhost", "password": "hunter2"},
            "api_key": "abc",
        }
        safe = tc.to_json(cfg_with_secret)
        self.assertNotIn("hunter2", safe)
        self.assertNotIn("abc", safe)
        self.assertIn("localhost", safe)

    def test_json_schema_to_validator_roundtrip_shape(self):
        """Schema output should be roughly JSON-Schema compatible."""
        cfg = {"name": "test", "count": 5, "tags": ["a"]}
        schema = tc.to_json_schema(cfg)
        # Must have draft-07-$schema identifier
        self.assertTrue(schema["$schema"].startswith("https://json-schema.org/draft/"))
        # Properties must be a dict
        self.assertIsInstance(schema["properties"], dict)
        # Round-trip via JSON
        json.loads(json.dumps(schema))


if __name__ == "__main__":
    unittest.main()