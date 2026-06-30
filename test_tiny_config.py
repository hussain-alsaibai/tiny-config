"""Tests for tiny-config — run with `python test_tiny_config.py`."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tiny_config as tc


class TestCoerce(unittest.TestCase):
    def test_bool(self):
        self.assertIs(tc._coerce("true"), True)
        self.assertIs(tc._coerce("FALSE"), False)
        self.assertIs(tc._coerce("yes"), True)
        self.assertIs(tc._coerce("off"), False)

    def test_int(self):
        self.assertEqual(tc._coerce("42"), 42)
        self.assertEqual(tc._coerce("-7"), -7)

    def test_float(self):
        self.assertEqual(tc._coerce("3.14"), 3.14)
        self.assertEqual(tc._coerce("1e3"), 1000.0)

    def test_string_passthrough(self):
        self.assertEqual(tc._coerce("hello"), "hello")
        self.assertEqual(tc._coerce(""), "")


class TestDotted(unittest.TestCase):
    def test_set_get(self):
        d = {}
        tc._set_dotted(d, "a.b.c", 1)
        self.assertEqual(d, {"a": {"b": {"c": 1}}})
        self.assertEqual(tc._get_dotted(d, "a.b.c"), 1)
        self.assertIsNone(tc._get_dotted(d, "a.x.y"))
        self.assertEqual(tc._get_dotted(d, "a.x.y", "default"), "default")


class TestGetSetPublic(unittest.TestCase):
    def test_get_set(self):
        cfg = {"a": {"b": 1}}
        self.assertEqual(tc.get(cfg, "a.b"), 1)
        tc.set(cfg, "a.c", 2)
        self.assertEqual(cfg["a"]["c"], 2)
        self.assertEqual(tc.get(cfg, "a__c"), 2)


class TestMerge(unittest.TestCase):
    def test_deep_override(self):
        a = {"x": {"y": 1, "z": 2}}
        b = {"x": {"y": 99, "w": 3}, "k": 4}
        m = tc.merge(a, b)
        self.assertEqual(m, {"x": {"y": 99, "z": 2, "w": 3}, "k": 4})


class TestFromEnv(unittest.TestCase):
    def test_prefix_and_nesting(self):
        os.environ["MYAPP_DB__HOST"] = "localhost"
        os.environ["MYAPP_DB__PORT"] = "5432"
        os.environ["OTHER"] = "ignored"
        try:
            d = tc.from_env(prefix="MYAPP")
            self.assertEqual(d, {"db": {"host": "localhost", "port": 5432}})
        finally:
            del os.environ["MYAPP_DB__HOST"]
            del os.environ["MYAPP_DB__PORT"]
            del os.environ["OTHER"]


class TestFileLoaders(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_json(self):
        p = Path(self.tmp) / "c.json"
        p.write_text(json.dumps({"a": 1, "b": {"c": 2}}))
        self.assertEqual(tc.load_file(p), {"a": 1, "b": {"c": 2}})

    def test_ini(self):
        p = Path(self.tmp) / "c.ini"
        p.write_text(
            "[DEFAULT]\nname=alice\n[db]\nhost=localhost\nport=5432\n"
        )
        d = tc.load_file(p)
        self.assertEqual(d["name"], "alice")
        self.assertEqual(d["db"]["host"], "localhost")
        self.assertEqual(d["db"]["port"], 5432)

    def test_env_file(self):
        p = Path(self.tmp) / ".env"
        p.write_text("# comment\nAPP_PORT=8080\nAPP_DEBUG=true\n")
        d = tc.load_file(p)
        self.assertEqual(d["app_port"], 8080)
        self.assertIs(d["app_debug"], True)

    def test_yaml(self):
        p = Path(self.tmp) / "c.yaml"
        p.write_text(
            "name: alice\n"
            "age: 30\n"
            "active: true\n"
            "db:\n"
            "  host: localhost\n"
            "  port: 5432\n"
            "tags: [a, b, c]\n"
        )
        d = tc.load_file(p)
        self.assertEqual(d["name"], "alice")
        self.assertEqual(d["db"]["host"], "localhost")
        self.assertEqual(d["db"]["port"], 5432)
        self.assertEqual(d["tags"], ["a", "b", "c"])
        self.assertIs(d["active"], True)


class TestLoad(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_precedence(self):
        defaults = {"a": 1, "b": 2}
        f = Path(self.tmp) / "c.json"
        f.write_text(json.dumps({"b": 20, "c": 30}))
        os.environ["TC_TEST__B"] = "200"
        os.environ["TC_TEST__D"] = "400"
        try:
            cfg = tc.load(
                file=f,
                env_prefix="TC_TEST",
                cli=False,
                defaults=defaults,
            )
            self.assertEqual(cfg["a"], 1)  # default kept
            self.assertEqual(cfg["b"], 200)  # env wins
            self.assertEqual(cfg["c"], 30)  # file only
            self.assertEqual(cfg["d"], 400)  # env only
        finally:
            del os.environ["TC_TEST__B"]
            del os.environ["TC_TEST__D"]

    def test_cli(self):
        defaults = {"x": 1}
        cfg = tc.load(
            file=None, env_prefix="", cli=False, defaults=defaults
        )
        # Simulate CLI override manually
        sys.argv = ["prog", "--x=99", "--y=hello"]
        cfg2 = tc.load(file=None, env_prefix="", cli=True, defaults=defaults)
        self.assertEqual(cfg2["x"], 99)
        self.assertEqual(cfg2["y"], "hello")


class TestCLIEntry(unittest.TestCase):
    def test_main(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"a": 1, "b": {"c": 2}}, f)
            path = f.name
        try:
            rc = tc._main([path, "b.c"])
            self.assertEqual(rc, 0)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
