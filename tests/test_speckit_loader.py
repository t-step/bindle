import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle import speckit_loader, work_ledger


class SpeckitLoaderTestCase(unittest.TestCase):
    """Temp `repo_root` with real tasks.md files: load_feature() reads disk."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_root = self.tmp.name
        self.ledger = work_ledger.WorkLedger(self.repo_root)

    def tearDown(self):
        self.tmp.cleanup()

    def write_tasks_md(self, feature_dir: str, content: str) -> str:
        """Write `content` to the feature's tasks.md; return `feature_dir`."""
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
    """T006 (Acceptance Scenario 1.1): one open task item per task line."""

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
    """T007 (Scenario 1.2, SC-004): equal ids in two features stay distinct."""

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
    """T008 (Scenario 1.3, SC-002): an unchanged reload changes nothing."""

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
    """T009 (Scenario 1.4, FR-006, SC-003): reload keeps status and claims."""

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
    """T010 (Scenario 1.5, FR-009): a forward dependency still resolves."""

    def test_forward_reference_dependency_resolves(self):
        # T001 depends on T002, whose line appears after T001's.
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
    """T011 (Scenario 1.6, FR-007, FR-008): edits resync; edges are kept."""

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

        # The next revision no longer declares the dependency.
        self.write_tasks_md(
            "specs/001-example-feature",
            "- [ ] T001 First task.\n"
            "- [ ] T002 Second task, dependency text removed from the file.\n",
        )
        speckit_loader.load_feature(self.ledger, feature_dir)

        # The previously recorded edge is still there — reload never removes it.
        self.assertTrue(self.ledger.is_blocked("speckit:001-example-feature:T002"))


class TestLoadFeatureUnparseableLineAndMissingFile(SpeckitLoaderTestCase):
    """T012 (Scenario 1.7, FR-011, FR-012): skips; missing or empty file."""

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


class TestLoadFeatureSourceIdentityConflict(SpeckitLoaderTestCase):
    """A foreign-provenance id collision raises SourceIdentityConflictError."""

    def test_collision_with_unrelated_adhoc_item_raises_and_does_not_mutate(
        self,
    ):
        feature_dir = self.write_tasks_md(
            "specs/001-example-feature",
            "- [ ] T001 Set up the project scaffolding.\n",
        )
        colliding_id = "speckit:001-example-feature:T001"
        self.ledger.create_work_item(
            id=colliding_id,
            title="An unrelated, manually created adhoc item.",
            source_kind="adhoc",
            source_locator="manually created, not from Spec Kit",
        )
        # An unrelated item: the conflict must not mutate other rows.
        self.ledger.create_work_item(
            id="unrelated-item",
            title="Some other work item entirely.",
            source_kind="adhoc",
            source_locator="elsewhere",
        )

        before_colliding = self.ledger.get_work_item(colliding_id)
        before_unrelated = self.ledger.get_work_item("unrelated-item")

        with self.assertRaises(speckit_loader.SourceIdentityConflictError):
            speckit_loader.load_feature(self.ledger, feature_dir)

        self.assertEqual(
            self.ledger.get_work_item(colliding_id), before_colliding
        )
        self.assertEqual(
            self.ledger.get_work_item("unrelated-item"), before_unrelated
        )

    def test_collision_with_speckit_task_from_different_locator_raises(self):
        feature_dir = self.write_tasks_md(
            "specs/001-example-feature",
            "- [ ] T001 Set up the project scaffolding.\n",
        )
        colliding_id = "speckit:001-example-feature:T001"
        # Same source_kind but another feature/task's source_locator.
        self.ledger.create_work_item(
            id=colliding_id,
            title="A different speckit task with the same derived id.",
            source_kind="speckit_task",
            source_locator="specs/999-other-feature/tasks.md#T001",
        )
        before = self.ledger.get_work_item(colliding_id)

        with self.assertRaises(speckit_loader.SourceIdentityConflictError):
            speckit_loader.load_feature(self.ledger, feature_dir)

        self.assertEqual(self.ledger.get_work_item(colliding_id), before)


class TestLoadFeatureDuplicateTaskId(SpeckitLoaderTestCase):
    """A repeated task id raises TasksFileError and loads nothing."""

    def test_duplicate_task_id_raises_with_line_numbers_and_creates_nothing(
        self,
    ):
        content = (
            "- [ ] T001 First occurrence of this task id.\n"
            "- [ ] T002 An unrelated, unambiguous task.\n"
            "- [ ] T001 Second, conflicting occurrence of the same id.\n"
        )
        feature_dir = self.write_tasks_md("specs/001-example-feature", content)

        with self.assertRaises(speckit_loader.TasksFileError) as ctx:
            speckit_loader.load_feature(self.ledger, feature_dir)

        message = str(ctx.exception)
        self.assertIn("T001", message)
        self.assertIn("line 1", message)
        self.assertIn("line 3", message)

        # Parsing stopped the load before pass 1, so T002 didn't load either.
        self.assertIsNone(
            self.ledger.get_work_item("speckit:001-example-feature:T001")
        )
        self.assertIsNone(
            self.ledger.get_work_item("speckit:001-example-feature:T002")
        )


class TestLoadFeatureUnresolvedDependency(SpeckitLoaderTestCase):
    """spec.md Edge Cases (FR-010): an unknown dependency id is reported."""

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
