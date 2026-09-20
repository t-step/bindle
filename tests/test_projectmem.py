import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle.projectmem import (
    PJM_HOOKS_INSTALL_ARGS,
    PJM_INIT_ARGS,
    detect_projectmem,
    pjm_executable,
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


class TestDetectProjectmemRealFixtures(unittest.TestCase):
    # Fixtures mirror projectmem's marker (`.projectmem/config.toml`): no `pjm`.
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.info = get_repo_info(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_not_installed_when_no_projectmem_directory_exists(self):
        self.assertEqual(detect_projectmem(self.info), "not-installed")

    def test_installed_when_config_toml_present(self):
        mem_dir = os.path.join(self.repo, ".projectmem")
        os.makedirs(mem_dir)
        with open(os.path.join(mem_dir, "config.toml"), "w") as f:
            f.write('summary_size_limit_kb = 20\nrecent_days = 30\nproject_description = ""\n')
        self.assertEqual(detect_projectmem(self.info), "installed")

    def test_installed_recognizes_directory_via_native_marker_alone(self):
        # Mirrors projectmem's `_is_project_mem_dir`: config.toml suffices.
        mem_dir = os.path.join(self.repo, ".projectmem")
        os.makedirs(mem_dir)
        with open(os.path.join(mem_dir, "config.toml"), "w") as f:
            f.write("")
        self.assertEqual(detect_projectmem(self.info), "installed")

    def test_partial_when_directory_exists_without_config_toml(self):
        mem_dir = os.path.join(self.repo, ".projectmem")
        os.makedirs(mem_dir)
        os.makedirs(os.path.join(mem_dir, "issues"))
        with open(os.path.join(mem_dir, "events.jsonl"), "w"):
            pass
        self.assertEqual(detect_projectmem(self.info), "partial")

    def test_conflict_when_projectmem_path_is_a_file(self):
        with open(os.path.join(self.repo, ".projectmem"), "w") as f:
            f.write("not a directory")
        self.assertEqual(detect_projectmem(self.info), "conflict")

    def test_conflict_when_projectmem_is_a_dangling_symlink(self):
        # exists() misses a dangling symlink, yet `pjm init` would fail on it.
        link = os.path.join(self.repo, ".projectmem")
        os.symlink(os.path.join(self.repo, "nonexistent-target"), link)
        self.assertEqual(detect_projectmem(self.info), "conflict")
        # Never followed or repaired.
        self.assertTrue(os.path.islink(link))
        self.assertFalse(os.path.exists(link))

    def test_installed_when_config_toml_is_not_a_regular_file(self):
        # Projectmem's marker is plain .exists(); don't tighten to is_file().
        mem_dir = os.path.join(self.repo, ".projectmem")
        os.makedirs(mem_dir)
        os.makedirs(os.path.join(mem_dir, "config.toml"))
        self.assertEqual(detect_projectmem(self.info), "installed")

    def test_detection_never_mutates_the_repository(self):
        mem_dir = os.path.join(self.repo, ".projectmem")
        os.makedirs(mem_dir)
        with open(os.path.join(mem_dir, "config.toml"), "w") as f:
            f.write('summary_size_limit_kb = 20\n')
        before = sorted(os.listdir(mem_dir))
        detect_projectmem(self.info)
        detect_projectmem(self.info)
        after = sorted(os.listdir(mem_dir))
        self.assertEqual(before, after)

    def test_scoped_to_worktree_root_not_a_parent_directory(self):
        # A parent directory's .projectmem/ (sibling worktree) must not count.
        parent = os.path.dirname(self.repo)
        parent_mem_dir = os.path.join(parent, ".projectmem")
        os.makedirs(parent_mem_dir)
        with open(os.path.join(parent_mem_dir, "config.toml"), "w") as f:
            f.write("")
        try:
            self.assertEqual(detect_projectmem(self.info), "not-installed")
        finally:
            os.remove(os.path.join(parent_mem_dir, "config.toml"))
            os.rmdir(parent_mem_dir)


class TestPjmExecutable(unittest.TestCase):
    # Thin shutil.which() wrapper; no Projectmem dependency (AGENTS.md).
    def test_returns_none_when_pjm_is_not_on_path(self):
        with mock.patch("shutil.which", return_value=None) as which:
            self.assertIsNone(pjm_executable())
        which.assert_called_once_with("pjm")

    def test_returns_the_resolved_path_when_pjm_is_on_path(self):
        with mock.patch("shutil.which", return_value="/usr/local/bin/pjm"):
            self.assertEqual(pjm_executable(), "/usr/local/bin/pjm")


class TestPjmInitArgs(unittest.TestCase):
    # Core repo-local setup only; each flag drops a `pjm init` extra (D033).
    # --no-hooks: pjm resolves <cwd>/.git/hooks, a no-op in linked worktrees;
    # hooks go in via PJM_HOOKS_INSTALL_ARGS instead (cli.py `_cmd_init`).
    def test_narrows_to_core_repo_local_setup_only(self):
        self.assertEqual(
            PJM_INIT_ARGS,
            (
                "init",
                "--no-hooks",
                "--no-global",
                "--no-watch",
                "--no-backfill",
                "--no-claude-md",
                "--no-mcp-config",
                "--no-structure",
                "--no-stack-detect",
            ),
        )


class TestPjmHooksInstallArgs(unittest.TestCase):
    def test_is_the_native_hooks_install_command(self):
        self.assertEqual(PJM_HOOKS_INSTALL_ARGS, ("hooks", "install"))


if __name__ == "__main__":
    unittest.main()
