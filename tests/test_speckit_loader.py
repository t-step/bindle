import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle import speckit_loader, work_ledger


class SpeckitLoaderTestCase(unittest.TestCase):
    """Base fixture: a temp directory standing in for a repository's Git
    common-directory-resolved `repo_root`, with real `specs/NNN-slug/
    tasks.md` fixture files written to disk — `load_feature()` reads
    `tasks.md` from the filesystem, so this needs real files, not an
    in-memory stand-in (mirrors `tests/test_work_ledger.py`'s own
    `LedgerTestCase` fixture pattern, extended with a helper for writing a
    feature directory's `tasks.md`)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_root = self.tmp.name
        self.ledger = work_ledger.WorkLedger(self.repo_root)

    def tearDown(self):
        self.tmp.cleanup()

    def write_tasks_md(self, feature_dir: str, content: str) -> str:
        """Write `content` to `{repo_root}/{feature_dir}/tasks.md`, creating
        the feature directory if needed. Returns `feature_dir` unchanged,
        for convenient chaining into `load_feature()` calls."""
        full_dir = os.path.join(self.repo_root, feature_dir)
        os.makedirs(full_dir, exist_ok=True)
        with open(os.path.join(full_dir, "tasks.md"), "w", encoding="utf-8") as f:
            f.write(content)
        return feature_dir


_BASIC_TASKS_MD = """\
# Tasks: Example Feature

## Phase 1: Setup

