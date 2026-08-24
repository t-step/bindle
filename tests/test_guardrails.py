import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle.guardrails import (
    GuardrailDetectionError,
    detect_claude_guardrails,
    detect_git_guardrails,
    installer_path,
)
from bindle.repo import get_repo_info


def _run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path):
    os.makedirs(path, exist_ok=True)
    _run(["git", "init", "--initial-branch=main"], path)
    _run(["git", "config", "user.email", "test@example.com"], path)
    _run(["git", "config", "user.name", "Test"], path)
    _run(["git", "commit", "--allow-empty", "-m", "init"], path)


def _apply_guardrails(repo):
    subprocess.run(
        ["bash", str(installer_path()), "--apply", "--repo", repo],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "BINDLE_PYTHON": sys.executable},
    )


class TestDetectGuardrailsRealFixtures(unittest.TestCase):
    # These functions are the read-only inspection seam `bindle status`
    # (cli.py) drives — proven here directly against real repository state,
    # not mocked away, since they're exactly the ownership predicates
    # install-guardrails.sh's --apply/--uninstall already enforce (see
    # bin/test-guardrail-status.sh for the full five-state matrix at the
    # installer level; this proves the Python entry points parse that
    # correctly).
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.info = get_repo_info(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_not_installed_before_init(self):
        self.assertEqual(detect_git_guardrails(self.info), "not-installed")
        self.assertEqual(detect_claude_guardrails(self.info), "not-installed")

    def test_installed_after_init(self):
        _apply_guardrails(self.repo)
        self.assertEqual(detect_git_guardrails(self.info), "installed")
        self.assertEqual(detect_claude_guardrails(self.info), "installed")

    def test_conflict_when_foreign_hookspath_present(self):
        foreign = os.path.join(self.tmp.name, "foreign-hooks")
        os.makedirs(foreign)
        _run(["git", "config", "--local", "core.hooksPath", foreign], self.repo)
        self.assertEqual(detect_git_guardrails(self.info), "conflict")

    def test_detection_never_mutates_the_repository(self):
        _apply_guardrails(self.repo)
        before = subprocess.run(
            ["git", "config", "--local", "--list"], cwd=self.repo, capture_output=True, text=True
        ).stdout
        detect_git_guardrails(self.info)
        detect_claude_guardrails(self.info)
        detect_git_guardrails(self.info)
        detect_claude_guardrails(self.info)
        after = subprocess.run(
            ["git", "config", "--local", "--list"], cwd=self.repo, capture_output=True, text=True
        ).stdout
        self.assertEqual(before, after)


class TestDetectGuardrailsErrorHandling(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.info = get_repo_info(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_raises_clearly_when_installer_is_missing(self):
        with mock.patch(
            "bindle.guardrails.installer_path",
            return_value=Path("/nonexistent/install-guardrails.sh"),
        ):
            with self.assertRaises(GuardrailDetectionError) as cm:
                detect_git_guardrails(self.info)
        self.assertIn("guardrail installer not found", str(cm.exception))

    def test_raises_clearly_when_the_installer_exits_nonzero(self):
        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="boom"
            ),
        ):
            with self.assertRaises(GuardrailDetectionError) as cm:
                detect_claude_guardrails(self.info)
        self.assertIn("boom", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
