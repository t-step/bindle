import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle.qmd import (
    COLLECTION_MASK,
    COLLECTION_NAME,
    QMD_INIT_ARGS,
    _index_file_path,
    _parse_collection_paths,
    collection_add_args,
    detect_qmd,
    ensure_gitignored,
    qmd_executable,
)
from bindle.repo import get_repo_info

from tests.test_cli import _init_repo


def _fake_qmd(monkeypatch_target="/usr/bin/fake-qmd"):
    return mock.patch("bindle.qmd.qmd_executable", return_value=monkeypatch_target)


def _no_qmd():
    return mock.patch("bindle.qmd.qmd_executable", return_value=None)


# Exact shape verified this session against the real, installed `qmd` CLI
# (2.5.3 on PATH, 2.8.3 via a disposable local install) — `qmd init`
# followed by `qmd collection add . --name repo --mask "..."`.
_REAL_INDEX_YML_ONE_COLLECTION = """\
collections:
  repo:
    path: /repo-example/dev/bindle
    pattern: "{*.md,docs/**/*.md,plans/**/*.md}"
models:
  embed: hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf
  generate: hf:tobil/qmd-query-expansion-1.7B-gguf/qmd-query-expansion-1.7B-q4_k_m.gguf
  rerank: hf:ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF/qwen3-reranker-0.6b-q8_0.gguf
"""

# Exact shape of a freshly `qmd init`-ed index before any collection exists.
_REAL_INDEX_YML_EMPTY = """\
collections: {}
models:
  embed: hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf
  generate: hf:tobil/qmd-query-expansion-1.7B-gguf/qmd-query-expansion-1.7B-q4_k_m.gguf
  rerank: hf:ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF/qwen3-reranker-0.6b-q8_0.gguf
"""

_REAL_INDEX_YML_TWO_COLLECTIONS = """\
collections:
  notes:
    path: /repo-example/notes
    pattern: "**/*.md"
  repo:
    path: /repo-example/dev/bindle
    pattern: "{*.md,docs/**/*.md,plans/**/*.md}"
models:
  embed: hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf
"""


class TestParseCollectionPaths(unittest.TestCase):
    def test_single_collection(self):
        paths = _parse_collection_paths(_REAL_INDEX_YML_ONE_COLLECTION)
        self.assertEqual(paths, {"repo": "/repo-example/dev/bindle"})

    def test_empty_collections_inline_dict(self):
        self.assertEqual(_parse_collection_paths(_REAL_INDEX_YML_EMPTY), {})

    def test_multiple_collections(self):
        paths = _parse_collection_paths(_REAL_INDEX_YML_TWO_COLLECTIONS)
        self.assertEqual(
            paths,
            {
                "notes": "/repo-example/notes",
                "repo": "/repo-example/dev/bindle",
            },
        )

    def test_no_collections_key_at_all(self):
        self.assertEqual(_parse_collection_paths("models:\n  embed: foo\n"), {})

    def test_quoted_path_value_is_unquoted(self):
        text = 'collections:\n  repo:\n    path: "/has spaces/bindle"\n'
        self.assertEqual(_parse_collection_paths(text), {"repo": "/has spaces/bindle"})

    def test_stops_at_next_top_level_key_never_reads_into_models(self):
        # A pathological config where a *model* value happens to start with
        # "path:" must never be misread as a collection path.
        text = "collections:\n  repo:\n    path: /ok\nmodels:\n  path: /not-a-collection\n"
        self.assertEqual(_parse_collection_paths(text), {"repo": "/ok"})

    def test_malformed_text_never_raises(self):
        for garbage in ("", "not yaml at all {{{", "collections:\n", "collections:\n  \n"):
            self.assertEqual(_parse_collection_paths(garbage), {})


