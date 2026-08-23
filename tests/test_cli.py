import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle import __version__
from bindle.cli import main


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


if __name__ == "__main__":
    unittest.main()
