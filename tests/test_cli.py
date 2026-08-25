import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle import __version__
from bindle.cli import _LIFECYCLE_COMMANDS, main
from bindle.guardrails import detect_claude_guardrails, detect_git_guardrails
from bindle import qmd as qmd_mod
from bindle.projectmem import detect_projectmem
from bindle.qmd import COLLECTION_NAME, detect_qmd
from bindle.repo import get_repo_info
from bindle.skills import KitInfo, KitOpOutcome, KitStatus

TOP_LEVEL_COMMANDS = [*_LIFECYCLE_COMMANDS, "repo", "branch", "skills"]

_HAS_REAL_PJM = shutil.which("pjm") is not None
_HAS_REAL_QMD = shutil.which("qmd") is not None


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
        self.assertIn("Create a new worktree and branch off up-to-date origin/main.", text)

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


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[")


class TestHelpOutputIsPlainText(unittest.TestCase):
    # Python 3.14 made argparse.ArgumentParser(color=True) the default —
    # a styling policy Bindle never opted into (every other CLI surface
    # is deterministic plain text). _BindleArgumentParser forces it off.
    # PYTHON_COLORS=1 forces `_colorize.can_colorize()` to return True
    # unconditionally (verified against the installed argparse/_colorize
    # source this session), so this test cannot pass merely because
    # stdout isn't attached to a terminal — only because `color` is
    # actually False on every parser/subparser instance.
    def _help_text_forced_color(self, argv):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"PYTHON_COLORS": "1"}):
            with contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit) as cm:
                    main(argv)
        self.assertEqual(cm.exception.code, 0)
        return out.getvalue()

    def test_top_level_help_has_no_ansi_escapes(self):
        text = self._help_text_forced_color(["--help"])
        self.assertIsNone(_ANSI_ESCAPE_RE.search(text), text)

    def test_every_lifecycle_command_help_has_no_ansi_escapes(self):
        for name in _LIFECYCLE_COMMANDS:
            with self.subTest(command=name):
                text = self._help_text_forced_color([name, "--help"])
                self.assertIsNone(_ANSI_ESCAPE_RE.search(text), text)

    def test_nested_subparser_help_has_no_ansi_escapes(self):
        # Two levels of nesting (skills -> add), the deepest subparser
        # this CLI has — proves add_subparsers()'s parser_class
        # propagation actually reaches nested subparsers, not just the
        # top level.
        for argv in (["repo", "info", "--help"], ["skills", "--help"], ["skills", "add", "--help"]):
            with self.subTest(argv=argv):
                text = self._help_text_forced_color(argv)
                self.assertIsNone(_ANSI_ESCAPE_RE.search(text), text)

    def test_subparser_instances_use_the_bindle_parser_class(self):
        # A direct structural check, not just a behavioral one: every
        # subparser argparse constructs must actually be
        # _BindleArgumentParser, confirming add_subparsers()'s
        # parser_class default (type(self)) is doing the propagation —
        # not merely that color happens to end up False some other way.
        from bindle.cli import _BindleArgumentParser, build_parser

        parser = build_parser()
        self.assertIsInstance(parser, _BindleArgumentParser)

        subparsers_action = next(
            action for action in parser._subparsers._group_actions if hasattr(action, "choices")
        )
        for name, subparser in subparsers_action.choices.items():
            with self.subTest(subparser=name):
                self.assertIsInstance(subparser, _BindleArgumentParser)


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


_STILL_UNIMPLEMENTED = [
    name
    for name in _LIFECYCLE_COMMANDS
    if name not in ("init", "remove", "status", "migrate-legacy-global")
]


class TestUnimplementedLifecycleCommands(unittest.TestCase):
    def test_direct_invocation_fails_clearly(self):
        for name in _STILL_UNIMPLEMENTED:
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
            for name in _STILL_UNIMPLEMENTED:
                with self.subTest(command=name):
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err):
                        code = main([name])
                    self.assertEqual(code, 1)


_REAL_SUBPROCESS_RUN = subprocess.run


def _intercept_installer_call(on_installer_call):
    # get_repo_info() legitimately shells out to `git` on the way to
    # resolving init/remove's target repository — only the installer
    # invocation itself (`["bash", ".../install-guardrails.sh", ...]`)
    # should be faked or forbidden, so real `git` calls always pass
    # through unmodified.
    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "bash":
            return on_installer_call(cmd)
        return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

    return mock.patch("subprocess.run", side_effect=fake_run)


class TestGuardrailLifecycleCommands(unittest.TestCase):
    # `init`/`remove` are the one real lifecycle behavior so far: driving
    # bin/install-guardrails.sh's Git layer, scoped to the current
    # repository, via --git-only --repo <worktree root>.
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_invokes_the_installer_for_this_repository_both_layers(self):
        captured = {}

        def on_installer_call(cmd):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0)

        with _chdir(self.repo), _intercept_installer_call(on_installer_call):
            code = main(["init"])

        self.assertEqual(code, 0)
        cmd = captured["cmd"]
        self.assertEqual(cmd[0], "bash")
        self.assertTrue(cmd[1].endswith("_bin/install-guardrails.sh"))
        self.assertEqual(cmd[2], "--apply")
        # Both layers are repo-scoped now, so init/remove no longer need
        # --git-only to avoid also toggling a separately-scoped global
        # Claude layer — that layer doesn't exist anymore.
        self.assertNotIn("--git-only", cmd)
        self.assertNotIn("--claude-only", cmd)
        self.assertIn("--repo", cmd)
        self.assertEqual(cmd[cmd.index("--repo") + 1], os.path.realpath(self.repo))

    def test_remove_invokes_uninstall(self):
        captured = {}

        def on_installer_call(cmd):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0)

        with _chdir(self.repo), _intercept_installer_call(on_installer_call):
            code = main(["remove"])

        self.assertEqual(code, 0)
        self.assertEqual(captured["cmd"][2], "--uninstall")

    def test_init_propagates_the_installer_exit_code(self):
        with _chdir(self.repo), _intercept_installer_call(
            lambda cmd: subprocess.CompletedProcess(cmd, 3)
        ):
            code = main(["init"])
        self.assertEqual(code, 3)

    def test_init_outside_a_git_repository_fails_clearly_without_shelling_out(self):
        outside = tempfile.mkdtemp()
        err = io.StringIO()

        def on_installer_call(cmd):
            raise AssertionError("must not shell out")

        try:
            with _intercept_installer_call(on_installer_call):
                with _chdir(outside), contextlib.redirect_stderr(err):
                    code = main(["init"])
            self.assertEqual(code, 1)
            self.assertIn("not a Git repository", err.getvalue())
        finally:
            os.rmdir(outside)

    def test_init_passes_bindle_python_env_for_the_installer(self):
        # settings_json.py (the Claude-layer JSON helper) must run under
        # the exact interpreter already running `bindle` itself — no
        # external JSON tool (jq) is required. See _installer_env().
        captured = {}

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "bash":
                captured["env"] = kwargs.get("env")
                return subprocess.CompletedProcess(cmd, 0)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch("subprocess.run", side_effect=fake_run):
            code = main(["init"])

        self.assertEqual(code, 0)
        self.assertIsNotNone(captured.get("env"))
        self.assertEqual(captured["env"].get("BINDLE_PYTHON"), sys.executable)

    def test_init_reports_clearly_when_the_installer_script_is_missing(self):
        err = io.StringIO()

        def on_installer_call(cmd):
            raise AssertionError("must not shell out")

        with _chdir(self.repo), mock.patch(
            "bindle.cli._installer_path",
            return_value=Path("/nonexistent/install-guardrails.sh"),
        ), _intercept_installer_call(on_installer_call), contextlib.redirect_stderr(err):
            code = main(["init"])
        self.assertEqual(code, 1)
        self.assertIn("guardrail installer not found", err.getvalue())


class TestMigrateLegacyGlobalCommand(unittest.TestCase):
    # `migrate-legacy-global` is global/machine-level: unlike init/remove,
    # it does not resolve a current repository and passes no --repo.
    def test_invokes_the_installer_with_remove_legacy_global(self):
        captured = {}

        def on_installer_call(cmd):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0)

        with _intercept_installer_call(on_installer_call):
            code = main(["migrate-legacy-global"])

        self.assertEqual(code, 0)
        cmd = captured["cmd"]
        self.assertEqual(cmd[0], "bash")
        self.assertTrue(cmd[1].endswith("_bin/install-guardrails.sh"))
        self.assertEqual(cmd[2], "--remove-legacy-global")
        self.assertNotIn("--repo", cmd)

    def test_does_not_require_a_git_repository(self):
        outside = tempfile.mkdtemp()
        captured = {}

        def on_installer_call(cmd):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0)

        try:
            with _chdir(outside), _intercept_installer_call(on_installer_call):
                code = main(["migrate-legacy-global"])
            self.assertEqual(code, 0)
            self.assertIn("cmd", captured)
        finally:
            os.rmdir(outside)

    def test_propagates_the_installer_exit_code(self):
        with _intercept_installer_call(lambda cmd: subprocess.CompletedProcess(cmd, 2)):
            code = main(["migrate-legacy-global"])
        self.assertEqual(code, 2)

    def test_passes_bindle_python_env_for_the_installer(self):
        captured = {}

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "bash":
                captured["env"] = kwargs.get("env")
                return subprocess.CompletedProcess(cmd, 0)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with mock.patch("subprocess.run", side_effect=fake_run):
            code = main(["migrate-legacy-global"])

        self.assertEqual(code, 0)
        self.assertIsNotNone(captured.get("env"))
        self.assertEqual(captured["env"].get("BINDLE_PYTHON"), sys.executable)

    def test_reports_clearly_when_the_installer_script_is_missing(self):
        err = io.StringIO()

        def on_installer_call(cmd):
            raise AssertionError("must not shell out")

        with mock.patch(
            "bindle.cli._installer_path",
            return_value=Path("/nonexistent/install-guardrails.sh"),
        ), _intercept_installer_call(on_installer_call), contextlib.redirect_stderr(err):
            code = main(["migrate-legacy-global"])
        self.assertEqual(code, 1)
        self.assertIn("guardrail installer not found", err.getvalue())


