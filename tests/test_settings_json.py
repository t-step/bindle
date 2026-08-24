"""Unit tests for src/bindle/_bin/settings_json.py.

This is the jq-free JSON helper install-guardrails.sh uses for the
Claude-layer settings.local.json merge (docs/DECISIONS.md D032's "jq
elimination" amendment). Loaded directly from its file path (not via
`import bindle...`) because it's a package-owned runtime asset, not part
of the bindle package's own import surface — see cli.py's
_installer_path()/_installer_env().
"""

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest

_SETTINGS_JSON_PATH = os.path.join(
    os.path.dirname(__file__), "..", "src", "bindle", "_bin", "settings_json.py"
)
_spec = importlib.util.spec_from_file_location("settings_json", _SETTINGS_JSON_PATH)
settings_json = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(settings_json)


def _run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = settings_json.main(argv)
    return code, out.getvalue().strip()


class SettingsJsonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _path(self, name):
        return os.path.join(self.tmp.name, name)

    def _write(self, name, obj):
        path = self._path(name)
        with open(path, "w") as f:
            json.dump(obj, f)
        return path

    def test_valid_json(self):
        path = self._write("a.json", {"x": 1})
        self.assertEqual(_run(["valid-json", path])[0], 0)

    def test_valid_json_missing_or_malformed(self):
        self.assertEqual(_run(["valid-json", self._path("missing.json")])[0], 1)
        bad = self._path("bad.json")
        with open(bad, "w") as f:
            f.write("{not json")
        self.assertEqual(_run(["valid-json", bad])[0], 1)

    def test_read_array_absent_file_is_empty_array(self):
        code, out = _run(["read-array", self._path("missing.json")])
        self.assertEqual((code, out), (0, "[]"))

    def test_read_array_valid(self):
        path = self._write("owned.json", ["a", "b"])
        code, out = _run(["read-array", path])
        self.assertEqual((code, json.loads(out)), (0, ["a", "b"]))

    def test_read_array_rejects_non_array(self):
        path = self._write("owned.json", {"not": "an array"})
        self.assertEqual(_run(["read-array", path])[0], 1)

    def test_pretooluse_present_and_absent(self):
        path = self._write(
            "settings.json",
            {"hooks": {"PreToolUse": [{"matcher": "M", "hooks": [{"command": "C"}]}]}},
        )
        self.assertEqual(_run(["pretooluse-present", path, "M", "C"])[0], 0)
        self.assertEqual(_run(["pretooluse-present", path, "M", "other"])[0], 1)
        self.assertEqual(_run(["pretooluse-present", path, "other", "C"])[0], 1)

    def test_add_then_remove_pretooluse_round_trip(self):
        path = self._write("settings.json", {})
        self.assertEqual(_run(["add-pretooluse", path, "M", "C", "5"])[0], 0)
        with open(path) as f:
            doc = json.load(f)
        self.assertEqual(
            doc["hooks"]["PreToolUse"],
            [{"matcher": "M", "hooks": [{"type": "command", "command": "C", "timeout": 5}]}],
        )
        self.assertEqual(_run(["pretooluse-present", path, "M", "C"])[0], 0)

        self.assertEqual(_run(["remove-pretooluse", path, "M", "C"])[0], 0)
        with open(path) as f:
            doc = json.load(f)
        self.assertEqual(doc["hooks"]["PreToolUse"], [])
        self.assertEqual(_run(["pretooluse-present", path, "M", "C"])[0], 1)

    def test_remove_pretooluse_preserves_unrelated_entries(self):
        path = self._write(
            "settings.json",
            {
                "customUserSetting": "must-survive",
                "hooks": {
                    "PreToolUse": [
                        {"matcher": "Agent", "hooks": [{"command": "other"}]},
                        {"matcher": "M", "hooks": [{"command": "C"}]},
                    ]
                },
            },
        )
        self.assertEqual(_run(["remove-pretooluse", path, "M", "C"])[0], 0)
        with open(path) as f:
            doc = json.load(f)
        self.assertEqual(doc["customUserSetting"], "must-survive")
        self.assertEqual([e["matcher"] for e in doc["hooks"]["PreToolUse"]], ["Agent"])

    def test_merge_deny_and_deny_diff(self):
        path = self._write("settings.json", {"permissions": {"deny": ["Bash(rm -rf /)"]}})
        manifest = json.dumps(["Bash(rm -rf /)", "Read(.env)"])

        code, diff_out = _run(["deny-diff", path, manifest])
        self.assertEqual((code, json.loads(diff_out)), (0, ["Read(.env)"]))

        self.assertEqual(_run(["merge-deny", path, manifest])[0], 0)
        with open(path) as f:
            doc = json.load(f)
        self.assertEqual(doc["permissions"]["deny"], ["Bash(rm -rf /)", "Read(.env)"])

    def test_remove_deny(self):
        path = self._write(
            "settings.json", {"permissions": {"deny": ["Bash(rm -rf /)", "Read(.env)"]}}
        )
        self.assertEqual(_run(["remove-deny", path, json.dumps(["Read(.env)"])])[0], 0)
        with open(path) as f:
            doc = json.load(f)
        self.assertEqual(doc["permissions"]["deny"], ["Bash(rm -rf /)"])

    def test_array_union_dedupes_and_sorts(self):
        code, out = _run(["array-union", json.dumps(["b", "a"]), json.dumps(["a", "c"])])
        self.assertEqual((code, json.loads(out)), (0, ["a", "b", "c"]))

    def test_write_json_atomic(self):
        path = self._path("owned.json")
        self.assertEqual(_run(["write-json", path, json.dumps(["x", "y"])])[0], 0)
        with open(path) as f:
            self.assertEqual(json.load(f), ["x", "y"])

    def test_length(self):
        code, out = _run(["length", json.dumps(["a", "b", "c"])])
        self.assertEqual((code, out), (0, "3"))

    def test_lines_to_json_array(self):
        stdin = io.StringIO("one\ntwo\nthree\n")
        old_stdin = settings_json.sys.stdin
        settings_json.sys.stdin = stdin
        try:
            code, out = _run(["lines-to-json-array"])
        finally:
            settings_json.sys.stdin = old_stdin
        self.assertEqual((code, json.loads(out)), (0, ["one", "two", "three"]))

    def test_mutating_verb_leaves_destination_untouched_on_malformed_input(self):
        bad = self._path("bad.json")
        with open(bad, "w") as f:
            f.write("{not json")
        with open(bad) as f:
            before = f.read()
        self.assertEqual(_run(["add-pretooluse", bad, "M", "C", "5"])[0], 1)
        with open(bad) as f:
            self.assertEqual(f.read(), before)

    def test_unknown_verb(self):
        code, _ = _run(["not-a-real-verb"])
        self.assertEqual(code, 2)

    def test_doc_is_empty_true_for_bare_object_and_empty_containers(self):
        self.assertEqual(_run(["doc-is-empty", self._write("a.json", {})])[0], 0)
        self.assertEqual(
            _run(
                [
                    "doc-is-empty",
                    self._write(
                        "b.json",
                        {"hooks": {"PreToolUse": []}, "permissions": {"deny": []}},
                    ),
                ]
            )[0],
            0,
        )

    def test_doc_is_empty_false_when_unrelated_content_remains(self):
        self.assertEqual(
            _run(["doc-is-empty", self._write("a.json", {"customUserSetting": "keep"})])[0],
            1,
        )
        self.assertEqual(
            _run(
                [
                    "doc-is-empty",
                    self._write("b.json", {"permissions": {"deny": ["Bash(rm -rf /)"]}}),
                ]
            )[0],
            1,
        )
        self.assertEqual(
            _run(
                [
                    "doc-is-empty",
                    self._write(
                        "c.json",
                        {"hooks": {"PreToolUse": [{"matcher": "Agent", "hooks": []}]}},
                    ),
                ]
            )[0],
            1,
        )

    def test_doc_is_empty_false_for_falsy_scalars(self):
        self.assertEqual(_run(["doc-is-empty", self._write("a.json", {"flag": False})])[0], 1)
        self.assertEqual(_run(["doc-is-empty", self._write("b.json", {"n": 0})])[0], 1)
        self.assertEqual(_run(["doc-is-empty", self._write("c.json", {"s": ""})])[0], 1)

    def test_doc_is_empty_rejects_missing_or_non_object(self):
        self.assertEqual(_run(["doc-is-empty", self._path("missing.json")])[0], 1)
        self.assertEqual(_run(["doc-is-empty", self._write("arr.json", [])])[0], 1)


if __name__ == "__main__":
    unittest.main()
