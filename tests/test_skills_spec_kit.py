import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle.repo import get_repo_info
from bindle.skills import spec_kit as sk

_HAS_REAL_SPECIFY = shutil.which("specify") is not None


def _run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path):
    os.makedirs(path, exist_ok=True)
    _run(["git", "init", "--initial-branch=main"], path)
    _run(["git", "config", "user.email", "test@example.com"], path)
    _run(["git", "config", "user.name", "Test"], path)
    _run(["git", "commit", "--allow-empty", "-m", "init"], path)


class TestStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.info = get_repo_info(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_not_installed_when_no_specify_dir_and_no_specify_binary_needed(self):
        with mock.patch.object(sk, "_specify_executable", side_effect=AssertionError("must not shell out")):
            status = sk.status(self.info)
        self.assertEqual(status.claude, "not-installed")
        self.assertEqual(status.codex, "not-installed")

    def test_unavailable_when_specify_dir_exists_but_binary_missing(self):
        os.makedirs(os.path.join(self.repo, ".specify"))
        with mock.patch.object(sk, "_specify_executable", return_value=None):
            status = sk.status(self.info)
        self.assertEqual(status.claude, "unavailable")
        self.assertEqual(status.codex, "unavailable")

    def test_reports_installed_integrations_from_specify_status_json(self):
        os.makedirs(os.path.join(self.repo, ".specify"))

        def fake_run(cmd, **kwargs):
            self.assertEqual(cmd[1:4], ["integration", "status", "--json"])
            return subprocess.CompletedProcess(
                cmd, 0, stdout=json.dumps({"installed_integrations": ["claude"]}), stderr=""
            )

        with mock.patch.object(sk, "_specify_executable", return_value="specify"), mock.patch(
            "subprocess.run", side_effect=fake_run
        ):
            status = sk.status(self.info)

        self.assertEqual(status.claude, "installed")
        self.assertEqual(status.codex, "not-installed")

    def test_status_command_failure_reports_unavailable_not_not_installed(self):
        # A provider error ("I could not determine state") must never be
        # silently collapsed into "state is absent" — .specify/ existing
        # but the native status command failing is a real "can't tell",
        # reported as `unavailable` on both harnesses.
        os.makedirs(os.path.join(self.repo, ".specify"))

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Error: something broke")

        with mock.patch.object(sk, "_specify_executable", return_value="specify"), mock.patch(
            "subprocess.run", side_effect=fake_run
        ):
            status = sk.status(self.info)

        self.assertEqual(status.claude, "unavailable")
        self.assertEqual(status.codex, "unavailable")

    def test_status_command_malformed_json_reports_unavailable(self):
        os.makedirs(os.path.join(self.repo, ".specify"))

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout="not json", stderr="")

        with mock.patch.object(sk, "_specify_executable", return_value="specify"), mock.patch(
            "subprocess.run", side_effect=fake_run
        ):
            status = sk.status(self.info)

        self.assertEqual(status.claude, "unavailable")
        self.assertEqual(status.codex, "unavailable")

    def test_status_trusts_valid_installed_integrations_even_on_nonzero_exit(self):
        # Real, verified specify behavior: `integration status --json`
        # exits 1 once every integration has been removed
        # (.specify/integration.json missing), but still emits a
        # well-formed installed_integrations: [] — a genuine "zero
        # installed" answer, not a failed query. Exit-code gating would
        # misreport this as `unavailable`; the correct report is
        # `not-installed` for both harnesses.
        os.makedirs(os.path.join(self.repo, ".specify"))

        def fake_run(cmd, **kwargs):
            body = {
                "status": "error",
                "installed_integrations": [],
                "findings": [{"code": "integration-state-missing"}],
            }
            return subprocess.CompletedProcess(cmd, 1, stdout=json.dumps(body), stderr="")

        with mock.patch.object(sk, "_specify_executable", return_value="specify"), mock.patch(
            "subprocess.run", side_effect=fake_run
        ):
            status = sk.status(self.info)

        self.assertEqual(status.claude, "not-installed")
        self.assertEqual(status.codex, "not-installed")