class TestQmdExecutable(unittest.TestCase):
    def test_returns_none_when_qmd_is_not_on_path(self):
        with mock.patch("shutil.which", return_value=None) as which:
            self.assertIsNone(qmd_executable())
        which.assert_called_once_with("qmd")

    def test_returns_the_resolved_path_when_qmd_is_on_path(self):
        with mock.patch("shutil.which", return_value="/usr/local/bin/qmd"):
            self.assertEqual(qmd_executable(), "/usr/local/bin/qmd")


class TestCollectionAddArgs(unittest.TestCase):
    def test_uses_the_fixed_collection_name_and_mask(self):
        args = collection_add_args("/some/worktree")
        self.assertEqual(
            args,
            (
                "collection",
                "add",
                "/some/worktree",
                "--name",
                COLLECTION_NAME,
                "--mask",
                COLLECTION_MASK,
            ),
        )

    def test_mask_scopes_to_root_docs_and_plans_only(self):
        # Regression guard for the deliberately narrow boundary (module
        # docstring "Collection identity"): this must never silently widen
        # to "every *.md in the tree" (which would sweep in
        # .projectmem/'s own generated Markdown).
        self.assertEqual(COLLECTION_MASK, "{*.md,docs/**/*.md,plans/**/*.md}")


class TestQmdInitArgs(unittest.TestCase):
    def test_is_just_init(self):
        self.assertEqual(QMD_INIT_ARGS, ("init",))