def _intercept_installer_calls(on_installer_call):
    # Like _intercept_installer_call, but for commands (status) that shell
    # out to the installer more than once per invocation — collects every
    # `["bash", ".../install-guardrails.sh", ...]` call in order.
    calls = []

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "bash":
            calls.append(cmd)
            return on_installer_call(cmd)
        return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

    return calls, mock.patch("subprocess.run", side_effect=fake_run)


class TestStatusCommand(unittest.TestCase):
    # `bindle status` (read-only) drives detect_git_guardrails/
    # detect_claude_guardrails (guardrails.py), each a separate
    # install-guardrails.sh --status invocation scoped to one layer via
    # --git-only/--claude-only. See tests/test_guardrails.py for the
    # detector functions' own real-fixture coverage, and
    # bin/test-guardrail-status.sh for the full five-state matrix at the
    # installer level — this class covers the CLI wiring and output
    # formatting.
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def _fake_status_output(self, git="installed", claude="installed"):
        def on_installer_call(cmd):
            if "--git-only" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout=f"GIT_STATUS={git}\n")
            if "--claude-only" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout=f"CLAUDE_STATUS={claude}\n")
            raise AssertionError(f"unexpected installer invocation: {cmd}")

        return on_installer_call

    def test_invokes_the_installer_read_only_once_per_layer(self):
        calls, patch = _intercept_installer_calls(self._fake_status_output())
        with _chdir(self.repo), patch:
            code = main(["status"])

        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        flags = {tuple(c) for c in calls}
        self.assertTrue(any("--git-only" in c for c in flags))
        self.assertTrue(any("--claude-only" in c for c in flags))
        for cmd in calls:
            self.assertEqual(cmd[0], "bash")
            self.assertTrue(cmd[1].endswith("_bin/install-guardrails.sh"))
            self.assertIn("--status", cmd)
            self.assertIn("--repo", cmd)
            self.assertEqual(cmd[cmd.index("--repo") + 1], os.path.realpath(self.repo))
            # Genuinely read-only: never any mutation/migration mode flag.
            self.assertNotIn("--apply", cmd)
            self.assertNotIn("--uninstall", cmd)
            self.assertNotIn("--remove-legacy-global", cmd)

    def test_output_format_matches_the_documented_shape(self):
        _, patch = _intercept_installer_calls(self._fake_status_output(git="installed", claude="partial"))
        out = io.StringIO()
        with _chdir(self.repo), patch, contextlib.redirect_stdout(out):
            code = main(["status"])

        self.assertEqual(code, 0)
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0], f"Repository: {os.path.basename(os.path.realpath(self.repo))}")
        self.assertEqual(lines[1], "Guardrails")
        self.assertEqual(lines[2], "  Git       installed")
        self.assertEqual(lines[3], "  Claude    partial")

    def test_passes_bindle_python_env_for_the_installer(self):
        captured_envs = []

        def on_installer_call(cmd):
            captured_envs.append(None)
            if "--git-only" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="GIT_STATUS=not-installed\n")
            return subprocess.CompletedProcess(cmd, 0, stdout="CLAUDE_STATUS=not-installed\n")

        envs = []

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "bash":
                envs.append(kwargs.get("env"))
                return on_installer_call(cmd)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch("subprocess.run", side_effect=fake_run):
            code = main(["status"])

        self.assertEqual(code, 0)
        self.assertEqual(len(envs), 2)
        for env in envs:
            self.assertEqual(env.get("BINDLE_PYTHON"), sys.executable)

    def test_outside_git_repository_fails_clearly_without_shelling_out(self):
        outside = tempfile.mkdtemp()
        err = io.StringIO()

        def on_installer_call(cmd):
            raise AssertionError("must not shell out")

        try:
            _, patch = _intercept_installer_calls(on_installer_call)
            with patch, _chdir(outside), contextlib.redirect_stderr(err):
                code = main(["status"])
            self.assertEqual(code, 1)
            self.assertIn("not a Git repository", err.getvalue())
        finally:
            os.rmdir(outside)

    def test_reports_clearly_when_the_installer_script_is_missing(self):
        err = io.StringIO()

        def on_installer_call(cmd):
            raise AssertionError("must not shell out")

        _, patch = _intercept_installer_calls(on_installer_call)
        with _chdir(self.repo), mock.patch(
            "bindle.guardrails.installer_path",
            return_value=Path("/nonexistent/install-guardrails.sh"),
        ), patch, contextlib.redirect_stderr(err):
            code = main(["status"])
        self.assertEqual(code, 1)
        self.assertIn("guardrail installer not found", err.getvalue())

    def test_reports_clearly_when_the_installer_fails(self):
        err = io.StringIO()

        def on_installer_call(cmd):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="something broke")

        _, patch = _intercept_installer_calls(on_installer_call)
        with _chdir(self.repo), patch, contextlib.redirect_stderr(err):
            code = main(["status"])
        self.assertEqual(code, 1)
        self.assertIn("something broke", err.getvalue())

    def test_real_end_to_end_reflects_init_and_remove_with_no_mutation(self):
        # No mocking: proves the whole `bindle status` -> guardrails.py ->
        # install-guardrails.sh --status chain against a real repository,
        # and that status itself never changes what it reports.
        out = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stdout(out):
            code = main(["status"])
        self.assertEqual(code, 0)
        self.assertIn("Git       not-installed", out.getvalue())
        self.assertIn("Claude    not-installed", out.getvalue())

        # Repeating it changes nothing (still not-installed).
        out2 = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stdout(out2):
            main(["status"])
        self.assertEqual(out.getvalue(), out2.getvalue())

        with _chdir(self.repo):
            self.assertEqual(main(["init"]), 0)

        out3 = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stdout(out3):
            code = main(["status"])
        self.assertEqual(code, 0)
        self.assertIn("Git       installed", out3.getvalue())
        self.assertIn("Claude    installed", out3.getvalue())

        with _chdir(self.repo):
            self.assertEqual(main(["remove"]), 0)

        out4 = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stdout(out4):
            code = main(["status"])
        self.assertEqual(code, 0)
        self.assertIn("Git       not-installed", out4.getvalue())
        self.assertIn("Claude    not-installed", out4.getvalue())

    def test_projectmem_row_not_installed_by_default(self):
        # No mocking of the guardrail installer here: proves the real
        # detect_projectmem wiring against a repository with no
        # .projectmem/ directory at all.
        out = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stdout(out):
            code = main(["status"])
        self.assertEqual(code, 0)
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[4], "Projectmem  not-installed")

    def test_projectmem_row_reflects_real_projectmem_state(self):
        mem_dir = os.path.join(self.repo, ".projectmem")
        os.makedirs(mem_dir)
        with open(os.path.join(mem_dir, "config.toml"), "w") as f:
            f.write('summary_size_limit_kb = 20\nrecent_days = 30\nproject_description = ""\n')

        out = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stdout(out):
            code = main(["status"])
        self.assertEqual(code, 0)
        self.assertIn("Projectmem  installed", out.getvalue())

    def test_mixed_guardrail_and_projectmem_rendering(self):
        # Guardrails partially installed, Projectmem not installed at all —
        # each row renders its own independently observed state.
        _, patch = _intercept_installer_calls(self._fake_status_output(git="installed", claude="partial"))
        out = io.StringIO()
        with _chdir(self.repo), patch, contextlib.redirect_stdout(out):
            code = main(["status"])

        self.assertEqual(code, 0)
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0], f"Repository: {os.path.basename(os.path.realpath(self.repo))}")
        self.assertEqual(lines[1], "Guardrails")
        self.assertEqual(lines[2], "  Git       installed")
        self.assertEqual(lines[3], "  Claude    partial")
        self.assertEqual(lines[4], "Projectmem  not-installed")

    def test_repeated_status_calls_cause_no_projectmem_mutation(self):
        mem_dir = os.path.join(self.repo, ".projectmem")
        os.makedirs(mem_dir)
        with open(os.path.join(mem_dir, "config.toml"), "w") as f:
            f.write('summary_size_limit_kb = 20\n')
        before = sorted(os.listdir(mem_dir))

        with _chdir(self.repo):
            self.assertEqual(main(["status"]), 0)
            self.assertEqual(main(["status"]), 0)

        after = sorted(os.listdir(mem_dir))
        self.assertEqual(before, after)

    def test_qmd_row_unavailable_when_qmd_not_on_path(self):
        with _chdir(self.repo), mock.patch("bindle.qmd.qmd_executable", return_value=None):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["status"])
        self.assertEqual(code, 0)
        self.assertIn("QMD         unavailable", out.getvalue())

    def test_qmd_row_not_initialized_when_qmd_available_but_unused(self):
        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["status"])
        self.assertEqual(code, 0)
        self.assertIn("QMD         not-initialized", out.getvalue())

    def test_qmd_row_reflects_real_ready_state(self):
        qmd_dir = os.path.join(self.repo, ".qmd")
        os.makedirs(qmd_dir)
        with open(os.path.join(qmd_dir, "index.yml"), "w") as f:
            f.write(f"collections:\n  {COLLECTION_NAME}:\n    path: {os.path.realpath(self.repo)}\n")

        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["status"])
        self.assertEqual(code, 0)
        self.assertIn("QMD         ready", out.getvalue())

    def test_status_never_mutates_qmd_directory(self):
        qmd_dir = os.path.join(self.repo, ".qmd")
        os.makedirs(qmd_dir)
        with open(os.path.join(qmd_dir, "index.yml"), "w") as f:
            f.write(f"collections:\n  {COLLECTION_NAME}:\n    path: {os.path.realpath(self.repo)}\n")
        before = sorted(os.listdir(qmd_dir))

        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ):
            self.assertEqual(main(["status"]), 0)
            self.assertEqual(main(["status"]), 0)

        after = sorted(os.listdir(qmd_dir))
        self.assertEqual(before, after)


