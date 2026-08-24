import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle import __version__
from bindle.cli import _LIFECYCLE_COMMANDS, main

TOP_LEVEL_COMMANDS = [*_LIFECYCLE_COMMANDS, "repo"]


def _run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path):
    os.makedirs(path, exist_ok=True)
    _run(["git", "init", "--initial-branch=main"], path)
    _run(["git", "config", "user.email", "test@example.com"], path)
    _run(["git", "config", "user.name", "Test"], path)
    with open(os.path.join(path, "README.md"), "w") as f:
        f.write("test\n")
    _run(["git", "add", "README.md"], path)
    _run(["git", "commit", "-m", "chore: initial commit"], path)


@contextlib.contextmanager
def _chdir(path):
    original = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


def _normalize_ws(text):
    # argparse wraps description/help text to the terminal width, so a
    # multi-sentence description can gain line breaks mid-phrase. Compare
    # on whitespace-normalized text so wrapping never causes a spurious
    # mismatch.
    return " ".join(text.split())


class TestVersion(unittest.TestCase):
    def test_version_flag(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as cm:
                main(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(out.getvalue().strip(), f"bindle {__version__}")


class TestRepoInfoCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_human_output(self):
        out = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stdout(out):
            code = main(["repo", "info"])

        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("branch:          main", text)
        self.assertIn("repository root:", text)
        self.assertIn("HEAD SHA:", text)

    def test_json_output(self):
        out = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stdout(out):
            code = main(["repo", "info", "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["branch"], "main")
        self.assertFalse(payload["detached"])
        self.assertEqual(len(payload["head_sha"]), 40)

    def test_outside_git_repository_fails_clearly(self):
        outside = tempfile.mkdtemp()
        err = io.StringIO()
        try:
            with _chdir(outside), contextlib.redirect_stderr(err):
                code = main(["repo", "info"])
            self.assertEqual(code, 1)
            self.assertIn("not a Git repository", err.getvalue())
        finally:
            os.rmdir(outside)


class TestTopLevelHelpSurface(unittest.TestCase):
    def _help_text(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as cm:
                main(argv)
        self.assertEqual(cm.exception.code, 0)
        return out.getvalue()

    def test_all_target_commands_listed(self):
        text = self._help_text(["--help"])
        for name in TOP_LEVEL_COMMANDS:
            self.assertIn(name, text)

    def test_help_descriptions_reflect_intended_meaning(self):
        text = _normalize_ws(self._help_text(["--help"]))
        for help_text, _description in _LIFECYCLE_COMMANDS.values():
            self.assertIn(help_text, text)
        self.assertIn("Repository information.", text)

    def test_each_lifecycle_command_has_working_help(self):
        for name, (_help_text, description) in _LIFECYCLE_COMMANDS.items():
            with self.subTest(command=name):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    with self.assertRaises(SystemExit) as cm:
                        main([name, "--help"])
                self.assertEqual(cm.exception.code, 0)
                text = out.getvalue()
                self.assertIn(f"usage: bindle {name}", text)
                # The command's own --help must show its full description,
                # not merely the usage line.
                self.assertIn(_normalize_ws(description), _normalize_ws(text))


class TestGlobalVsRepositoryContract(unittest.TestCase):
    # Regression coverage for the documented split: `list`/`update` are
    # global/machine-level, everything else (init/remove/status/upgrade/
    # doctor/repo info) targets the current repository, with `upgrade`
    # specifically repository-targeted by default (no fleet-wide mutation).
    def _help_text(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit):
                main(argv)
        return _normalize_ws(out.getvalue())

    def test_update_is_global_and_does_not_mutate_repositories(self):
        text = self._help_text(["update", "--help"])
        self.assertIn("Global/machine-level", text)
        self.assertIn("never mutates a managed repository", text)

    def test_upgrade_is_repository_targeted_by_default(self):
        text = self._help_text(["upgrade", "--help"])
        self.assertIn("current repository", text)
        self.assertIn("Repository-targeted by default", text)
        self.assertNotIn("--all", text)

    def test_list_is_global_inventory_of_opted_in_repositories(self):
        text = self._help_text(["list", "--help"])
        self.assertIn("Global/machine-level", text)
        self.assertIn("bindle init", text)


class TestUnimplementedLifecycleCommands(unittest.TestCase):
    def test_direct_invocation_fails_clearly(self):
        for name in _LIFECYCLE_COMMANDS:
            with self.subTest(command=name):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = main([name])
                self.assertEqual(code, 1)
                self.assertEqual(err.getvalue().strip(), f"bindle {name}: not implemented yet")
                self.assertEqual(out.getvalue(), "")

    def test_stubs_do_not_shell_out(self):
        # Regression guard: an unimplemented command must not invoke any
        # script or installer (e.g. scripts/doctor.sh) on its way to
        # reporting "not implemented yet".
        with mock.patch("subprocess.run", side_effect=AssertionError("must not shell out")):
            for name in _LIFECYCLE_COMMANDS:
                with self.subTest(command=name):
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err):
                        code = main([name])
                    self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