class TestDetectQmdRealFixtures(unittest.TestCase):
    # Mirrors test_projectmem.py's TestDetectProjectmemRealFixtures: real
    # Git fixtures on disk, `qmd_executable()` mocked so these never depend
    # on (or vary with) whether `qmd` is actually installed on the machine
    # running the tests.
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.info = get_repo_info(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_index_yml(self, text):
        qmd_dir = os.path.join(self.repo, ".qmd")
        os.makedirs(qmd_dir, exist_ok=True)
        with open(os.path.join(qmd_dir, "index.yml"), "w") as f:
            f.write(text)

    def test_unavailable_when_qmd_not_on_path(self):
        with _no_qmd():
            self.assertEqual(detect_qmd(self.info), "unavailable")

    def test_not_initialized_when_no_qmd_directory_exists(self):
        with _fake_qmd():
            self.assertEqual(detect_qmd(self.info), "not-initialized")

    def test_not_initialized_takes_priority_over_unavailable_check_order(self):
        # unavailable must be checked first regardless of on-disk state —
        # state genuinely cannot be determined without the executable.
        self._write_index_yml(_REAL_INDEX_YML_EMPTY)
        with _no_qmd():
            self.assertEqual(detect_qmd(self.info), "unavailable")

    def test_ready_when_our_collection_points_at_this_worktree(self):
        text = (
            "collections:\n"
            f"  {COLLECTION_NAME}:\n"
            f"    path: {self.repo}\n"
            f'    pattern: "{COLLECTION_MASK}"\n'
            "models:\n"
            "  embed: hf:example\n"
        )
        self._write_index_yml(text)
        with _fake_qmd():
            self.assertEqual(detect_qmd(self.info), "ready")

    def test_ready_resolves_symlinked_worktree_paths(self):
        # os.path.realpath comparison, not string equality — a worktree
        # reached through a symlinked path must still match.
        real_dir = os.path.join(self.tmp.name, "real-repo")
        os.rename(self.repo, real_dir)
        link = self.repo
        os.symlink(real_dir, link)
        info = get_repo_info(link)

        text = f"collections:\n  {COLLECTION_NAME}:\n    path: {real_dir}\n"
        os.makedirs(os.path.join(real_dir, ".qmd"), exist_ok=True)
        with open(os.path.join(real_dir, ".qmd", "index.yml"), "w") as f:
            f.write(text)

        with _fake_qmd():
            self.assertEqual(detect_qmd(info), "ready")

    def test_not_initialized_when_index_exists_without_our_collection(self):
        self._write_index_yml(_REAL_INDEX_YML_EMPTY)
        with _fake_qmd():
            self.assertEqual(detect_qmd(self.info), "not-initialized")

    def test_not_initialized_when_index_has_other_named_collections_only(self):
        text = "collections:\n  notes:\n    path: /somewhere/else\nmodels:\n  embed: x\n"
        self._write_index_yml(text)
        with _fake_qmd():
            self.assertEqual(detect_qmd(self.info), "not-initialized")

    def test_conflict_when_qmd_path_is_a_file(self):
        with open(os.path.join(self.repo, ".qmd"), "w") as f:
            f.write("not a directory")
        with _fake_qmd():
            self.assertEqual(detect_qmd(self.info), "conflict")

    def test_conflict_when_qmd_is_a_dangling_symlink(self):
        link = os.path.join(self.repo, ".qmd")
        os.symlink(os.path.join(self.repo, "nonexistent-target"), link)
        with _fake_qmd():
            self.assertEqual(detect_qmd(self.info), "conflict")
        self.assertTrue(os.path.islink(link))
        self.assertFalse(os.path.exists(link))

    def test_conflict_when_qmd_dir_exists_with_no_index_file(self):
        os.makedirs(os.path.join(self.repo, ".qmd"))
        with _fake_qmd():
            self.assertEqual(detect_qmd(self.info), "conflict")

    def test_conflict_when_our_collection_name_points_elsewhere(self):
        # Same collection name, different path: an unrelated, non-Bindle
        # collection that happens to be named "repo" — ownership is
        # ambiguous, must never be reused or overwritten.
        text = f"collections:\n  {COLLECTION_NAME}:\n    path: /somewhere/unrelated\n"
        self._write_index_yml(text)
        with _fake_qmd():
            self.assertEqual(detect_qmd(self.info), "conflict")

    def test_accepts_index_yaml_extension_too(self):
        qmd_dir = os.path.join(self.repo, ".qmd")
        os.makedirs(qmd_dir)
        with open(os.path.join(qmd_dir, "index.yaml"), "w") as f:
            f.write(f"collections:\n  {COLLECTION_NAME}:\n    path: {self.repo}\n")
        with _fake_qmd():
            self.assertEqual(detect_qmd(self.info), "ready")

    def test_detection_never_mutates_the_repository(self):
        text = f"collections:\n  {COLLECTION_NAME}:\n    path: {self.repo}\n"
        self._write_index_yml(text)
        qmd_dir = os.path.join(self.repo, ".qmd")
        before = sorted(os.listdir(qmd_dir))
        with _fake_qmd():
            detect_qmd(self.info)
            detect_qmd(self.info)
        after = sorted(os.listdir(qmd_dir))
        self.assertEqual(before, after)

    def test_scoped_to_worktree_root_not_a_parent_directory(self):
        parent = os.path.dirname(self.repo)
        parent_qmd_dir = os.path.join(parent, ".qmd")
        os.makedirs(parent_qmd_dir)
        with open(os.path.join(parent_qmd_dir, "index.yml"), "w") as f:
            f.write(f"collections:\n  {COLLECTION_NAME}:\n    path: {parent}\n")
        try:
            with _fake_qmd():
                self.assertEqual(detect_qmd(self.info), "not-initialized")
        finally:
            os.remove(os.path.join(parent_qmd_dir, "index.yml"))
            os.rmdir(parent_qmd_dir)


class TestIndexFilePath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_none_when_qmd_dir_absent(self):
        self.assertIsNone(_index_file_path(self.tmp.name))

    def test_prefers_yml_over_yaml_when_both_present(self):
        qmd_dir = os.path.join(self.tmp.name, ".qmd")
        os.makedirs(qmd_dir)
        with open(os.path.join(qmd_dir, "index.yml"), "w") as f:
            f.write("collections: {}\n")
        with open(os.path.join(qmd_dir, "index.yaml"), "w") as f:
            f.write("collections: {}\n")
        self.assertEqual(_index_file_path(self.tmp.name), os.path.join(qmd_dir, "index.yml"))


class TestEnsureGitignored(unittest.TestCase):
    # `ensure_gitignored` is the "Bindle should locally ignore .qmd/"
    # follow-up: a single, machine-local `info/exclude` line, added
    # idempotently, never touching the repository's own tracked
    # `.gitignore`. No `qmd` CLI dependency — this is pure Git mechanics.
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.info = get_repo_info(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def _exclude_path(self):
        return os.path.join(self.info.git_common_dir, "info", "exclude")

    def _run(self, args):
        subprocess.run(["git", "-C", self.repo, *args], check=True, capture_output=True, text=True)

    def test_adds_a_single_line_to_info_exclude(self):
        os.makedirs(os.path.join(self.repo, ".qmd"))
        ensure_gitignored(self.info)

        with open(self._exclude_path()) as f:
            lines = f.read().splitlines()
        self.assertIn(".qmd/", lines)
        self.assertEqual(lines.count(".qmd/"), 1)

    def test_never_writes_to_the_tracked_gitignore(self):
        gitignore = os.path.join(self.repo, ".gitignore")
        with open(gitignore, "w") as f:
            f.write("*.log\n")
        self._run(["add", ".gitignore"])
        self._run(["commit", "-m", "add gitignore"])

        os.makedirs(os.path.join(self.repo, ".qmd"))
        ensure_gitignored(self.info)

        with open(gitignore) as f:
            self.assertEqual(f.read(), "*.log\n")

    def test_idempotent_no_duplicate_line_on_repeated_calls(self):
        os.makedirs(os.path.join(self.repo, ".qmd"))
        ensure_gitignored(self.info)
        ensure_gitignored(self.info)
        ensure_gitignored(self.info)

        with open(self._exclude_path()) as f:
            lines = f.read().splitlines()
        self.assertEqual(lines.count(".qmd/"), 1)

    def test_skips_when_qmd_dir_already_tracked(self):
        qmd_dir = os.path.join(self.repo, ".qmd")
        os.makedirs(qmd_dir)
        with open(os.path.join(qmd_dir, "index.yml"), "w") as f:
            f.write("collections: {}\n")
        self._run(["add", ".qmd"])
        self._run(["commit", "-m", "deliberately track .qmd"])

        ensure_gitignored(self.info)

        exclude_path = self._exclude_path()
        if os.path.isfile(exclude_path):
            with open(exclude_path) as f:
                self.assertNotIn(".qmd/", f.read().splitlines())

    def test_skips_when_already_ignored_by_the_repositorys_own_gitignore(self):
        gitignore = os.path.join(self.repo, ".gitignore")
        with open(gitignore, "w") as f:
            f.write(".qmd/\n")
        self._run(["add", ".gitignore"])
        self._run(["commit", "-m", "repo already ignores .qmd"])

        os.makedirs(os.path.join(self.repo, ".qmd"))
        ensure_gitignored(self.info)

        exclude_path = self._exclude_path()
        if os.path.isfile(exclude_path):
            with open(exclude_path) as f:
                self.assertNotIn(".qmd/", f.read().splitlines())

    def test_preserves_existing_exclude_content(self):
        exclude_path = self._exclude_path()
        os.makedirs(os.path.dirname(exclude_path), exist_ok=True)
        with open(exclude_path, "w") as f:
            f.write("*.tmp\nsome-other-tool/\n")

        os.makedirs(os.path.join(self.repo, ".qmd"))
        ensure_gitignored(self.info)

        with open(exclude_path) as f:
            lines = f.read().splitlines()
        self.assertEqual(lines, ["*.tmp", "some-other-tool/", ".qmd/"])

    def test_never_raises_on_filesystem_error(self):
        with mock.patch("bindle.qmd._qmd_dir_is_tracked", side_effect=OSError("boom")):
            ensure_gitignored(self.info)  # must not raise


if __name__ == "__main__":
    unittest.main()