class TestBranchCommand(unittest.TestCase):
    # `bindle branch <name>` closes the "forking gap": a single command
    # that creates an isolated worktree + branch off freshly-fetched
    # origin/main, rather than a raw multi-step git dance that can silently
    # branch off stale local main (see docs/DECISIONS.md, the forking-gap
    # design discussion this implements).
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.remote = os.path.join(self.tmp.name, "remote")
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.remote)
        _run(["git", "clone", self.remote, self.repo], self.tmp.name)
        _run(["git", "config", "user.email", "test@example.com"], self.repo)
        _run(["git", "config", "user.name", "Test"], self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def _head_sha(self, path):
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=True
        ).stdout.strip()

    def _current_branch(self, path):
        return subprocess.run(
            ["git", "symbolic-ref", "-q", "--short", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def test_creates_worktree_off_fresh_origin_main_not_stale_local_main(self):
        # Advance the remote's main without ever updating the local clone's
        # own main, so a naive "branch off local main" would silently pick
        # up stale history.
        with open(os.path.join(self.remote, "NEW.md"), "w") as f:
            f.write("advance\n")
        _run(["git", "add", "NEW.md"], self.remote)
        _run(["git", "commit", "-m", "feat: advance remote main"], self.remote)
        remote_head = self._head_sha(self.remote)

        out = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stdout(out):
            code = main(["branch", "feature-x"])

        self.assertEqual(code, 0)
        target = out.getvalue().strip()
        self.assertTrue(os.path.isdir(target))
        self.assertEqual(self._head_sha(target), remote_head)
        self.assertEqual(self._current_branch(target), "feature-x")

    def test_slugifies_slash_in_branch_name_for_the_directory(self):
        out = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stdout(out):
            code = main(["branch", "feat/thing"])

        self.assertEqual(code, 0)
        target = out.getvalue().strip()
        self.assertTrue(target.endswith("repo-feat-thing"))
        self.assertEqual(self._current_branch(target), "feat/thing")

    def test_refuses_when_branch_already_exists(self):
        _run(["git", "branch", "feature-x"], self.repo)

        err = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stderr(err):
            code = main(["branch", "feature-x"])

        self.assertEqual(code, 1)
        self.assertIn("already exists", err.getvalue())

    def test_refuses_when_target_worktree_path_already_exists(self):
        target = os.path.join(self.tmp.name, "repo-feature-x")
        os.makedirs(target)

        err = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stderr(err):
            code = main(["branch", "feature-x"])

        self.assertEqual(code, 1)
        self.assertIn("already exists", err.getvalue())

    def test_refuses_and_does_not_fall_back_to_stale_local_main_when_fetch_fails(self):
        _run(["git", "remote", "set-url", "origin", "/nonexistent/path"], self.repo)

        err = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stderr(err):
            code = main(["branch", "feature-x"])

        self.assertEqual(code, 1)
        self.assertIn("failed to fetch", err.getvalue())

    def test_rejects_whitespace_only_branch_name(self):
        err = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stderr(err):
            code = main(["branch", "  "])

        self.assertEqual(code, 1)

    def test_outside_git_repository_fails_clearly(self):
        outside = tempfile.mkdtemp()
        err = io.StringIO()
        try:
            with _chdir(outside), contextlib.redirect_stderr(err):
                code = main(["branch", "feature-x"])
            self.assertEqual(code, 1)
            self.assertIn("not a Git repository", err.getvalue())
        finally:
            os.rmdir(outside)


class TestInitProjectmemFlag(unittest.TestCase):
    # `bindle init --projectmem` is a second, independent provider-lifecycle
    # seam alongside the guardrail installer (TestGuardrailLifecycleCommands
    # above): detection is the same read-only bindle.projectmem
    # .detect_projectmem() `bindle status` already uses (see
    # tests/test_projectmem.py for its own real-fixture coverage), and
    # initialization goes through Projectmem's native `pjm init` CLI —
    # Bindle never constructs `.projectmem/` state itself. Every test here
    # mocks `bindle.cli.pjm_executable`/`subprocess.run`, so none of them
    # require the real `pjm` CLI to be installed; see
    # TestInitProjectmemRealPjm below for real-CLI coverage.
    #
    # Ordering under test throughout: known Projectmem preconditions
    # (partial/conflicting `.projectmem/`, a missing `pjm` executable) are
    # checked BEFORE guardrails mutate anything — a Projectmem-side refusal
    # must never leave guardrails newly installed/reconciled behind it.
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def _mem_dir(self):
        return os.path.join(self.repo, ".projectmem")

    def _assert_guardrails_untouched(self):
        info = get_repo_info(self.repo)
        self.assertEqual(detect_git_guardrails(info), "not-installed")
        self.assertEqual(detect_claude_guardrails(info), "not-installed")

    def test_bare_init_never_touches_projectmem(self):
        with _chdir(self.repo), mock.patch(
            "bindle.cli.pjm_executable",
            side_effect=AssertionError("bare `bindle init` must not check for pjm"),
        ):
            code = main(["init"])

        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(self._mem_dir()))

    def test_projectmem_flag_is_noop_when_already_installed(self):
        # "installed" still requires no `pjm` executable at all, but
        # guardrails ARE still applied — only the Projectmem mutation step
        # is skipped.
        os.makedirs(self._mem_dir())
        with open(os.path.join(self._mem_dir(), "config.toml"), "w") as f:
            f.write("")

        out = io.StringIO()
        with _chdir(self.repo), mock.patch(
            "bindle.cli.pjm_executable",
            side_effect=AssertionError("must not invoke pjm for an already-installed repo"),
        ), contextlib.redirect_stdout(out):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)
        self.assertIn("already installed", out.getvalue())

        info = get_repo_info(self.repo)
        self.assertEqual(detect_git_guardrails(info), "installed")
        self.assertEqual(detect_claude_guardrails(info), "installed")

    def test_projectmem_flag_refuses_on_partial_state_before_guardrail_mutation(self):
        os.makedirs(self._mem_dir())
        with open(os.path.join(self._mem_dir(), "events.jsonl"), "w"):
            pass
        before = sorted(os.listdir(self._mem_dir()))

        def on_installer_call(cmd):
            raise AssertionError("guardrails must not be touched when Projectmem preflight refuses")

        err = io.StringIO()
        with _chdir(self.repo), mock.patch(
            "bindle.cli.pjm_executable",
            side_effect=AssertionError("must not invoke pjm on partial state"),
        ), _intercept_installer_call(on_installer_call), contextlib.redirect_stderr(err):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 1)
        self.assertIn("incomplete", err.getvalue())
        self.assertEqual(sorted(os.listdir(self._mem_dir())), before)
        self._assert_guardrails_untouched()

    def test_projectmem_flag_refuses_on_conflict_state_before_guardrail_mutation(self):
        with open(self._mem_dir(), "w") as f:
            f.write("occupied")

        def on_installer_call(cmd):
            raise AssertionError("guardrails must not be touched when Projectmem preflight refuses")

        err = io.StringIO()
        with _chdir(self.repo), mock.patch(
            "bindle.cli.pjm_executable",
            side_effect=AssertionError("must not invoke pjm on conflicting state"),
        ), _intercept_installer_call(on_installer_call), contextlib.redirect_stderr(err):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 1)
        self.assertIn("not a directory", err.getvalue())
        self.assertTrue(os.path.isfile(self._mem_dir()))
        self._assert_guardrails_untouched()

    def test_projectmem_flag_fails_clearly_when_pjm_missing_before_guardrail_mutation(self):
        def on_installer_call(cmd):
            raise AssertionError("guardrails must not be touched when pjm is missing")

        err = io.StringIO()
        with _chdir(self.repo), mock.patch(
            "bindle.cli.pjm_executable", return_value=None
        ), _intercept_installer_call(on_installer_call), contextlib.redirect_stderr(err):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 1)
        self.assertIn("pjm", err.getvalue())
        self.assertIn("PATH", err.getvalue())
        self.assertFalse(os.path.exists(self._mem_dir()))
        self._assert_guardrails_untouched()

    def test_projectmem_flag_succeeds_when_installed_even_with_pjm_missing(self):
        # "installed" never requires a `pjm` executable — Bindle is
        # accepting a healthy existing provider installation, not claiming
        # ownership of it.
        os.makedirs(self._mem_dir())
        with open(os.path.join(self._mem_dir(), "config.toml"), "w") as f:
            f.write("")

        with _chdir(self.repo), mock.patch("bindle.cli.pjm_executable", return_value=None):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)
        info = get_repo_info(self.repo)
        self.assertEqual(detect_git_guardrails(info), "installed")

    def test_projectmem_flag_invokes_pjm_init_with_the_narrowed_arg_set_and_worktree_cwd(self):
        pjm_calls = []

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "/usr/bin/fake-pjm":
                pjm_calls.append((cmd, kwargs.get("cwd")))
                return subprocess.CompletedProcess(cmd, 0)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch(
            "bindle.cli.pjm_executable", return_value="/usr/bin/fake-pjm"
        ), mock.patch("subprocess.run", side_effect=fake_run):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)
        self.assertEqual(len(pjm_calls), 2)
        init_cmd, init_cwd = pjm_calls[0]
        self.assertEqual(
            init_cmd,
            [
                "/usr/bin/fake-pjm",
                "init",
                "--no-hooks",
                "--no-global",
                "--no-watch",
                "--no-backfill",
                "--no-claude-md",
                "--no-mcp-config",
                "--no-structure",
                "--no-stack-detect",
            ],
        )
        self.assertEqual(init_cwd, os.path.realpath(self.repo))

        info = get_repo_info(self.repo)
        self.assertEqual(detect_git_guardrails(info), "installed")

    def test_projectmem_flag_invokes_pjm_hooks_install_with_repo_root_cwd(self):
        pjm_calls = []

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "/usr/bin/fake-pjm":
                pjm_calls.append((cmd, kwargs.get("cwd")))
                return subprocess.CompletedProcess(cmd, 0)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch(
            "bindle.cli.pjm_executable", return_value="/usr/bin/fake-pjm"
        ), mock.patch("subprocess.run", side_effect=fake_run):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)
        hooks_cmd, hooks_cwd = pjm_calls[1]
        self.assertEqual(hooks_cmd, ["/usr/bin/fake-pjm", "hooks", "install"])
        # In an ordinary (non-worktree) checkout, repo_root == worktree_root,
        # so this doesn't by itself distinguish the two — the dedicated
        # TestInitProjectmemLinkedWorktree class below proves the real
        # divergence.
        info = get_repo_info(self.repo)
        self.assertEqual(hooks_cwd, info.repo_root)

    def test_projectmem_flag_runs_guardrails_then_pjm_init_then_hooks_install_in_order(self):
        order = []

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "bash":
                order.append("guardrails")
                return _REAL_SUBPROCESS_RUN(cmd, **kwargs)
            if cmd and cmd[0] == "/usr/bin/fake-pjm" and cmd[1] == "init":
                order.append("pjm-init")
                return subprocess.CompletedProcess(cmd, 0)
            if cmd and cmd[0] == "/usr/bin/fake-pjm" and cmd[1] == "hooks":
                order.append("pjm-hooks")
                return subprocess.CompletedProcess(cmd, 0)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch(
            "bindle.cli.pjm_executable", return_value="/usr/bin/fake-pjm"
        ), mock.patch("subprocess.run", side_effect=fake_run):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)
        self.assertEqual(order, ["guardrails", "pjm-init", "pjm-hooks"])

    def test_projectmem_flag_propagates_pjm_init_exit_code_and_skips_hooks_install(self):
        pjm_calls = []

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "/usr/bin/fake-pjm":
                pjm_calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 7)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch(
            "bindle.cli.pjm_executable", return_value="/usr/bin/fake-pjm"
        ), mock.patch("subprocess.run", side_effect=fake_run):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 7)
        # `pjm init` failed — `pjm hooks install` must never be attempted.
        self.assertEqual(len(pjm_calls), 1)
        self.assertEqual(pjm_calls[0][1], "init")
        # Guardrails already succeeded and are never rolled back merely
        # because the later Projectmem step failed.
        info = get_repo_info(self.repo)
        self.assertEqual(detect_git_guardrails(info), "installed")

    def test_projectmem_flag_propagates_hooks_install_failure_and_preserves_state(self):
        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "/usr/bin/fake-pjm" and cmd[1] == "init":
                # Real `pjm init` also creates .projectmem/ as a side
                # effect — reproduce that so the "preserved on failure"
                # assertion below is meaningful.
                os.makedirs(self._mem_dir(), exist_ok=True)
                with open(os.path.join(self._mem_dir(), "config.toml"), "w") as f:
                    f.write("")
                return subprocess.CompletedProcess(cmd, 0)
            if cmd and cmd[0] == "/usr/bin/fake-pjm" and cmd[1] == "hooks":
                return subprocess.CompletedProcess(cmd, 5)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        err = io.StringIO()
        with _chdir(self.repo), mock.patch(
            "bindle.cli.pjm_executable", return_value="/usr/bin/fake-pjm"
        ), mock.patch("subprocess.run", side_effect=fake_run), contextlib.redirect_stderr(err):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 5)
        self.assertIn("hooks install", err.getvalue())
        # Neither Projectmem storage nor guardrails are rolled back merely
        # because hook installation failed.
        self.assertTrue(os.path.isfile(os.path.join(self._mem_dir(), "config.toml")))
        info = get_repo_info(self.repo)
        self.assertEqual(detect_git_guardrails(info), "installed")

    def test_projectmem_init_never_attempted_when_guardrails_fail(self):
        # Preflight passes (pjm resolved) before guardrails ever run; a
        # guardrail failure must still stop the invocation before `pjm
        # init` (or `pjm hooks install`) is actually invoked.
        pjm_calls = []

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "bash":
                return subprocess.CompletedProcess(cmd, 3)
            if cmd and cmd[0] == "/usr/bin/fake-pjm":
                pjm_calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 0)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch(
            "bindle.cli.pjm_executable", return_value="/usr/bin/fake-pjm"
        ), mock.patch("subprocess.run", side_effect=fake_run):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 3)
        self.assertEqual(pjm_calls, [])
        self.assertFalse(os.path.exists(self._mem_dir()))

    def test_remove_never_touches_projectmem(self):
        os.makedirs(self._mem_dir())
        with open(os.path.join(self._mem_dir(), "config.toml"), "w") as f:
            f.write("")

        with _chdir(self.repo):
            self.assertEqual(main(["init"]), 0)

        out = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stdout(out):
            code = main(["remove"])

        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(os.path.join(self._mem_dir(), "config.toml")))
        self.assertIn("left untouched", out.getvalue())

        info = get_repo_info(self.repo)
        self.assertEqual(detect_projectmem(info), "installed")

    def test_remove_says_nothing_about_projectmem_when_never_installed(self):
        with _chdir(self.repo):
            self.assertEqual(main(["init"]), 0)

        out = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stdout(out):
            code = main(["remove"])

        self.assertEqual(code, 0)
        self.assertNotIn("Projectmem", out.getvalue())