class TestAddRemoveMocked(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.info = get_repo_info(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_reports_unavailable_for_both_harnesses_when_specify_missing(self):
        with mock.patch.object(sk, "_specify_executable", return_value=None):
            outcome = sk.add(self.info)
        self.assertTrue(outcome.ok)
        self.assertTrue(all("unavailable" in line for line in outcome.lines))

    def test_add_bootstraps_via_specify_init_when_specify_dir_absent(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[1] == "init":
                os.makedirs(os.path.join(self.repo, ".specify"))
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if cmd[1:4] == ["integration", "status", "--json"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=json.dumps({"installed_integrations": ["claude"]}), stderr=""
                )
            if cmd[1:3] == ["integration", "install"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            raise AssertionError(f"unexpected command: {cmd}")

        with mock.patch.object(sk, "_specify_executable", return_value="specify"), mock.patch(
            "subprocess.run", side_effect=fake_run
        ):
            outcome = sk.add(self.info)

        self.assertTrue(outcome.ok, outcome.lines)
        init_calls = [c for c in calls if c[1] == "init"]
        self.assertEqual(len(init_calls), 1)
        self.assertIn("--force", init_calls[0])
        self.assertIn("--non-interactive", init_calls[0])
        install_calls = [c for c in calls if c[1:3] == ["integration", "install"]]
        self.assertEqual([c[3] for c in install_calls], ["codex"])

    def test_add_installs_missing_harness_only_when_specify_dir_already_exists(self):
        os.makedirs(os.path.join(self.repo, ".specify"))
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[1:4] == ["integration", "status", "--json"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=json.dumps({"installed_integrations": ["claude"]}), stderr=""
                )
            if cmd[1:3] == ["integration", "install"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            raise AssertionError(f"unexpected command: {cmd}")

        with mock.patch.object(sk, "_specify_executable", return_value="specify"), mock.patch(
            "subprocess.run", side_effect=fake_run
        ):
            outcome = sk.add(self.info)

        self.assertTrue(outcome.ok, outcome.lines)
        install_calls = [c for c in calls if c[1:3] == ["integration", "install"]]
        self.assertEqual([c[3] for c in install_calls], ["codex"])
        self.assertTrue(any("init" == c[1] for c in calls) is False)

    def test_remove_never_deletes_specify_directory(self):
        specify_dir = os.path.join(self.repo, ".specify")
        os.makedirs(specify_dir)

        def fake_run(cmd, **kwargs):
            if cmd[1:4] == ["integration", "status", "--json"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=json.dumps({"installed_integrations": ["claude", "codex"]}), stderr=""
                )
            if cmd[1:3] == ["integration", "uninstall"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            raise AssertionError(f"unexpected command: {cmd}")

        with mock.patch.object(sk, "_specify_executable", return_value="specify"), mock.patch(
            "subprocess.run", side_effect=fake_run
        ):
            outcome = sk.remove(self.info)

        self.assertTrue(outcome.ok, outcome.lines)
        self.assertTrue(os.path.isdir(specify_dir))

    def test_remove_is_a_no_op_when_specify_dir_absent(self):
        with mock.patch.object(sk, "_specify_executable", return_value="specify"), mock.patch(
            "subprocess.run", side_effect=AssertionError("must not shell out")
        ):
            outcome = sk.remove(self.info)
        self.assertTrue(outcome.ok)
        self.assertTrue(all("already not installed" in line for line in outcome.lines))

    def test_remove_refuses_and_preserves_state_when_specify_dir_present_but_binary_missing(self):
        # .specify/ existing but no `specify` binary means removal cannot
        # be safely performed — this must never report success/"nothing
        # to remove" while leaving real integration state untouched.
        os.makedirs(os.path.join(self.repo, ".specify"))

        with mock.patch.object(sk, "_specify_executable", return_value=None), mock.patch(
            "subprocess.run", side_effect=AssertionError("must not shell out")
        ):
            outcome = sk.remove(self.info)

        self.assertFalse(outcome.ok)
        self.assertTrue(all("unavailable" in line for line in outcome.lines))
        self.assertTrue(os.path.isdir(os.path.join(self.repo, ".specify")))

    def test_remove_refuses_and_preserves_state_when_status_command_fails(self):
        os.makedirs(os.path.join(self.repo, ".specify"))

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

        with mock.patch.object(sk, "_specify_executable", return_value="specify"), mock.patch(
            "subprocess.run", side_effect=fake_run
        ):
            outcome = sk.remove(self.info)

        self.assertFalse(outcome.ok)
        self.assertTrue(all("unavailable" in line for line in outcome.lines))

    def test_install_one_does_not_crash_when_status_check_fails(self):
        # _installed_integrations() returning None (a failed status
        # check) must not crash `key in None` inside _install_one — it
        # should just attempt the install rather than assume "already
        # installed".
        os.makedirs(os.path.join(self.repo, ".specify"))
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[1:4] == ["integration", "status", "--json"]:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")
            if cmd[1:3] == ["integration", "install"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            raise AssertionError(f"unexpected command: {cmd}")

        with mock.patch.object(sk, "_specify_executable", return_value="specify"), mock.patch(
            "subprocess.run", side_effect=fake_run
        ):
            outcome = sk.add(self.info)

        self.assertTrue(outcome.ok, outcome.lines)
        install_calls = [c for c in calls if c[1:3] == ["integration", "install"]]
        self.assertEqual(sorted(c[3] for c in install_calls), ["claude", "codex"])


@unittest.skipUnless(_HAS_REAL_SPECIFY, "specify CLI not installed")
class TestRealSpecifyIntegration(unittest.TestCase):
    """Exercises the real `specify` CLI. Confirmed empirically (this
    session) that `specify` operates entirely within the target
    directory (`--here`) and touches no global/user-level state, so no
    isolation env override is needed here — unlike the Claude harness."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.info = get_repo_info(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_then_remove_round_trip(self):
        outcome = sk.add(self.info)
        self.assertTrue(outcome.ok, outcome.lines)
        self.assertEqual(sk.status(self.info), sk.KitStatus(claude="installed", codex="installed"))
        self.assertTrue(os.path.isdir(os.path.join(self.repo, ".specify")))

        remove_outcome = sk.remove(self.info)
        self.assertTrue(remove_outcome.ok, remove_outcome.lines)
        self.assertEqual(sk.status(self.info), sk.KitStatus(claude="not-installed", codex="not-installed"))
        # .specify/ itself is never deleted by remove().
        self.assertTrue(os.path.isdir(os.path.join(self.repo, ".specify")))

    def test_add_is_idempotent(self):
        sk.add(self.info)
        second = sk.add(self.info)
        self.assertTrue(second.ok, second.lines)
        self.assertTrue(all("already installed" in line for line in second.lines))

    def test_add_from_a_linked_worktree_is_worktree_local_since_specify_leaves_its_output_untracked(self):
        # `specify init`/`specify integration install` create .specify/,
        # .claude/skills/speckit-*, and .agents/skills/speckit-* as
        # UNTRACKED files (confirmed empirically this session) — Spec
        # Kit's own choice, not Bindle's. Untracked content is
        # worktree-local (docs/WORKTREES.md), so a sibling linked
        # worktree genuinely does not see it unless the repository
        # commits it itself. Bindle does not force that decision.
        wt_path = os.path.join(self.tmp.name, "wt")
        _run(["git", "worktree", "add", "-b", "wt-branch", wt_path], self.repo)
        wt_info = get_repo_info(wt_path)

        sk.add(self.info)
        self.assertEqual(sk.status(self.info), sk.KitStatus(claude="installed", codex="installed"))

        # The sibling worktree runs `specify` from ITS OWN directory, and
        # correctly reports no adoption there — it never crashes or
        # misattributes the main checkout's state (`.git` being a file,
        # not a directory, in a linked worktree does not confuse it).
        status = sk.status(wt_info)
        self.assertEqual(status, sk.KitStatus(claude="not-installed", codex="not-installed"))

        # Adding it independently from the worktree works correctly too.
        wt_outcome = sk.add(wt_info)
        self.assertTrue(wt_outcome.ok, wt_outcome.lines)
        self.assertEqual(sk.status(wt_info), sk.KitStatus(claude="installed", codex="installed"))


if __name__ == "__main__":
    unittest.main()