- [ ] T001 Set up the project scaffolding.
- [ ] T002 [P] Add the configuration file. Depends on: T001.
- [ ] T003 [US1] Implement the main feature entry point. Depends on: T001, T002.
"""


class TestLoadFeatureBasic(SpeckitLoaderTestCase):
    """T006 (Acceptance Scenario 1.1): loading a fixture tasks.md (several
    task lines) creates one type='task' work item per line with the
    correct derived id/source_kind='speckit_task'/source_locator, each
    open."""

    def test_creates_one_open_task_per_line(self):
        feature_dir = self.write_tasks_md(
            "specs/001-example-feature", _BASIC_TASKS_MD
        )

        result = speckit_loader.load_feature(self.ledger, feature_dir)

        self.assertEqual(
            set(result.created),
            {
                "speckit:001-example-feature:T001",
                "speckit:001-example-feature:T002",
                "speckit:001-example-feature:T003",
            },
        )
        self.assertEqual(result.resynced, ())
        self.assertEqual(result.skipped, ())
        self.assertEqual(result.unresolved_dependencies, ())

        item = self.ledger.get_work_item("speckit:001-example-feature:T001")
        self.assertIsNotNone(item)
        self.assertEqual(item.type, "task")
        self.assertEqual(item.status, "open")
        self.assertEqual(item.source_kind, "speckit_task")
        self.assertEqual(
            item.source_locator, "specs/001-example-feature/tasks.md#T001"
        )
        self.assertEqual(item.title, "Set up the project scaffolding.")

    def test_dependency_edges_are_recorded(self):
        feature_dir = self.write_tasks_md(
            "specs/001-example-feature", _BASIC_TASKS_MD
        )
        speckit_loader.load_feature(self.ledger, feature_dir)

        self.assertTrue(
            self.ledger.is_blocked("speckit:001-example-feature:T002")
        )
        self.assertTrue(
            self.ledger.is_blocked("speckit:001-example-feature:T003")
        )
        self.assertFalse(
            self.ledger.is_blocked("speckit:001-example-feature:T001")
        )

    def test_source_promoted_by_is_recorded(self):
        feature_dir = self.write_tasks_md(
            "specs/001-example-feature", _BASIC_TASKS_MD
        )
        speckit_loader.load_feature(
            self.ledger, feature_dir, source_promoted_by="maintainer-1"
        )
        item = self.ledger.get_work_item("speckit:001-example-feature:T001")
        self.assertEqual(item.source_promoted_by, "maintainer-1")


class TestLoadFeatureCrossFeatureCollision(SpeckitLoaderTestCase):
    """T007 (Acceptance Scenario 1.2, SC-004): two fixture feature
    directories that each declare a "T001" load as two distinct,
    independently identifiable work items with no collision."""

    def test_same_task_id_in_two_features_does_not_collide(self):
        feature_a = self.write_tasks_md(
            "specs/001-feature-a",
            "- [ ] T001 Do the first feature's own thing.\n",
        )
        feature_b = self.write_tasks_md(
            "specs/002-feature-b",
            "- [ ] T001 Do the second feature's own, different thing.\n",
        )

        result_a = speckit_loader.load_feature(self.ledger, feature_a)
        result_b = speckit_loader.load_feature(self.ledger, feature_b)

        self.assertEqual(result_a.created, ("speckit:001-feature-a:T001",))
        self.assertEqual(result_b.created, ("speckit:002-feature-b:T001",))

        item_a = self.ledger.get_work_item("speckit:001-feature-a:T001")
        item_b = self.ledger.get_work_item("speckit:002-feature-b:T001")
        self.assertIsNotNone(item_a)
        self.assertIsNotNone(item_b)
        self.assertNotEqual(item_a.id, item_b.id)
        self.assertEqual(
            item_a.source_locator, "specs/001-feature-a/tasks.md#T001"
        )
        self.assertEqual(
            item_b.source_locator, "specs/002-feature-b/tasks.md#T001"
        )


class TestLoadFeatureIdempotentReload(SpeckitLoaderTestCase):
    """T008 (Acceptance Scenario 1.3, SC-002): reloading an unchanged
    fixture a second time creates zero new work items and leaves every
    existing row byte-for-byte unchanged."""

    def test_reload_with_no_source_changes_is_a_true_noop(self):
        feature_dir = self.write_tasks_md(
            "specs/001-example-feature", _BASIC_TASKS_MD
        )
        speckit_loader.load_feature(self.ledger, feature_dir)

        before = {
            item.id: item
            for item in self.ledger.list_work_items()
        }

        result = speckit_loader.load_feature(self.ledger, feature_dir)

        self.assertEqual(result.created, ())
        self.assertEqual(result.resynced, ())

        after = {
            item.id: item
            for item in self.ledger.list_work_items()
        }
        self.assertEqual(before, after)


class TestLoadFeaturePreservesRuntimeState(SpeckitLoaderTestCase):
    """T009 (Acceptance Scenario 1.4, FR-006, SC-003): mark one previously
    loaded task done and claim a second, then reload the same feature
    directory; confirm both tasks' status/claim are completely
    unaffected."""

    def test_reload_never_disturbs_status_or_claim(self):
        feature_dir = self.write_tasks_md(
            "specs/001-example-feature", _BASIC_TASKS_MD
        )
        speckit_loader.load_feature(self.ledger, feature_dir)

        done_id = "speckit:001-example-feature:T001"
        claimed_id = "speckit:001-example-feature:T002"
        self.assertTrue(self.ledger.mark_done(done_id))
        self.assertTrue(self.ledger.claim(claimed_id, "worker-1"))

        speckit_loader.load_feature(self.ledger, feature_dir)

        self.assertEqual(self.ledger.get_work_item(done_id).status, "done")
        self.assertTrue(self.ledger.is_claimed(claimed_id))


class TestLoadFeatureDependencyOrderIndependence(SpeckitLoaderTestCase):
    """T010 (Acceptance Scenario 1.5, FR-009): a fixture whose dependent
    task line appears *before* the task line it depends on in file order
    still resolves the blocked_by edge correctly."""

    def test_forward_reference_dependency_resolves(self):
        # T001 depends on T002, but T002's own line appears *after* T001's
        # in the file.
        content = (
            "- [ ] T001 First task, depends on a later line. Depends on: T002.\n"
            "- [ ] T002 Second task, appears later in the file.\n"
        )
        feature_dir = self.write_tasks_md("specs/001-order", content)

        result = speckit_loader.load_feature(self.ledger, feature_dir)

        self.assertEqual(result.unresolved_dependencies, ())
        self.assertTrue(self.ledger.is_blocked("speckit:001-order:T001"))
        self.assertFalse(self.ledger.is_blocked("speckit:001-order:T002"))


class TestLoadFeatureDeclarativeResyncAndAdditiveDependencies(
    SpeckitLoaderTestCase
):
    """T011 (Acceptance Scenario 1.6, FR-007, FR-008): editing a fixture's
    task title/description text and adding a new Depends on: reference to
    an already-loaded task between two loads is reflected on reload; a
    previously recorded dependency is never removed even if a later edit
    stops declaring it."""

    def test_title_and_description_are_resynced_on_reload(self):
        feature_dir = self.write_tasks_md(
            "specs/001-example-feature",
            "- [ ] T001 Original title text.\n",
        )
        speckit_loader.load_feature(self.ledger, feature_dir)

        self.write_tasks_md(
            "specs/001-example-feature",
            "- [ ] T001 Updated title text.\n",
        )
        result = speckit_loader.load_feature(self.ledger, feature_dir)

        self.assertEqual(result.created, ())
        self.assertEqual(result.resynced, ("speckit:001-example-feature:T001",))
        item = self.ledger.get_work_item("speckit:001-example-feature:T001")
        self.assertEqual(item.title, "Updated title text.")

    def test_newly_declared_dependency_is_added_on_reload(self):
        feature_dir = self.write_tasks_md(
            "specs/001-example-feature",
            "- [ ] T001 First task.\n"
            "- [ ] T002 Second task, no dependency yet.\n",
        )
        speckit_loader.load_feature(self.ledger, feature_dir)
        self.assertFalse(self.ledger.is_blocked("speckit:001-example-feature:T002"))

        self.write_tasks_md(
            "specs/001-example-feature",
            "- [ ] T001 First task.\n"
            "- [ ] T002 Second task, now depends on the first. Depends on: T001.\n",
        )
        speckit_loader.load_feature(self.ledger, feature_dir)

        self.assertTrue(self.ledger.is_blocked("speckit:001-example-feature:T002"))

    def test_previously_recorded_dependency_is_never_removed(self):
        feature_dir = self.write_tasks_md(
            "specs/001-example-feature",
            "- [ ] T001 First task.\n"
            "- [ ] T002 Second task, depends on the first. Depends on: T001.\n",
        )
        speckit_loader.load_feature(self.ledger, feature_dir)
        self.assertTrue(self.ledger.is_blocked("speckit:001-example-feature:T002"))

        # The next revision of tasks.md no longer declares the dependency.
        self.write_tasks_md(
            "specs/001-example-feature",
            "- [ ] T001 First task.\n"
            "- [ ] T002 Second task, dependency text removed from the file.\n",
        )
        speckit_loader.load_feature(self.ledger, feature_dir)

        # The previously recorded edge is still there — reload never removes it.
        self.assertTrue(self.ledger.is_blocked("speckit:001-example-feature:T002"))


class TestLoadFeatureUnparseableLineAndMissingFile(SpeckitLoaderTestCase):
    """T012 (Acceptance Scenario 1.7, FR-011; Edge Cases, FR-012): a
    fixture containing one line that looks like an attempted task line
    but doesn't fully match the parser's shape is reported as skipped
    while every other well-formed line still loads; a feature directory
    with a missing or empty tasks.md is reported clearly rather than
    silently producing zero work items."""

    def test_unparseable_line_is_skipped_others_still_load(self):
        content = (
            "- [ ] T001 A well-formed task line.\n"
            "- [ ] not-a-valid-task-id in this line at all\n"
            "- [ ] T002 Another well-formed task line.\n"
        )
        feature_dir = self.write_tasks_md("specs/001-example-feature", content)

        result = speckit_loader.load_feature(self.ledger, feature_dir)

        self.assertEqual(
            set(result.created),
            {
                "speckit:001-example-feature:T001",
                "speckit:001-example-feature:T002",
            },
        )
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(result.skipped[0].line_number, 2)
        self.assertIn("task line shape", result.skipped[0].reason)

    def test_checkbox_state_is_never_read_or_required(self):
        content = (
            "- [x] T001 An already-checked task line.\n"
            "- [ ] T002 An unchecked task line.\n"
        )
        feature_dir = self.write_tasks_md("specs/001-example-feature", content)

        result = speckit_loader.load_feature(self.ledger, feature_dir)

        self.assertEqual(
            set(result.created),
            {
                "speckit:001-example-feature:T001",
                "speckit:001-example-feature:T002",
            },
        )
        # Both loaded 'open' regardless of their checkbox marker.
        self.assertEqual(
            self.ledger.get_work_item("speckit:001-example-feature:T001").status,
            "open",
        )

    def test_missing_tasks_file_raises_clear_error(self):
        os.makedirs(
            os.path.join(self.repo_root, "specs/001-empty-feature"), exist_ok=True
        )
        with self.assertRaises(speckit_loader.TasksFileError):
            speckit_loader.load_feature(self.ledger, "specs/001-empty-feature")

    def test_empty_tasks_file_raises_clear_error(self):
        feature_dir = self.write_tasks_md("specs/001-empty-feature", "")
        with self.assertRaises(speckit_loader.TasksFileError):
            speckit_loader.load_feature(self.ledger, feature_dir)

    def test_tasks_file_with_zero_parseable_lines_raises_clear_error(self):
        feature_dir = self.write_tasks_md(
            "specs/001-no-tasks",
            "# Tasks: No Tasks\n\nJust prose, no task lines here.\n",
        )
        with self.assertRaises(speckit_loader.TasksFileError):
            speckit_loader.load_feature(self.ledger, feature_dir)


class TestLoadFeatureUnresolvedDependency(SpeckitLoaderTestCase):
    """spec.md Edge Cases: a task line names a dependency on a Spec Kit
    task id that does not exist anywhere in the same tasks.md — the
    loader reports this rather than silently creating a dangling
    reference or silently dropping the dependency (FR-010)."""

    def test_dependency_on_nonexistent_task_id_is_reported(self):
        feature_dir = self.write_tasks_md(
            "specs/001-example-feature",
            "- [ ] T001 A task depending on something absent. Depends on: T099.\n",
        )

        result = speckit_loader.load_feature(self.ledger, feature_dir)

        self.assertEqual(result.created, ("speckit:001-example-feature:T001",))
        self.assertEqual(len(result.unresolved_dependencies), 1)
        unresolved = result.unresolved_dependencies[0]
        self.assertEqual(unresolved.task_id, "T001")
        self.assertEqual(unresolved.depends_on, "T099")
        # No dangling edge is ever written for the unresolved reference.
        self.assertFalse(self.ledger.is_blocked("speckit:001-example-feature:T001"))


if __name__ == "__main__":
    unittest.main()