@unittest.skipUnless(_HAS_REAL_PJM, "requires the real `pjm` CLI on PATH")
class TestInitProjectmemRealPjm(unittest.TestCase):
    # Exercises the actual native Projectmem CLI (not mocked) — skipped
    # wherever `pjm` isn't installed, which includes CI: this repository
    # declares no Projectmem dependency (AGENTS.md), and .github/workflows
    # /ci.yml never installs it. Verified locally this session against
    # projectmem 0.2.0 (`uv tool install projectmem`).
    #
    # PROJECTMEM_HOME isolation: Projectmem 0.2.0's `initialize()`
    # unconditionally calls `register_project()`, which appends this
    # fixture's absolute path to a cross-project registry
    # (`$PROJECTMEM_HOME/projects.json`, defaulting to
    # `~/.projectmem/projects.json`) — this happens regardless of
    # `--no-global` (that flag only skips *inheriting* global memory, a
    # separate mechanism; see docs/DECISIONS.md D033). Every real `pjm`
    # invocation below runs with `PROJECTMEM_HOME` redirected to a disposable
    # temp directory so this never touches the developer's real global
    # Projectmem state (AGENTS.md "Runtime isolation").
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)

        self.registry_home = tempfile.TemporaryDirectory()
        self.env_patcher = mock.patch.dict(
            os.environ, {"PROJECTMEM_HOME": self.registry_home.name}
        )
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.registry_home.cleanup()
        self.tmp.cleanup()

    def _mem_dir(self):
        return os.path.join(self.repo, ".projectmem")

    def test_real_pjm_init_results_in_installed_state(self):
        with _chdir(self.repo):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(os.path.join(self._mem_dir(), "config.toml")))
        info = get_repo_info(self.repo)
        self.assertEqual(detect_projectmem(info), "installed")

        # Positive proof PROJECTMEM_HOME isolation is actually in effect
        # (registration lands in the isolated registry, not the real one).
        registry = os.path.join(self.registry_home.name, "projects.json")
        self.assertTrue(os.path.isfile(registry))
        with open(registry) as f:
            self.assertIn(os.path.realpath(self.repo), f.read())

    def test_real_pjm_init_uses_the_narrowed_arg_set_then_installs_hooks_separately(self):
        real_run = subprocess.run
        pjm_calls = []

        def spy_run(cmd, **kwargs):
            if cmd and os.path.basename(cmd[0]) == "pjm":
                pjm_calls.append(cmd)
            return real_run(cmd, **kwargs)

        with _chdir(self.repo), mock.patch("subprocess.run", side_effect=spy_run):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)
        self.assertEqual(len(pjm_calls), 2)
        init_cmd, hooks_cmd = pjm_calls
        for flag in (
            "--no-hooks",
            "--no-global",
            "--no-watch",
            "--no-backfill",
            "--no-claude-md",
            "--no-mcp-config",
            "--no-structure",
            "--no-stack-detect",
        ):
            self.assertIn(flag, init_cmd)
        self.assertEqual(hooks_cmd[1:], ["hooks", "install"])

    def test_real_pjm_init_does_not_create_claude_md(self):
        # --no-claude-md: Bindle is provider-neutral — Projectmem must not
        # silently append its own Claude-specific bridge prose into
        # repository policy files as a side effect of Bindle setup. The
        # fixture starts with no CLAUDE.md (_init_repo only writes
        # README.md); it must still have none afterward.
        with _chdir(self.repo):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "CLAUDE.md")))

    def test_real_pjm_init_does_not_print_mcp_config(self):
        # --no-mcp-config: Projectmem MCP registration/configuration is a
        # separate concern, not part of this seam. _print_mcp_config only
        # ever writes to stdout (no file artifact), so stdout content is
        # the only observable signal.
        out = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stdout(out):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)
        self.assertNotIn("MCP client configuration", out.getvalue())
        self.assertNotIn("mcpServers", out.getvalue())

    def test_real_pjm_init_does_not_backfill_git_history(self):
        # --no-backfill: `bindle init` must not unexpectedly ingest existing
        # Git history into working memory. _init_repo already made one
        # commit before `bindle init --projectmem` runs; without backfill,
        # events.jsonl must stay empty (the only other event-producing path,
        # git hook auto-capture, only fires on a *future* commit/merge).
        with _chdir(self.repo):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)
        events_path = os.path.join(self._mem_dir(), "events.jsonl")
        with open(events_path) as f:
            self.assertEqual(f.read().strip(), "")

    def test_real_pjm_init_does_not_build_structure_cache(self):
        # --no-structure: Bindle setup should not trigger Projectmem's
        # repository code-structure analysis.
        with _chdir(self.repo):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self._mem_dir(), "structure.json")))

    def test_real_pjm_init_does_not_run_stack_detection(self):
        # --no-stack-detect: Bindle setup should not trigger Projectmem's
        # stack/manifest analysis merely to initialize provider storage.
        # Without it, PROJECT_MAP.md keeps its native placeholder ("Status:
        # not created yet") instead of being rewritten to "Status:
        # auto-detected from project manifests ...".
        with _chdir(self.repo):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)
        with open(os.path.join(self._mem_dir(), "PROJECT_MAP.md")) as f:
            content = f.read()
        self.assertIn("Status: not created yet", content)

    def test_real_pjm_init_does_not_start_a_watcher(self):
        # --no-watch: no long-running daemon started by `bindle init`. The
        # watcher writes a PID file only when actually running — its
        # absence is the repo-local, safe-to-check signal (no need to scan
        # system processes).
        with _chdir(self.repo):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self._mem_dir(), "watch.pid")))

    def test_real_pjm_init_still_installs_git_hooks(self):
        # `pjm init` itself skips hook installation (--no-hooks); Bindle
        # installs them separately via `pjm hooks install` right after.
        # This is an ordinary (non-worktree) checkout, where repo_root ==
        # worktree_root, so `.git/hooks` here is the same directory either
        # way — see TestInitProjectmemLinkedWorktree for the case where
        # that matters.
        with _chdir(self.repo):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)
        for hook_name in ("pre-commit", "post-commit", "post-merge"):
            hook_path = os.path.join(self.repo, ".git", "hooks", hook_name)
            self.assertTrue(os.path.isfile(hook_path), f"{hook_name} hook missing")
            self.assertTrue(os.access(hook_path, os.X_OK), f"{hook_name} hook not executable")

    def test_real_pjm_init_is_idempotent_on_rerun(self):
        with _chdir(self.repo):
            self.assertEqual(main(["init", "--projectmem"]), 0)

        config = os.path.join(self._mem_dir(), "config.toml")
        before = os.path.getmtime(config)

        # The second run must short-circuit on "installed" and never invoke
        # pjm again — proven by making a second real invocation impossible.
        with _chdir(self.repo), mock.patch(
            "bindle.cli.pjm_executable",
            side_effect=AssertionError("must not re-invoke pjm once already installed"),
        ):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)
        self.assertEqual(os.path.getmtime(config), before)

    def test_remove_preserves_real_projectmem_after_real_init(self):
        with _chdir(self.repo):
            self.assertEqual(main(["init", "--projectmem"]), 0)
            self.assertEqual(main(["remove"]), 0)

        info = get_repo_info(self.repo)
        self.assertEqual(detect_projectmem(info), "installed")
        self.assertEqual(detect_git_guardrails(info), "not-installed")
        self.assertEqual(detect_claude_guardrails(info), "not-installed")

    def test_git_hook_composition_with_bindle_guardrails(self):
        # Empirically verified once already this session in a disposable
        # fixture (see the session report); automated here so it's covered
        # by scripts/check.sh wherever `pjm` is installed.
        with _chdir(self.repo):
            self.assertEqual(main(["init", "--projectmem"]), 0)

        _run(["git", "checkout", "-q", "-b", "feature-x"], self.repo)
        with open(os.path.join(self.repo, "NOTE.md"), "w") as f:
            f.write("hook composition check\n")
        _run(["git", "add", "NOTE.md"], self.repo)

        commit = subprocess.run(
            ["git", "commit", "-m", "feat: verify hook composition"],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(commit.returncode, 0, commit.stderr)

        # Projectmem's post-commit auto-capture hook backgrounds itself
        # (`... &`), so the event may land a moment after `git commit`
        # returns — poll briefly rather than assuming synchronous capture.
        events_path = os.path.join(self._mem_dir(), "events.jsonl")
        deadline = time.time() + 5
        captured_event = False
        while time.time() < deadline:
            with open(events_path) as f:
                if '"capture_source": "git_post_commit"' in f.read():
                    captured_event = True
                    break
            time.sleep(0.2)
        self.assertTrue(
            captured_event,
            "Projectmem's post-commit auto-capture hook never fired through "
            "Bindle's dispatcher — hook composition is broken",
        )

        # Protected main is unaffected by Projectmem's own hooks being
        # present: the dispatcher's policy check still runs (and still
        # blocks) before it would ever delegate to `.git/hooks/pre-commit`
        # (Projectmem's own precheck warning).
        _run(["git", "checkout", "-q", "main"], self.repo)
        with open(os.path.join(self.repo, "MAIN.md"), "w") as f:
            f.write("direct main write\n")
        _run(["git", "add", "MAIN.md"], self.repo)
        blocked = subprocess.run(
            ["git", "commit", "-m", "test: direct main write"],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("protected", blocked.stderr)


@unittest.skipUnless(_HAS_REAL_PJM, "requires the real `pjm` CLI on PATH")
class TestInitProjectmemLinkedWorktree(unittest.TestCase):
    # Regression coverage for the linked-worktree hook-installation fix
    # (docs/DECISIONS.md D033): Projectmem's native hook installer resolves
    # `<cwd>/.git/hooks` directly, which does not exist as a directory in a
    # linked worktree (`.git` there is a file, not a directory) — so
    # `bindle init --projectmem` must install Projectmem's storage
    # worktree-locally but its hooks against the repository's shared Git
    # common directory (RepoInfo.repo_root), not silently skip them.
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.main_repo = os.path.join(self.tmp.name, "main")
        _init_repo(self.main_repo)

        self.worktree = os.path.join(self.tmp.name, "linked")
        _run(["git", "worktree", "add", "-q", "-b", "feature-x", self.worktree], self.main_repo)

        self.registry_home = tempfile.TemporaryDirectory()
        self.env_patcher = mock.patch.dict(
            os.environ, {"PROJECTMEM_HOME": self.registry_home.name}
        )
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.registry_home.cleanup()
        self.tmp.cleanup()

    def _mem_dir(self):
        return os.path.join(self.worktree, ".projectmem")

    def test_fixture_premise_git_is_a_file_in_the_worktree_and_a_directory_in_main(self):
        self.assertTrue(os.path.isfile(os.path.join(self.worktree, ".git")))
        self.assertTrue(os.path.isdir(os.path.join(self.main_repo, ".git")))

    def test_init_from_linked_worktree_initializes_storage_and_installs_shared_hooks(self):
        with _chdir(self.worktree):
            code = main(["init", "--projectmem"])

        self.assertEqual(code, 0)

        # Storage stays worktree-local.
        self.assertTrue(os.path.isfile(os.path.join(self._mem_dir(), "config.toml")))
        info = get_repo_info(self.worktree)
        self.assertEqual(detect_projectmem(info), "installed")

        # Hooks land in the SHARED repository hook directory (the main
        # checkout's `.git/hooks`) — never skipped merely because
        # `<worktree>/.git` is a file, and never present under the
        # worktree's own (nonexistent) `.git/hooks`.
        self.assertFalse(os.path.isdir(os.path.join(self.worktree, ".git", "hooks")))
        for hook_name in ("pre-commit", "post-commit", "post-merge"):
            hook_path = os.path.join(self.main_repo, ".git", "hooks", hook_name)
            self.assertTrue(os.path.isfile(hook_path), f"{hook_name} missing from the shared hooks dir")
            self.assertTrue(os.access(hook_path, os.X_OK), f"{hook_name} not executable")
            with open(hook_path) as f:
                self.assertIn("projectmem auto-capture", f.read())

    def test_post_commit_capture_fires_through_bindles_dispatcher_from_the_linked_worktree(self):
        with _chdir(self.worktree):
            self.assertEqual(main(["init", "--projectmem"]), 0)

        with open(os.path.join(self.worktree, "NOTE.md"), "w") as f:
            f.write("linked worktree hook composition check\n")
        _run(["git", "add", "NOTE.md"], self.worktree)
        commit = subprocess.run(
            ["git", "commit", "-m", "feat: linked worktree hook composition"],
            cwd=self.worktree,
            capture_output=True,
            text=True,
        )
        self.assertEqual(commit.returncode, 0, commit.stderr)

        # Auto-capture backgrounds itself — poll briefly rather than
        # assuming synchronous capture (same as the ordinary-checkout
        # composition test).
        events_path = os.path.join(self._mem_dir(), "events.jsonl")
        deadline = time.time() + 5
        captured_event = False
        while time.time() < deadline:
            with open(events_path) as f:
                if '"capture_source": "git_post_commit"' in f.read():
                    captured_event = True
                    break
            time.sleep(0.2)
        self.assertTrue(
            captured_event,
            "Projectmem's post-commit auto-capture hook never fired through "
            "Bindle's dispatcher from the linked worktree",
        )

    def test_protected_main_still_blocks_in_the_main_checkout(self):
        with _chdir(self.worktree):
            self.assertEqual(main(["init", "--projectmem"]), 0)

        with open(os.path.join(self.main_repo, "MAIN.md"), "w") as f:
            f.write("direct main write\n")
        _run(["git", "add", "MAIN.md"], self.main_repo)
        blocked = subprocess.run(
            ["git", "commit", "-m", "test: direct main write"],
            cwd=self.main_repo,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("protected", blocked.stderr)


class TestInitQmdFlag(unittest.TestCase):
    # `bindle init --qmd` mirrors TestInitProjectmemFlag's shape: detection
    # is the same read-only bindle.qmd.detect_qmd() `bindle status` already
    # uses (see tests/test_qmd.py for its own real-fixture coverage), and
    # initialization goes through QMD's native CLI — Bindle never
    # constructs `.qmd/index.yml` itself. Every test here mocks
    # `bindle.qmd.qmd_executable`/`subprocess.run`, so none require the
    # real `qmd` CLI to be installed; see TestInitQmdRealCli below for real
    # -CLI coverage.
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def _qmd_dir(self):
        return os.path.join(self.repo, ".qmd")

    def _assert_guardrails_untouched(self):
        info = get_repo_info(self.repo)
        self.assertEqual(detect_git_guardrails(info), "not-installed")
        self.assertEqual(detect_claude_guardrails(info), "not-installed")

    def test_bare_init_never_touches_qmd(self):
        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable",
            side_effect=AssertionError("bare `bindle init` must not check for qmd"),
        ):
            code = main(["init"])

        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(self._qmd_dir()))

    def test_qmd_flag_is_noop_when_already_ready(self):
        qmd_dir = self._qmd_dir()
        os.makedirs(qmd_dir)
        with open(os.path.join(qmd_dir, "index.yml"), "w") as f:
            f.write(f"collections:\n  {COLLECTION_NAME}:\n    path: {os.path.realpath(self.repo)}\n")

        out = io.StringIO()

        def forbid_mutation(cmd, **kwargs):
            if cmd and os.path.basename(cmd[0]) == "fake-qmd":
                raise AssertionError("must not invoke qmd for an already-ready repo")
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ), mock.patch("subprocess.run", side_effect=forbid_mutation), contextlib.redirect_stdout(out):
            code = main(["init", "--qmd"])

        self.assertEqual(code, 0)
        self.assertIn("already initialized", out.getvalue())
        info = get_repo_info(self.repo)
        self.assertEqual(detect_git_guardrails(info), "installed")
        self.assertEqual(detect_claude_guardrails(info), "installed")

    def test_qmd_flag_adds_qmd_to_info_exclude_after_fresh_init(self):
        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "/usr/bin/fake-qmd" and cmd[1] == "init":
                os.makedirs(self._qmd_dir(), exist_ok=True)
                return subprocess.CompletedProcess(cmd, 0)
            if cmd and cmd[0] == "/usr/bin/fake-qmd" and cmd[1] == "collection":
                with open(os.path.join(self._qmd_dir(), "index.yml"), "w") as f:
                    f.write(f"collections:\n  {COLLECTION_NAME}:\n    path: {os.path.realpath(self.repo)}\n")
                return subprocess.CompletedProcess(cmd, 0)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ), mock.patch("subprocess.run", side_effect=fake_run):
            self.assertEqual(main(["init", "--qmd"]), 0)

        info = get_repo_info(self.repo)
        exclude_path = os.path.join(info.git_common_dir, "info", "exclude")
        with open(exclude_path) as f:
            self.assertIn(".qmd/", f.read().splitlines())

        # git status must not show .qmd/ as untracked clutter.
        status = subprocess.run(
            ["git", "-C", self.repo, "status", "--porcelain"], capture_output=True, text=True
        )
        self.assertNotIn(".qmd", status.stdout)

    def test_qmd_flag_adds_qmd_to_info_exclude_retroactively_when_already_ready(self):
        qmd_dir = self._qmd_dir()
        os.makedirs(qmd_dir)
        with open(os.path.join(qmd_dir, "index.yml"), "w") as f:
            f.write(f"collections:\n  {COLLECTION_NAME}:\n    path: {os.path.realpath(self.repo)}\n")

        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ):
            self.assertEqual(main(["init", "--qmd"]), 0)

        info = get_repo_info(self.repo)
        exclude_path = os.path.join(info.git_common_dir, "info", "exclude")
        with open(exclude_path) as f:
            self.assertIn(".qmd/", f.read().splitlines())

    def test_qmd_flag_refuses_on_conflict_state_before_guardrail_mutation(self):
        with open(self._qmd_dir(), "w") as f:
            f.write("occupied")

        def on_installer_call(cmd):
            raise AssertionError("guardrails must not be touched when QMD preflight refuses")

        # detect_qmd() always checks qmd availability first (unlike
        # detect_projectmem, which never calls pjm_executable at all) — a
        # fake resolved path is fine here since this test's point is that
        # guardrails must never mutate, not that qmd resolution is skipped.
        err = io.StringIO()
        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ), _intercept_installer_call(on_installer_call), contextlib.redirect_stderr(err):
            code = main(["init", "--qmd"])

        self.assertEqual(code, 1)
        self.assertIn("does not look like a Bindle-owned QMD index", err.getvalue())
        self.assertTrue(os.path.isfile(self._qmd_dir()))
        self._assert_guardrails_untouched()

    def test_qmd_flag_fails_clearly_when_qmd_missing_before_guardrail_mutation(self):
        def on_installer_call(cmd):
            raise AssertionError("guardrails must not be touched when qmd is missing")

        err = io.StringIO()
        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value=None
        ), _intercept_installer_call(on_installer_call), contextlib.redirect_stderr(err):
            code = main(["init", "--qmd"])

        self.assertEqual(code, 1)
        self.assertIn("qmd", err.getvalue())
        self.assertIn("PATH", err.getvalue())
        self.assertFalse(os.path.exists(self._qmd_dir()))
        self._assert_guardrails_untouched()

    def test_qmd_flag_runs_qmd_init_before_collection_add_always(self):
        # The single most safety-critical ordering in this integration
        # (see qmd.py's module docstring): `qmd collection add` run
        # without a prior `qmd init` in the same directory falls back to
        # the machine-global default index. This must never regress.
        calls = []

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "/usr/bin/fake-qmd":
                calls.append((cmd, kwargs.get("cwd")))
                return subprocess.CompletedProcess(cmd, 0)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ), mock.patch("subprocess.run", side_effect=fake_run):
            code = main(["init", "--qmd"])

        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        init_cmd, init_cwd = calls[0]
        self.assertEqual(init_cmd, ["/usr/bin/fake-qmd", "init"])
        self.assertEqual(init_cwd, os.path.realpath(self.repo))

        add_cmd, add_cwd = calls[1]
        self.assertEqual(
            add_cmd,
            [
                "/usr/bin/fake-qmd",
                "collection",
                "add",
                os.path.realpath(self.repo),
                "--name",
                COLLECTION_NAME,
                "--mask",
                "{*.md,docs/**/*.md,plans/**/*.md}",
            ],
        )
        self.assertEqual(add_cwd, os.path.realpath(self.repo))

    def test_qmd_flag_runs_guardrails_then_qmd_init_then_collection_add_in_order(self):
        order = []

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "bash":
                order.append("guardrails")
                return _REAL_SUBPROCESS_RUN(cmd, **kwargs)
            if cmd and cmd[0] == "/usr/bin/fake-qmd" and cmd[1] == "init":
                order.append("qmd-init")
                return subprocess.CompletedProcess(cmd, 0)
            if cmd and cmd[0] == "/usr/bin/fake-qmd" and cmd[1] == "collection":
                order.append("qmd-collection-add")
                return subprocess.CompletedProcess(cmd, 0)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ), mock.patch("subprocess.run", side_effect=fake_run):
            code = main(["init", "--qmd"])

        self.assertEqual(code, 0)
        self.assertEqual(order, ["guardrails", "qmd-init", "qmd-collection-add"])

    def test_qmd_flag_propagates_init_failure_and_skips_collection_add(self):
        calls = []

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "/usr/bin/fake-qmd":
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 9)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ), mock.patch("subprocess.run", side_effect=fake_run):
            code = main(["init", "--qmd"])

        self.assertEqual(code, 9)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "init")
        info = get_repo_info(self.repo)
        self.assertEqual(detect_git_guardrails(info), "installed")

    def test_qmd_flag_propagates_collection_add_failure_and_preserves_state(self):
        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "/usr/bin/fake-qmd" and cmd[1] == "init":
                os.makedirs(self._qmd_dir(), exist_ok=True)
                with open(os.path.join(self._qmd_dir(), "index.yml"), "w") as f:
                    f.write("collections: {}\n")
                return subprocess.CompletedProcess(cmd, 0)
            if cmd and cmd[0] == "/usr/bin/fake-qmd" and cmd[1] == "collection":
                return subprocess.CompletedProcess(cmd, 4)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        err = io.StringIO()
        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ), mock.patch("subprocess.run", side_effect=fake_run), contextlib.redirect_stderr(err):
            code = main(["init", "--qmd"])

        self.assertEqual(code, 4)
        self.assertIn("collection add", err.getvalue())
        self.assertTrue(os.path.isfile(os.path.join(self._qmd_dir(), "index.yml")))
        info = get_repo_info(self.repo)
        self.assertEqual(detect_git_guardrails(info), "installed")

    def test_qmd_mutation_never_attempted_when_guardrails_fail(self):
        calls = []

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "bash":
                return subprocess.CompletedProcess(cmd, 3)
            if cmd and cmd[0] == "/usr/bin/fake-qmd":
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 0)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ), mock.patch("subprocess.run", side_effect=fake_run):
            code = main(["init", "--qmd"])

        self.assertEqual(code, 3)
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(self._qmd_dir()))

    def test_remove_never_touches_qmd(self):
        qmd_dir = self._qmd_dir()

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "/usr/bin/fake-qmd":
                os.makedirs(qmd_dir, exist_ok=True)
                with open(os.path.join(qmd_dir, "index.yml"), "w") as f:
                    f.write(f"collections:\n  {COLLECTION_NAME}:\n    path: {os.path.realpath(self.repo)}\n")
                return subprocess.CompletedProcess(cmd, 0)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ), mock.patch("subprocess.run", side_effect=fake_run):
            self.assertEqual(main(["init", "--qmd"]), 0)

        out = io.StringIO()
        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ), contextlib.redirect_stdout(out):
            code = main(["remove"])

        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(os.path.join(qmd_dir, "index.yml")))
        self.assertIn("QMD: left untouched", out.getvalue())

        # detect_qmd() itself resolves qmd_executable() (see qmd.py) — on a
        # machine with no real `qmd` on PATH (CI) this would otherwise
        # report "unavailable" regardless of the file state actually left
        # behind, so this final check stays inside the same fake-qmd mock
        # as the calls above rather than depending on a real PATH lookup.
        info = get_repo_info(self.repo)
        with mock.patch("bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"):
            self.assertEqual(detect_qmd(info), "ready")

    def test_remove_says_nothing_about_qmd_when_never_initialized(self):
        with _chdir(self.repo):
            self.assertEqual(main(["init"]), 0)

        out = io.StringIO()
        with _chdir(self.repo), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ), contextlib.redirect_stdout(out):
            code = main(["remove"])

        self.assertEqual(code, 0)
        self.assertNotIn("QMD", out.getvalue())

    def test_projectmem_and_qmd_compose_guardrails_once_each_opt_in_once(self):
        order = []

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "bash":
                order.append("guardrails")
                return _REAL_SUBPROCESS_RUN(cmd, **kwargs)
            if cmd and cmd[0] == "/usr/bin/fake-pjm":
                order.append(f"pjm-{cmd[1]}")
                return subprocess.CompletedProcess(cmd, 0)
            if cmd and cmd[0] == "/usr/bin/fake-qmd":
                order.append(f"qmd-{cmd[1]}")
                return subprocess.CompletedProcess(cmd, 0)
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch(
            "bindle.cli.pjm_executable", return_value="/usr/bin/fake-pjm"
        ), mock.patch(
            "bindle.qmd.qmd_executable", return_value="/usr/bin/fake-qmd"
        ), mock.patch("subprocess.run", side_effect=fake_run):
            code = main(["init", "--projectmem", "--qmd"])

        self.assertEqual(code, 0)
        # Guardrails mutate exactly once, before either opt-in; Projectmem
        # (init, hooks) runs before QMD (init, collection add) — a fixed,
        # documented order, not a race.
        self.assertEqual(
            order,
            ["guardrails", "pjm-init", "pjm-hooks", "qmd-init", "qmd-collection"],
        )

    def test_projectmem_refusal_leaves_qmd_preflight_unreached_and_guardrails_untouched(self):
        # Projectmem preflight is checked first (fixed order) — a
        # Projectmem-side refusal must never let QMD preflight run, let
        # alone mutate anything.
        with open(os.path.join(self.repo, ".projectmem"), "w") as f:
            f.write("occupied")

        def on_installer_call(cmd):
            raise AssertionError("guardrails must not be touched when Projectmem preflight refuses")

        err = io.StringIO()
        with _chdir(self.repo), mock.patch(
            "bindle.cli.pjm_executable",
            side_effect=AssertionError("must not resolve pjm on conflicting state"),
        ), mock.patch(
            "bindle.qmd.qmd_executable",
            side_effect=AssertionError("qmd preflight must not run when projectmem preflight already refused"),
        ), _intercept_installer_call(on_installer_call), contextlib.redirect_stderr(err):
            code = main(["init", "--projectmem", "--qmd"])

        self.assertEqual(code, 1)
        self._assert_guardrails_untouched()
        self.assertFalse(os.path.exists(self._qmd_dir()))


