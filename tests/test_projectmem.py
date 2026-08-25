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
    # No dependency on the `pjm` CLI being installed: fixtures reproduce
    # exactly the marker projectmem's own storage.py
    # (`_is_project_mem_dir`) uses to recognize an initialized project —
    # a `.projectmem/` directory containing `config.toml` — rather than
    # shelling out to a tool that may not be on PATH, and rather than
    # duplicating projectmem's own test suite.
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
        # Matches projectmem's own _is_project_mem_dir predicate: existence
        # of config.toml is sufficient, regardless of which other files
        # (events.jsonl, issues/, summary.md, ...) are present.
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
        # os.path.exists() is false for a dangling symlink, which would
        # otherwise misread this as "not-installed" even though the path
        # entry is occupied and `pjm init`'s own
        # `project_dir.mkdir(exist_ok=True)` would fail against it.
        link = os.path.join(self.repo, ".projectmem")
        os.symlink(os.path.join(self.repo, "nonexistent-target"), link)
        self.assertEqual(detect_projectmem(self.info), "conflict")
        # Never followed or repaired: the dangling symlink is left exactly
        # as it was.
        self.assertTrue(os.path.islink(link))
        self.assertFalse(os.path.exists(link))

    def test_installed_when_config_toml_is_not_a_regular_file(self):
        # Projectmem's own _is_project_mem_dir predicate is
        # `candidate.is_dir() and (candidate / CONFIG_FILE).exists()` —
        # plain existence, not is_file(). A config.toml that is itself a
        # directory still satisfies Projectmem's own recognition, so
        # Bindle must report "installed" here too rather than tightening
        # the marker into a stronger, non-native check.
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
        # A .projectmem/ that exists in a linked worktree's parent
        # directory (e.g. a sibling worktree created by `bindle branch`,
        # both under the same parent) must not be reported as installed
        # for a worktree that has no .projectmem/ of its own.
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
    # pjm_executable() is a thin shutil.which() wrapper — Bindle declares no
    # Projectmem package dependency (AGENTS.md), so this is the only
    # supported way it locates the native CLI.
    def test_returns_none_when_pjm_is_not_on_path(self):
        with mock.patch("shutil.which", return_value=None) as which:
            self.assertIsNone(pjm_executable())
        which.assert_called_once_with("pjm")

    def test_returns_the_resolved_path_when_pjm_is_on_path(self):
        with mock.patch("shutil.which", return_value="/usr/local/bin/pjm"):
            self.assertEqual(pjm_executable(), "/usr/local/bin/pjm")


class TestPjmInitArgs(unittest.TestCase):
    # Narrowed to core repository-local storage setup only: every flag
    # suppresses a native `pjm init` convenience that reaches outside that
    # scope (docs/DECISIONS.md D033). --no-hooks IS included — Projectmem's
    # own hook installer resolves `<cwd>/.git/hooks` directly, which
    # silently no-ops in a linked worktree (`.git` is a file there, not
    # that directory). Hooks are installed separately via
    # PJM_HOOKS_INSTALL_ARGS, against the repository's shared Git common
    # directory, so they still take effect and still compose with Bindle's
    # dispatcher — see cli.py's `_cmd_init`.
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
