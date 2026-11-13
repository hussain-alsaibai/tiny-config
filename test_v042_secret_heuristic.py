"""v0.4.2 — secret-key detection must key on names, not substrings.

The v0.4.0/v0.4.1 heuristic masked any key whose lowercase form *contained* a
sensitive word. `secret_ref`, `tokenizer` and `auth_mode` were therefore
redacted, which silently removed the exact fields a redacted config is
supposed to preserve: where the secret lives and how it is verified.

Both halves are asserted here: the false positives are gone, and the real
credentials are still masked. Fixing only the first would be a regression.
"""

import unittest

import tiny_config as tc


class TestSecretNameMatching(unittest.TestCase):
    def test_pointer_and_non_secret_compound_keys_survive(self):
        cfg = {
            "app": {
                "name": "svc",
                "secret_ref": "vault://team/api",
                "tokenizer": "bpe",
                "auth_mode": "mtls",
                "secret_manager": {"region": "us-east-1"},
            }
        }
        out = tc.to_dict(cfg)
        self.assertEqual(out["app"]["secret_ref"], "vault://team/api")
        self.assertEqual(out["app"]["tokenizer"], "bpe")
        self.assertEqual(out["app"]["auth_mode"], "mtls")
        self.assertEqual(out["app"]["secret_manager"], {"region": "us-east-1"})

    def test_suffixed_credential_keys_are_masked(self):
        cfg = {
            "db_password": "hunter2",
            "github_token": "x" * 8,
            "client_secret": "shh",
            "aws_secret_access_key": "AKIA",
            "auth": {"secret": "s"},
        }
        out = tc.to_dict(cfg)
        self.assertEqual(out["db_password"], "***")
        self.assertEqual(out["github_token"], "***")
        self.assertEqual(out["client_secret"], "***")
        self.assertEqual(out["aws_secret_access_key"], "***")
        self.assertEqual(out["auth"], "***")

    def test_pointer_value_wins_over_explicit_key(self):
        """A `keys=` entry must not mask a secret-manager pointer."""
        cfg = {"password": "vault://prod/db", "other": {"password": "real"}}
        tc.mask_secrets(cfg, keys=("password",))
        self.assertEqual(cfg["password"], "vault://prod/db")
        self.assertEqual(cfg["other"]["password"], "***")

    def test_empty_pointer_is_not_masked_as_credential(self):
        cfg = {"token": "", "db": {"password": " "}}
        out = tc.to_dict(cfg)
        self.assertEqual(out["token"], "")
        self.assertEqual(out["db"]["password"], " ")

    def test_non_string_keys_do_not_raise(self):
        cfg = {1: {"token": "t"}, "keep": 2}
        out = tc.to_dict(cfg)
        self.assertEqual(out["1"]["token"], "***")
        self.assertEqual(out["keep"], 2)

    def test_masking_still_recursive_in_lists(self):
        cfg = {"accounts": [{"name": "a", "token": "t1"}, {"name": "b", "api_key": "t2"}]}
        out = tc.to_dict(cfg)
        self.assertEqual(out["accounts"][0]["token"], "***")
        self.assertEqual(out["accounts"][1]["api_key"], "***")
        self.assertEqual([a["name"] for a in out["accounts"]], ["a", "b"])


class TestUnchangedGuarantees(unittest.TestCase):
    def test_opt_out_returns_value(self):
        cfg = {"api_key": "abc123"}
        self.assertEqual(tc.to_dict(cfg, redact_secret_keys=False)["api_key"], "abc123")

    def test_source_is_not_mutated(self):
        cfg = {"db": {"password": "hunter2"}}
        tc.to_dict(cfg)
        self.assertEqual(cfg["db"]["password"], "hunter2")

    def test_to_json_uses_same_policy(self):
        import json

        cfg = {"tokenizer": "bpe", "token": "t"}
        parsed = json.loads(tc.to_json(cfg))
        self.assertEqual(parsed["tokenizer"], "bpe")
        self.assertEqual(parsed["token"], "***")


if __name__ == "__main__":
    unittest.main()