@unittest.skipUnless(_HAS_REAL_QMD, "requires the real `qmd` CLI on PATH")
class TestInitQmdRealCli(unittest.TestCase):
    # Exercises the actual native QMD CLI (not mocked) — skipped wherever
    # `qmd` isn't installed, which includes CI: this repository declares no
    # QMD dependency (AGENTS.md), and .github/workflows/ci.yml never
    # installs it. Verified locally this session against the real
    # `@tobilu/qmd` CLI (2.5.3 on PATH; 2.8.3 via a disposable local
    # install used for the deeper upstream investigation).
    #
    # Isolation: QMD_CONFIG_DIR and XDG_CACHE_HOME are redirected to a
    # disposable temp directory for every real invocation below, exactly
    # mirroring TestInitProjectmemRealPjm's PROJECTMEM_HOME isolation
    # (AGENTS.md "Runtime isolation"). This integration's whole design
    # already keeps QMD state inside the repository's own `.qmd/` (see
    # qmd.py's module docstring) rather than the machine-global registry —
    # this env redirection is defense in depth, verified this session to
    # also be where QMD's own trust bookkeeping
    # (~/.config/qmd/trusted.json) lands, which is otherwise unconditional
    # global state outside `.qmd/` itself.
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)

        self.qmd_config_home = tempfile.TemporaryDirectory()
        self.qmd_cache_home = tempfile.TemporaryDirectory()
        self.env_patcher = mock.patch.dict(
            os.environ,
            {
                "QMD_CONFIG_DIR": self.qmd_config_home.name,
                "XDG_CACHE_HOME": self.qmd_cache_home.name,
            },
        )
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.qmd_config_home.cleanup()
        self.qmd_cache_home.cleanup()
        self.tmp.cleanup()

    def _qmd_dir(self):
        return os.path.join(self.repo, ".qmd")

    def _write_doc(self, rel_path, text):
        full = os.path.join(self.repo, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)

    def test_real_qmd_init_results_in_ready_state_and_indexes_docs(self):
        self._write_doc("docs/SCOPE.md", "# SCOPE\nunique-marker-alpha-9f2 lives here.\n")
        self._write_doc("plans/active/README.md", "# Active\nunique-marker-beta-3c1 lives here.\n")
        self._write_doc("src/notreally.md", "should NOT be indexed\n")

        with _chdir(self.repo):
            code = main(["init", "--qmd"])

        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(os.path.join(self._qmd_dir(), "index.yml")))
        info = get_repo_info(self.repo)

        self.assertEqual(detect_qmd(info), "ready")

        # The real disposable smoke test this slice's plan calls for: BM25
        # full-text search (no embeddings needed) actually finds the
        # indexed content, and the deliberately out-of-scope decoy doc is
        # excluded by COLLECTION_MASK.
        qmd_bin = shutil.which("qmd")
        qmd_env = qmd_mod.subprocess_env(os.path.realpath(self.repo))
        alpha = subprocess.run(
            [qmd_bin, "search", "unique-marker-alpha-9f2", "--format", "files"],
            cwd=self.repo,
            env=qmd_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(alpha.returncode, 0, alpha.stderr)
        self.assertIn("docs/SCOPE.md", alpha.stdout)

        beta = subprocess.run(
            [qmd_bin, "search", "unique-marker-beta-3c1", "--format", "files"],
            cwd=self.repo,
            env=qmd_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(beta.returncode, 0, beta.stderr)
        self.assertIn("plans/active/README.md", beta.stdout)

        decoy = subprocess.run(
            [qmd_bin, "search", "notreally", "--format", "files"],
            cwd=self.repo,
            env=qmd_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(decoy.returncode, 0, decoy.stderr)
        self.assertNotIn("notreally.md", decoy.stdout)

    def test_real_qmd_init_is_idempotent_and_does_not_duplicate_the_collection(self):
        self._write_doc("docs/SCOPE.md", "# SCOPE\nhello\n")
        with _chdir(self.repo):
            self.assertEqual(main(["init", "--qmd"]), 0)

        index_path = os.path.join(self._qmd_dir(), "index.yml")
        before = os.path.getmtime(index_path)

        # The second run must short-circuit on "ready" and never mutate
        # qmd's state again — proven by making a real `qmd init`/
        # `collection add` invocation impossible. detect_qmd() itself
        # still legitimately resolves qmd_executable() as part of
        # computing "ready" (see qmd.py), so only the mutating subcommands
        # (init, collection) are forbidden here, not resolution itself.
        def forbid_mutation(cmd, **kwargs):
            if cmd and os.path.basename(cmd[0]) == "qmd" and cmd[1] in ("init", "collection"):
                raise AssertionError(f"must not re-invoke qmd once already ready: {cmd}")
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)

        with _chdir(self.repo), mock.patch("subprocess.run", side_effect=forbid_mutation):
            code = main(["init", "--qmd"])

        self.assertEqual(code, 0)
        self.assertEqual(os.path.getmtime(index_path), before)

    def test_real_qmd_update_makes_newly_added_markdown_searchable(self):
        # This slice's own "how does retrieval become fresh?" answer:
        # QMD's native `qmd update`, run directly by the user/agent — never
        # a Bindle-owned watcher or hook.
        self._write_doc("docs/SCOPE.md", "# SCOPE\noriginal content\n")
        with _chdir(self.repo):
            self.assertEqual(main(["init", "--qmd"]), 0)

        self._write_doc("docs/NEW.md", "# New\nunique-marker-gamma-77a appears fresh.\n")

        qmd_bin = shutil.which("qmd")
        qmd_env = qmd_mod.subprocess_env(os.path.realpath(self.repo))
        before = subprocess.run(
            [qmd_bin, "search", "unique-marker-gamma-77a", "--format", "files"],
            cwd=self.repo,
            env=qmd_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(before.stdout.strip(), "")

        update = subprocess.run(
            [qmd_bin, "update"], cwd=self.repo, env=qmd_env, capture_output=True, text=True
        )
        self.assertEqual(update.returncode, 0, update.stderr)

        after = subprocess.run(
            [qmd_bin, "search", "unique-marker-gamma-77a", "--format", "files"],
            cwd=self.repo,
            env=qmd_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertIn("docs/NEW.md", after.stdout)

    def test_remove_preserves_real_qmd_collection_after_real_init(self):
        self._write_doc("docs/SCOPE.md", "# SCOPE\nhello\n")
        with _chdir(self.repo):
            self.assertEqual(main(["init", "--qmd"]), 0)
            self.assertEqual(main(["remove"]), 0)

        info = get_repo_info(self.repo)

        self.assertEqual(detect_qmd(info), "ready")
        self.assertEqual(detect_git_guardrails(info), "not-installed")
        self.assertEqual(detect_claude_guardrails(info), "not-installed")

    def test_real_qmd_init_never_creates_the_global_default_index(self):
        # Positive proof of this integration's central safety finding
        # (qmd.py's module docstring): even against the real CLI, no
        # global default index (`<config-dir>/index.yml`) is ever created
        # — everything lands inside this worktree's own `.qmd/`.
        self._write_doc("docs/SCOPE.md", "# SCOPE\nhello\n")
        with _chdir(self.repo):
            self.assertEqual(main(["init", "--qmd"]), 0)

        self.assertFalse(
            os.path.exists(os.path.join(self.qmd_config_home.name, "index.yml"))
        )


class _FakeKitModule:
    """A stand-in for a real kit module (software_engineering.py,
    spec_kit.py) used to test the `skills` CLI's own logic — argument
    wiring, desired-state read/write, exit codes — without depending on
    any real provider CLI or network access."""

    def __init__(self):
        self.status_calls = []
        self.add_calls = []
        self.remove_calls = []
        self.status_result = KitStatus(claude="not-installed", codex="not-installed")
        self.add_result = KitOpOutcome(ok=True, lines=["Claude    installed", "Codex     installed"])
        self.remove_result = KitOpOutcome(ok=True, lines=["Claude    removed", "Codex     removed"])

    def status(self, repo_info):
        self.status_calls.append(repo_info)
        return self.status_result

    def add(self, repo_info):
        self.add_calls.append(repo_info)
        return self.add_result

    def remove(self, repo_info):
        self.remove_calls.append(repo_info)
        return self.remove_result


class TestSkillsCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.fake = _FakeKitModule()
        self.fake_catalog = {
            "fake-kit": KitInfo(
                kit_id="fake-kit",
                description="A fake kit for CLI testing.",
                source="example/fake",
                module=self.fake,
            )
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_shows_the_real_catalog(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["skills", "list"])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("software-engineering", text)
        self.assertIn("spec-kit", text)
        self.assertIn("t-step/skills", text)
        self.assertIn("github/spec-kit", text)

    def test_status_outside_a_git_repository_fails_clearly(self):
        outside = tempfile.mkdtemp()
        err = io.StringIO()
        try:
            with _chdir(outside), contextlib.redirect_stderr(err):
                code = main(["skills", "status"])
            self.assertEqual(code, 1)
            self.assertIn("not a Git repository", err.getvalue())
        finally:
            os.rmdir(outside)

    def test_add_unknown_kit_fails_clearly_without_touching_desired_state(self):
        err = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stderr(err):
            code = main(["skills", "add", "nonexistent-kit"])
        self.assertEqual(code, 1)
        self.assertIn("unknown kit 'nonexistent-kit'", err.getvalue())
        self.assertIn("software-engineering", err.getvalue())
        self.assertIn("spec-kit", err.getvalue())
        self.assertFalse(os.path.exists(os.path.join(self.repo, "bindle.toml")))

    def test_remove_unknown_kit_fails_clearly(self):
        err = io.StringIO()
        with _chdir(self.repo), contextlib.redirect_stderr(err):
            code = main(["skills", "remove", "nonexistent-kit"])
        self.assertEqual(code, 1)
        self.assertIn("unknown kit 'nonexistent-kit'", err.getvalue())

    def test_add_records_desired_state_and_calls_the_kit_module(self):
        out = io.StringIO()
        with _chdir(self.repo), mock.patch.dict("bindle.skills.catalog.CATALOG", self.fake_catalog, clear=True), contextlib.redirect_stdout(
            out
        ):
            code = main(["skills", "add", "fake-kit"])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.fake.add_calls), 1)
        with open(os.path.join(self.repo, "bindle.toml")) as f:
            self.assertIn('kits = ["fake-kit"]', f.read())
        self.assertIn("Claude    installed", out.getvalue())

    def test_add_is_idempotent_in_desired_state(self):
        with _chdir(self.repo), mock.patch.dict("bindle.skills.catalog.CATALOG", self.fake_catalog, clear=True):
            main(["skills", "add", "fake-kit"])
            code = main(["skills", "add", "fake-kit"])
        self.assertEqual(code, 0)
        with open(os.path.join(self.repo, "bindle.toml")) as f:
            self.assertEqual(f.read().count("fake-kit"), 1)

    def test_add_returns_nonzero_when_the_kit_module_reports_failure_but_still_records_desired_state(self):
        self.fake.add_result = KitOpOutcome(ok=False, lines=["Claude    install failed: boom"])
        with _chdir(self.repo), mock.patch.dict("bindle.skills.catalog.CATALOG", self.fake_catalog, clear=True):
            code = main(["skills", "add", "fake-kit"])
        self.assertEqual(code, 1)
        with open(os.path.join(self.repo, "bindle.toml")) as f:
            self.assertIn("fake-kit", f.read())

    def test_remove_records_desired_state_and_calls_the_kit_module(self):
        with _chdir(self.repo), mock.patch.dict("bindle.skills.catalog.CATALOG", self.fake_catalog, clear=True):
            main(["skills", "add", "fake-kit"])
            code = main(["skills", "remove", "fake-kit"])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.fake.remove_calls), 1)
        with open(os.path.join(self.repo, "bindle.toml")) as f:
            self.assertIn("kits = []", f.read())

    def test_remove_on_a_never_added_kit_is_a_clean_no_op(self):
        # No bindle.toml exists yet, and the kit was never desired — remove
        # must not fabricate a config file just to record an empty list.
        with _chdir(self.repo), mock.patch.dict("bindle.skills.catalog.CATALOG", self.fake_catalog, clear=True):
            code = main(["skills", "remove", "fake-kit"])
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "bindle.toml")))

    def test_remove_is_idempotent_once_a_kit_has_been_desired(self):
        with _chdir(self.repo), mock.patch.dict("bindle.skills.catalog.CATALOG", self.fake_catalog, clear=True):
            main(["skills", "add", "fake-kit"])
            main(["skills", "remove", "fake-kit"])
            code = main(["skills", "remove", "fake-kit"])
        self.assertEqual(code, 0)
        with open(os.path.join(self.repo, "bindle.toml")) as f:
            self.assertIn("kits = []", f.read())

    def test_status_reports_desired_flag_and_per_harness_state(self):
        self.fake.status_result = KitStatus(claude="installed", codex="partial")
        with _chdir(self.repo), mock.patch.dict("bindle.skills.catalog.CATALOG", self.fake_catalog, clear=True):
            main(["skills", "add", "fake-kit"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["skills", "status"])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("fake-kit", text)
        self.assertIn("installed", text)
        self.assertIn("partial", text)

    def test_status_shows_not_desired_before_any_add(self):
        out = io.StringIO()
        with _chdir(self.repo), mock.patch.dict("bindle.skills.catalog.CATALOG", self.fake_catalog, clear=True), contextlib.redirect_stdout(
            out
        ):
            code = main(["skills", "status"])
        self.assertEqual(code, 0)
        self.assertIn("no", out.getvalue())


if __name__ == "__main__":
    unittest.main()
