import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle import git_local_exclude


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


class GitRepoTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.git_common_dir = os.path.join(self.repo, ".git")

    def tearDown(self):
        self.tmp.cleanup()

    def _exclude_path(self):
        return git_local_exclude.info_exclude_path(self.git_common_dir)


class TestIsPathTracked(GitRepoTestCase):
    def test_untracked_path_is_false(self):
        self.assertFalse(git_local_exclude.is_path_tracked(self.repo, "nope.txt"))

    def test_tracked_path_is_true(self):
        self.assertTrue(git_local_exclude.is_path_tracked(self.repo, "README.md"))

    def test_git_failure_raises_git_command_error_not_false(self):
        # A genuine `git ls-files` failure (not simply "no match") must
        # never read as an ordinary "not tracked" answer — a caller that
        # depends on trackedness for safety needs to be able to tell the
        # two apart.
        not_a_repo = os.path.join(self.tmp.name, "not-a-repo")
        os.makedirs(not_a_repo)
        with self.assertRaises(git_local_exclude.GitCommandError):
            git_local_exclude.is_path_tracked(not_a_repo, "foo.txt")

    def test_git_command_error_is_an_os_error(self):
        # Subclassing OSError is load-bearing: it lets an existing
        # best-effort caller (qmd.ensure_gitignored's `except OSError:
        # pass`) keep swallowing this failure unchanged, while a
        # safety-critical caller can still catch it explicitly and fail
        # closed instead.
        self.assertTrue(issubclass(git_local_exclude.GitCommandError, OSError))


class TestIsPathIgnored(GitRepoTestCase):
    def test_not_ignored_by_default(self):
        self.assertFalse(git_local_exclude.is_path_ignored(self.repo, "scratch.tmp"))

    def test_ignored_via_tracked_gitignore(self):
        with open(os.path.join(self.repo, ".gitignore"), "w") as f:
            f.write("*.tmp\n")
        _run(["git", "add", ".gitignore"], self.repo)
        _run(["git", "commit", "-m", "add gitignore"], self.repo)
        self.assertTrue(git_local_exclude.is_path_ignored(self.repo, "scratch.tmp"))

    def test_ignored_via_info_exclude(self):
        os.makedirs(os.path.dirname(self._exclude_path()), exist_ok=True)
        with open(self._exclude_path(), "w") as f:
            f.write("scratch.tmp\n")
        self.assertTrue(git_local_exclude.is_path_ignored(self.repo, "scratch.tmp"))


class TestEnsureLineExcluded(GitRepoTestCase):
    def test_adds_a_line_to_info_exclude(self):
        git_local_exclude.ensure_line_excluded(self.git_common_dir, "/foo/bar")
        with open(self._exclude_path()) as f:
            self.assertIn("/foo/bar", f.read().splitlines())

    def test_never_writes_to_tracked_gitignore(self):
        gitignore = os.path.join(self.repo, ".gitignore")
        with open(gitignore, "w") as f:
            f.write("*.log\n")
        _run(["git", "add", ".gitignore"], self.repo)
        _run(["git", "commit", "-m", "add gitignore"], self.repo)

        git_local_exclude.ensure_line_excluded(self.git_common_dir, "/foo/bar")

        with open(gitignore) as f:
            self.assertEqual(f.read(), "*.log\n")

    def test_idempotent_no_duplicate_line(self):
        git_local_exclude.ensure_line_excluded(self.git_common_dir, "/foo/bar")
        git_local_exclude.ensure_line_excluded(self.git_common_dir, "/foo/bar")
        git_local_exclude.ensure_line_excluded(self.git_common_dir, "/foo/bar")
        with open(self._exclude_path()) as f:
            lines = f.read().splitlines()
        self.assertEqual(lines.count("/foo/bar"), 1)

    def test_preserves_existing_exclude_content(self):
        os.makedirs(os.path.dirname(self._exclude_path()), exist_ok=True)
        with open(self._exclude_path(), "w") as f:
            f.write("*.tmp\nsome-other-tool/\n")

        git_local_exclude.ensure_line_excluded(self.git_common_dir, "/foo/bar")

        with open(self._exclude_path()) as f:
            lines = f.read().splitlines()
        self.assertEqual(lines, ["*.tmp", "some-other-tool/", "/foo/bar"])

    def test_appends_newline_when_file_lacks_trailing_newline(self):
        os.makedirs(os.path.dirname(self._exclude_path()), exist_ok=True)
        with open(self._exclude_path(), "w") as f:
            f.write("*.tmp")  # no trailing newline

        git_local_exclude.ensure_line_excluded(self.git_common_dir, "/foo/bar")

        with open(self._exclude_path()) as f:
            self.assertEqual(f.read(), "*.tmp\n/foo/bar\n")


class TestSqliteArtifactExcludeLines(unittest.TestCase):
    def test_returns_root_anchored_db_plus_three_sidecars(self):
        lines = git_local_exclude.sqlite_artifact_exclude_lines(".bindle-work/ledger.sqlite3")
        self.assertEqual(
            lines,
            (
                "/.bindle-work/ledger.sqlite3",
                "/.bindle-work/ledger.sqlite3-journal",
                "/.bindle-work/ledger.sqlite3-wal",
                "/.bindle-work/ledger.sqlite3-shm",
            ),
        )

    def test_every_line_is_root_anchored(self):
        lines = git_local_exclude.sqlite_artifact_exclude_lines("nested/dir/db.sqlite3")
        self.assertTrue(all(line.startswith("/") for line in lines))


if __name__ == "__main__":
    unittest.main()
