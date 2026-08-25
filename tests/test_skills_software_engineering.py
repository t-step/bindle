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
from bindle.skills import software_engineering as se

_HAS_REAL_CLAUDE = shutil.which("claude") is not None
_HAS_REAL_GIT = shutil.which("git") is not None


def _run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path):
    os.makedirs(path, exist_ok=True)
    _run(["git", "init", "--initial-branch=main"], path)
    _run(["git", "config", "user.email", "test@example.com"], path)
    _run(["git", "config", "user.name", "Test"], path)
    _run(["git", "commit", "--allow-empty", "-m", "init"], path)


def _fake_clone(skill_names):
    def clone(tmp_dir):
        subtree = os.path.join(tmp_dir, se._SKILLS_SUBTREE)
        os.makedirs(subtree, exist_ok=True)
        for name in skill_names:
            d = os.path.join(subtree, name)
            os.makedirs(d)
            with open(os.path.join(d, "SKILL.md"), "w") as f:
                f.write(f"---\nname: {name}\ndescription: test\n---\nbody\n")
        return True, ""

    return clone


class TestClaudeStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.info = get_repo_info(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_settings(self, doc):
        os.makedirs(os.path.join(self.repo, ".claude"), exist_ok=True)
        with open(os.path.join(self.repo, ".claude", "settings.json"), "w") as f:
            json.dump(doc, f)

    def test_not_installed_when_no_settings_file(self):
        self.assertEqual(se._claude_status(self.info), "not-installed")

    def test_not_installed_when_enabled_plugins_missing(self):
        self._write_settings({})
        self.assertEqual(se._claude_status(self.info), "not-installed")

    def test_not_installed_when_plugin_key_false(self):
        self._write_settings({"enabledPlugins": {se.PLUGIN_SPEC: False}})
        self.assertEqual(se._claude_status(self.info), "not-installed")

    def test_installed_when_plugin_key_true(self):
        self._write_settings({"enabledPlugins": {se.PLUGIN_SPEC: True}})
        self.assertEqual(se._claude_status(self.info), "installed")

    def test_not_installed_when_settings_file_is_malformed_json(self):
        os.makedirs(os.path.join(self.repo, ".claude"))
        with open(os.path.join(self.repo, ".claude", "settings.json"), "w") as f:
            f.write("not json")
        self.assertEqual(se._claude_status(self.info), "not-installed")


class TestClaudeAddRemoveMocked(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.info = get_repo_info(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_reports_unavailable_when_claude_missing(self):
        with mock.patch.object(se, "_claude_executable", return_value=None):
            ok, line = se._claude_add(self.info)
        self.assertTrue(ok)
        self.assertIn("unavailable", line)

    def test_add_registers_marketplace_only_when_not_already_registered(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[1:4] == ["plugin", "marketplace", "list"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with mock.patch.object(se, "_claude_executable", return_value="claude"), mock.patch(
            "subprocess.run", side_effect=fake_run
        ):
            ok, line = se._claude_add(self.info)

        self.assertTrue(ok)
        self.assertIn("installed", line)
        marketplace_add_calls = [c for c in calls if c[1:4] == ["plugin", "marketplace", "add"]]
        self.assertEqual(len(marketplace_add_calls), 1)

    def test_add_skips_marketplace_registration_when_already_registered(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[1:4] == ["plugin", "marketplace", "list"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=json.dumps([{"name": se.MARKETPLACE_ID}]), stderr=""
                )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with mock.patch.object(se, "_claude_executable", return_value="claude"), mock.patch(
            "subprocess.run", side_effect=fake_run
        ):
            se._claude_add(self.info)

        marketplace_add_calls = [c for c in calls if c[1:4] == ["plugin", "marketplace", "add"]]
        self.assertEqual(marketplace_add_calls, [])

    def test_remove_does_not_touch_marketplace_registration(self):
        os.makedirs(os.path.join(self.repo, ".claude"))
        with open(os.path.join(self.repo, ".claude", "settings.json"), "w") as f:
            json.dump({"enabledPlugins": {se.PLUGIN_SPEC: True}}, f)

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with mock.patch.object(se, "_claude_executable", return_value="claude"), mock.patch(
            "subprocess.run", side_effect=fake_run
        ):
            ok, line = se._claude_remove(self.info)

        self.assertTrue(ok)
        marketplace_calls = [c for c in calls if "marketplace" in c]
        self.assertEqual(marketplace_calls, [])

    def test_remove_is_a_clean_no_op_when_claude_missing_and_not_installed(self):
        with mock.patch.object(se, "_claude_executable", return_value=None):
            ok, line = se._claude_remove(self.info)
        self.assertTrue(ok)
        self.assertIn("unavailable", line)

    def test_remove_fails_and_preserves_config_when_claude_missing_but_settings_say_installed(self):
        os.makedirs(os.path.join(self.repo, ".claude"))
        with open(os.path.join(self.repo, ".claude", "settings.json"), "w") as f:
            json.dump({"enabledPlugins": {se.PLUGIN_SPEC: True}}, f)

        with mock.patch.object(se, "_claude_executable", return_value=None), mock.patch(
            "subprocess.run", side_effect=AssertionError("must not shell out")
        ):
            ok, line = se._claude_remove(self.info)

        self.assertFalse(ok)
        self.assertIn("unavailable", line)
        # Configuration is preserved, never hand-edited to force success.
        self.assertEqual(se._claude_status(self.info), "installed")


class TestDigestDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _make_dir(self, files):
        d = os.path.join(self.tmp.name, f"d{len(os.listdir(self.tmp.name))}")
        os.makedirs(d)
        for rel, content in files.items():
            full = os.path.join(d, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(content)
        return d

    def test_identical_content_gives_identical_digest(self):
        d1 = self._make_dir({"SKILL.md": "hello"})
        d2 = os.path.join(self.tmp.name, "copy")
        shutil.copytree(d1, d2)
        self.assertEqual(se._digest_dir(d1), se._digest_dir(d2))

    def test_content_edit_changes_digest(self):
        d = self._make_dir({"SKILL.md": "hello"})
        before = se._digest_dir(d)
        with open(os.path.join(d, "SKILL.md"), "w") as f:
            f.write("goodbye")
        after = se._digest_dir(d)
        self.assertNotEqual(before, after)

    def test_added_file_changes_digest(self):
        d = self._make_dir({"SKILL.md": "hello"})
        before = se._digest_dir(d)
        with open(os.path.join(d, "extra.txt"), "w") as f:
            f.write("x")
        after = se._digest_dir(d)
        self.assertNotEqual(before, after)

    def test_removed_file_changes_digest(self):
        d = self._make_dir({"SKILL.md": "hello", "extra.txt": "x"})
        before = se._digest_dir(d)
        os.unlink(os.path.join(d, "extra.txt"))
        after = se._digest_dir(d)
        self.assertNotEqual(before, after)


class TestCodexStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.info = get_repo_info(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def _materialize(self, name):
        path = os.path.join(self.repo, ".agents", "skills", name)
        os.makedirs(path)
        with open(os.path.join(path, "SKILL.md"), "w") as f:
            f.write(f"---\nname: {name}\ndescription: test\n---\nbody\n")
        return path, se._digest_dir(path)

    def test_not_installed_when_no_marker(self):
        self.assertEqual(se._codex_status(self.info), "not-installed")

    def test_not_installed_when_marker_has_no_skills(self):
        se._write_marker(self.info, {})
        self.assertEqual(se._codex_status(self.info), "not-installed")

    def test_installed_when_all_marked_skills_present_and_matching(self):
        _, digest_a = self._materialize("a")
        _, digest_b = self._materialize("b")
        se._write_marker(self.info, {"a": digest_a, "b": digest_b})
        self.assertEqual(se._codex_status(self.info), "installed")

    def test_partial_when_some_marked_skills_missing(self):
        _, digest_a = self._materialize("a")
        se._write_marker(self.info, {"a": digest_a, "b": "0" * 64})
        self.assertEqual(se._codex_status(self.info), "partial")

    def test_not_installed_when_marker_present_but_nothing_on_disk(self):
        se._write_marker(self.info, {"a": "0" * 64, "b": "0" * 64})
        self.assertEqual(se._codex_status(self.info), "not-installed")

    def test_conflict_when_marked_skill_content_was_modified(self):
        path, digest_a = self._materialize("a")
        se._write_marker(self.info, {"a": digest_a})
        with open(os.path.join(path, "SKILL.md"), "a") as f:
            f.write("tampered\n")
        self.assertEqual(se._codex_status(self.info), "conflict")

    def test_conflict_takes_priority_even_alongside_a_missing_skill(self):
        path, digest_a = self._materialize("a")
        with open(os.path.join(path, "SKILL.md"), "a") as f:
            f.write("tampered\n")
        se._write_marker(self.info, {"a": digest_a, "b": "0" * 64})
        self.assertEqual(se._codex_status(self.info), "conflict")


class TestCodexAddRemove(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.info = get_repo_info(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def _info_exclude_path(self):
        return os.path.join(self.info.git_common_dir, "info", "exclude")

    def test_add_materializes_discovered_skills_and_records_marker(self):
        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a", "b"])):
            ok, line = se._codex_add(self.info)

        self.assertTrue(ok)
        self.assertIn("installed", line)
        self.assertTrue(os.path.isfile(os.path.join(self.repo, ".agents", "skills", "a", "SKILL.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.repo, ".agents", "skills", "b", "SKILL.md")))

        marker = se._read_marker(self.info)
        self.assertEqual(sorted(marker["skills"]), ["a", "b"])
        self.assertEqual(len(marker["skills"]["a"]), 64)  # a real sha256 hex digest

        with open(self._info_exclude_path()) as f:
            exclude = f.read()
        self.assertIn(".agents/skills/a/", exclude)
        self.assertIn(".agents/skills/b/", exclude)
        self.assertIn(se._EXCLUDE_BLOCK_BEGIN, exclude)
        self.assertIn(se._EXCLUDE_BLOCK_END, exclude)

    def test_add_is_idempotent(self):
        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a"])):
            se._codex_add(self.info)
            ok, line = se._codex_add(self.info)

        self.assertTrue(ok)
        self.assertIn("already installed", line)

    def test_add_refuses_when_a_target_directory_already_exists_and_is_not_bindle_owned(self):
        foreign = os.path.join(self.repo, ".agents", "skills", "a")
        os.makedirs(foreign)
        with open(os.path.join(foreign, "SKILL.md"), "w") as f:
            f.write("not bindle's")

        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a", "b"])):
            ok, line = se._codex_add(self.info)

        self.assertFalse(ok)
        self.assertIn("conflict", line)
        with open(os.path.join(foreign, "SKILL.md")) as f:
            self.assertEqual(f.read(), "not bindle's")
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".agents", "skills", "b")))
        self.assertIsNone(se._read_marker(self.info))

    def test_add_refuses_when_status_is_conflict(self):
        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a"])):
            se._codex_add(self.info)
        with open(os.path.join(self.repo, ".agents", "skills", "a", "SKILL.md"), "a") as f:
            f.write("tampered\n")

        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a"])):
            ok, line = se._codex_add(self.info)

        self.assertFalse(ok)
        self.assertIn("conflict", line)

    def test_add_repairs_a_missing_owned_directory(self):
        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a", "b"])):
            se._codex_add(self.info)
        shutil.rmtree(os.path.join(self.repo, ".agents", "skills", "b"))
        self.assertEqual(se._codex_status(self.info), "partial")

        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a", "b"])):
            ok, line = se._codex_add(self.info)

        self.assertTrue(ok, line)
        self.assertEqual(se._codex_status(self.info), "installed")

    def test_remove_detaches_only_owned_directories_leaving_unrelated_ones_alone(self):
        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a", "b"])):
            se._codex_add(self.info)

        # A same-parent-directory skill from another kit (e.g. spec-kit's
        # own speckit-* skills) must survive removal untouched.
        unrelated = os.path.join(self.repo, ".agents", "skills", "speckit-plan")
        os.makedirs(unrelated)
        with open(os.path.join(unrelated, "SKILL.md"), "w") as f:
            f.write("unrelated")

        ok, line = se._codex_remove(self.info)

        self.assertTrue(ok)
        self.assertIn("removed", line)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".agents", "skills", "a")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".agents", "skills", "b")))
        self.assertTrue(os.path.isfile(os.path.join(unrelated, "SKILL.md")))
        self.assertIsNone(se._read_marker(self.info))

    def test_remove_cleans_up_only_the_exclude_block_it_owns(self):
        os.makedirs(os.path.dirname(self._info_exclude_path()), exist_ok=True)
        with open(self._info_exclude_path(), "w") as f:
            f.write("some-unrelated-pattern/\n")

        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a"])):
            se._codex_add(self.info)

        with open(self._info_exclude_path()) as f:
            content = f.read()
        self.assertIn(".agents/skills/a/", content)
        self.assertIn("some-unrelated-pattern/", content)
        self.assertIn(se._EXCLUDE_BLOCK_BEGIN, content)

        se._codex_remove(self.info)

        with open(self._info_exclude_path()) as f:
            content = f.read()
        self.assertNotIn(".agents/skills/a/", content)
        self.assertIn("some-unrelated-pattern/", content)
        # Nothing left requires the managed block — it's fully removed,
        # not left behind empty.
        self.assertNotIn(se._EXCLUDE_BLOCK_BEGIN, content)

    def test_remove_clears_a_bindle_only_info_exclude_it_created_rather_than_leaving_it_stale(self):
        # Regression: info/exclude did not exist before Bindle. Once
        # Bindle creates it containing only its own managed block, and
        # the last worktree removes the kit, `before`/`after` (everything
        # outside the block) are both empty — reconciliation must still
        # rewrite the file rather than return early and leave the stale
        # Bindle-owned block behind.
        #
        # `git init` itself populates info/exclude with boilerplate
        # comments (verified against the installed git this session), so
        # the "did not exist before Bindle" precondition is reproduced
        # explicitly here rather than assumed from a fresh checkout.
        if os.path.exists(self._info_exclude_path()):
            os.unlink(self._info_exclude_path())
        self.assertFalse(os.path.exists(self._info_exclude_path()))

        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a"])):
            se._codex_add(self.info)

        with open(self._info_exclude_path()) as f:
            content = f.read()
        self.assertIn(se._EXCLUDE_BLOCK_BEGIN, content)
        self.assertIn(".agents/skills/a/", content)
        self.assertIn(se._EXCLUDE_BLOCK_END, content)

        se._codex_remove(self.info)

        # The file is never unlinked (it's Git infrastructure, not
        # Bindle's to remove) — but no Bindle-owned content may remain.
        self.assertTrue(os.path.exists(self._info_exclude_path()))
        with open(self._info_exclude_path()) as f:
            content = f.read()
        self.assertNotIn(se._EXCLUDE_BLOCK_BEGIN, content)
        self.assertNotIn(se._EXCLUDE_BLOCK_END, content)
        self.assertNotIn(".agents/skills/a/", content)

    def test_add_never_duplicates_a_pre_existing_identical_ignore_entry(self):
        os.makedirs(os.path.dirname(self._info_exclude_path()), exist_ok=True)
        with open(self._info_exclude_path(), "w") as f:
            f.write(".agents/skills/a/\n")

        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a"])):
            se._codex_add(self.info)

        with open(self._info_exclude_path()) as f:
            content = f.read()
        self.assertEqual(content.count(".agents/skills/a/"), 1)
        # The pre-existing, foreign line is never absorbed into Bindle's
        # own managed block.
        self.assertNotIn(se._EXCLUDE_BLOCK_BEGIN, content)

    def test_remove_is_idempotent(self):
        ok, line = se._codex_remove(self.info)
        self.assertTrue(ok)
        self.assertIn("already not installed", line)


class TestCodexModifiedContentSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.info = get_repo_info(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_modified_skill_survives_remove_and_is_reported_as_conflict(self):
        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a", "b"])):
            se._codex_add(self.info)

        modified_path = os.path.join(self.repo, ".agents", "skills", "a", "SKILL.md")
        with open(modified_path, "a") as f:
            f.write("user edit\n")

        ok, line = se._codex_remove(self.info)

        self.assertFalse(ok)
        self.assertIn("conflict", line)

        # Modified content survives byte-for-byte.
        with open(modified_path) as f:
            self.assertIn("user edit", f.read())

        # The unmodified owned directory ("b") was still removed.
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".agents", "skills", "b")))

        # Ownership evidence for "a" is retained so a future remove can
        # still act on it safely; "b" is gone from the marker.
        marker = se._read_marker(self.info)
        self.assertIn("a", marker["skills"])
        self.assertNotIn("b", marker["skills"])
        self.assertEqual(se._codex_status(self.info), "conflict")

    def test_retry_after_resolving_conflict_by_hand_succeeds(self):
        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a"])):
            se._codex_add(self.info)

        path = os.path.join(self.repo, ".agents", "skills", "a")
        with open(os.path.join(path, "SKILL.md"), "a") as f:
            f.write("user edit\n")

        ok, _ = se._codex_remove(self.info)
        self.assertFalse(ok)

        # User resolves the conflict by hand.
        shutil.rmtree(path)

        ok2, line2 = se._codex_remove(self.info)
        self.assertTrue(ok2)
        self.assertIn("removed", line2)
        self.assertIsNone(se._read_marker(self.info))


class TestCodexMultiWorktree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.info = get_repo_info(self.repo)

        self.wt_path = os.path.join(self.tmp.name, "wt")
        _run(["git", "worktree", "add", "-b", "wt-branch", self.wt_path], self.repo)
        self.wt_info = get_repo_info(self.wt_path)

    def tearDown(self):
        self.tmp.cleanup()

    def _info_exclude_path(self):
        return os.path.join(self.info.git_common_dir, "info", "exclude")

    def test_markers_are_worktree_scoped_not_shared(self):
        self.assertEqual(self.info.git_common_dir, self.wt_info.git_common_dir)
        self.assertNotEqual(self.info.git_dir, self.wt_info.git_dir)
        self.assertNotEqual(se._marker_path(self.info), se._marker_path(self.wt_info))

    def test_two_worktrees_add_independently_with_independent_ownership(self):
        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a", "b"])):
            main_ok, _ = se._codex_add(self.info)
            wt_ok, _ = se._codex_add(self.wt_info)

        self.assertTrue(main_ok)
        self.assertTrue(wt_ok)
        self.assertEqual(se._codex_status(self.info), "installed")
        self.assertEqual(se._codex_status(self.wt_info), "installed")
        self.assertIsNotNone(se._read_marker(self.info))
        self.assertIsNotNone(se._read_marker(self.wt_info))

        with open(self._info_exclude_path()) as f:
            content = f.read()
        self.assertIn(".agents/skills/a/", content)
        self.assertIn(".agents/skills/b/", content)

    def test_removing_one_worktrees_kit_never_touches_the_others_files_or_ownership(self):
        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a"])):
            se._codex_add(self.info)
            se._codex_add(self.wt_info)

        main_skill_path = os.path.join(self.repo, ".agents", "skills", "a", "SKILL.md")
        self.assertTrue(os.path.isfile(main_skill_path))

        remove_ok, _ = se._codex_remove(self.wt_info)

        self.assertTrue(remove_ok)
        self.assertEqual(se._codex_status(self.wt_info), "not-installed")
        self.assertFalse(os.path.exists(os.path.join(self.wt_path, ".agents", "skills", "a")))

        # Main worktree: completely untouched, ownership intact.
        self.assertEqual(se._codex_status(self.info), "installed")
        self.assertTrue(os.path.isfile(main_skill_path))
        self.assertIsNotNone(se._read_marker(self.info))

    def test_shared_ignore_bookkeeping_survives_until_the_last_worktree_removes_it(self):
        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a"])):
            se._codex_add(self.info)
            se._codex_add(self.wt_info)

        se._codex_remove(self.wt_info)

        # Main worktree still requires the ignore entry — must survive.
        with open(self._info_exclude_path()) as f:
            content = f.read()
        self.assertIn(".agents/skills/a/", content)
        self.assertIn(se._EXCLUDE_BLOCK_BEGIN, content)

        main_remove_ok, _ = se._codex_remove(self.info)
        self.assertTrue(main_remove_ok)
        self.assertEqual(se._codex_status(self.info), "not-installed")

        # Now nobody requires it — the managed block is gone entirely.
        with open(self._info_exclude_path()) as f:
            content = f.read()
        self.assertNotIn(se._EXCLUDE_BLOCK_BEGIN, content)
        self.assertNotIn(".agents/skills/a/", content)

    def test_main_can_safely_remove_after_linked_worktree_already_removed(self):
        with mock.patch.object(se, "_clone_skills_source", side_effect=_fake_clone(["a", "b"])):
            se._codex_add(self.info)
            se._codex_add(self.wt_info)

        se._codex_remove(self.wt_info)

        main_remove_ok, main_line = se._codex_remove(self.info)
        self.assertTrue(main_remove_ok, main_line)
        self.assertEqual(se._codex_status(self.info), "not-installed")


@unittest.skipUnless(_HAS_REAL_CLAUDE, "claude CLI not installed")
@unittest.skipUnless(_HAS_REAL_GIT, "git not installed")
class TestRealClaudeAndCodexIntegration(unittest.TestCase):
    """Exercises the real `claude` CLI and a real clone of t-step/skills,
    fully isolated from the user's live Claude configuration via
    CLAUDE_CONFIG_DIR (AGENTS.md's Runtime Isolation rule)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        _init_repo(self.repo)
        self.info = get_repo_info(self.repo)

        self.config_dir = os.path.join(self.tmp.name, "claude-config")
        os.makedirs(self.config_dir)
        self._env_patch = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.config_dir})
        self._env_patch.start()

        probe = subprocess.run(
            ["git", "ls-remote", se._SKILLS_GIT_URL],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if probe.returncode != 0:
            self._env_patch.stop()
            self.skipTest(f"t-step/skills not reachable: {probe.stderr.strip()}")

    def tearDown(self):
        self._env_patch.stop()
        self.tmp.cleanup()

    def test_add_then_remove_round_trip(self):
        outcome = se.add(self.info)
        self.assertTrue(outcome.ok, outcome.lines)
        self.assertEqual(se.status(self.info), se.KitStatus(claude="installed", codex="installed"))

        remove_outcome = se.remove(self.info)
        self.assertTrue(remove_outcome.ok, remove_outcome.lines)
        self.assertEqual(se.status(self.info), se.KitStatus(claude="not-installed", codex="not-installed"))


if __name__ == "__main__":
    unittest.main()
