import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle.repo import NotAGitRepositoryError, get_repo_info


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


class TestRepoInfo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_normal_repository(self):
        info = get_repo_info(self.repo)

        self.assertEqual(os.path.realpath(info.worktree_root), os.path.realpath(self.repo))
        self.assertEqual(
            os.path.realpath(info.repo_root), os.path.realpath(self.repo)
        )
        self.assertEqual(os.path.basename(info.git_common_dir), ".git")
        self.assertEqual(info.git_dir, info.git_common_dir)
        self.assertEqual(info.branch, "main")
        self.assertFalse(info.detached)
        self.assertEqual(len(info.head_sha), 40)

    def test_nested_subdirectory(self):
        nested = os.path.join(self.repo, "a", "b")
        os.makedirs(nested)

        info = get_repo_info(nested)

        self.assertEqual(os.path.realpath(info.worktree_root), os.path.realpath(self.repo))

    def test_detached_head(self):
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        _run(["git", "checkout", sha], self.repo)

        info = get_repo_info(self.repo)

        self.assertTrue(info.detached)
        self.assertIsNone(info.branch)
        self.assertEqual(info.head_sha, sha)

    def test_non_git_directory_fails_clearly(self):
        outside = tempfile.mkdtemp()
        try:
            with self.assertRaises(NotAGitRepositoryError):
                get_repo_info(outside)
        finally:
            os.rmdir(outside)

    def test_linked_worktree_shares_git_common_dir(self):
        linked = os.path.join(self.tmp.name, "linked")
        _run(["git", "worktree", "add", linked, "-b", "linked-branch"], self.repo)

        primary_info = get_repo_info(self.repo)
        linked_info = get_repo_info(linked)

        self.assertNotEqual(
            os.path.realpath(primary_info.worktree_root),
            os.path.realpath(linked_info.worktree_root),
        )
        self.assertEqual(primary_info.git_common_dir, linked_info.git_common_dir)
        self.assertEqual(primary_info.repo_root, linked_info.repo_root)
        self.assertEqual(linked_info.branch, "linked-branch")


if __name__ == "__main__":
    unittest.main()
