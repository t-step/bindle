import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle import __version__
from bindle.cli import _LIFECYCLE_COMMANDS, main

TOP_LEVEL_COMMANDS = [*_LIFECYCLE_COMMANDS, "repo", "branch"]


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


if __name__ == "__main__":
    unittest.main()
