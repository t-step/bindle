import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle import symphony_projection, work_ledger


class LedgerTestCase(unittest.TestCase):
    """Mirrors tests/test_work_ledger.py's own `LedgerTestCase` fixture: a
    temp directory standing in for a repository's Git common-directory-
    resolved `repo_root` (`RepoInfo.repo_root`) — this module never itself
    shells out to Git, so no real repository is needed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_root = self.tmp.name
        self.ledger = work_ledger.WorkLedger(self.repo_root)

    def tearDown(self):
        self.tmp.cleanup()

    def _create_task(self, id, **kwargs):
        kwargs.setdefault("title", f"Title {id}")
        kwargs.setdefault("source_kind", "adhoc")
        kwargs.setdefault("source_locator", f"plans/active/example.md#{id}")
        self.ledger.create_work_item(id=id, **kwargs)

    def _create_milestone(self, id):
        self.ledger.create_work_item(
            id=id,
            title=f"Milestone {id}",
            source_kind="adhoc",
            source_locator=f"plans/active/example.md#{id}",
            type="milestone",
        )


class TestPublish(LedgerTestCase):
    """specs/003-symphony-task-integration T016 (Acceptance Scenario 2.6,
    FR-018): `publish()` writes a `task_projection` table matching
    contracts/symphony-projection-v1.md's schema exactly, readable via a
    real `mode=ro` URI connection, with `PRAGMA user_version` reporting
    `1` from the export file alone — no internal ledger table need ever
    be opened by an external reader."""

    def test_publish_returns_the_documented_path(self):
        self._create_task("T-1")
        path = symphony_projection.publish(self.ledger)
        self.assertEqual(
            path,
            os.path.join(self.repo_root, ".bindle-work", "symphony-projection.sqlite3"),
        )
        self.assertTrue(os.path.isfile(path))

    def test_published_file_reports_user_version_1_via_readonly_connection(self):
        self._create_task("T-1")
        path = symphony_projection.publish(self.ledger)

        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(version, 1)

    def test_published_schema_and_row_values_match_the_contract(self):
        self._create_task("T-open")
        self._create_task("T-blocker")
        self._create_task("T-blocked", blocked_by=["T-blocker"])
        self._create_task("T-done")
        self.assertTrue(self.ledger.mark_done("T-done"))
        self._create_milestone("M-1")

        path = symphony_projection.publish(self.ledger)

        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            columns = [
                row[1]
                for row in conn.execute("PRAGMA table_info(task_projection)").fetchall()
            ]
            self.assertEqual(
                columns,
                [
                    "id",
                    "identifier",
                    "title",
                    "description",
                    "status",
                    "dispatchable",
                    "created_at",
                ],
            )

            rows = {
                row[0]: row
                for row in conn.execute(
                    "SELECT id, identifier, title, description, status, "
                    "dispatchable, created_at FROM task_projection"
                ).fetchall()
            }
        finally:
            conn.close()

        # Task-only, exactly (FR-014): the milestone never appears.
        self.assertNotIn("M-1", rows)
        self.assertEqual(
            set(rows), {"T-open", "T-blocker", "T-blocked", "T-done"}
        )

        self.assertEqual(rows["T-open"][4], "open")
        self.assertEqual(rows["T-open"][5], 1)
        self.assertEqual(rows["T-open"][1], "T-open")  # no ':' to replace
        self.assertEqual(rows["T-open"][2], "Title T-open")
        self.assertIsNotNone(rows["T-open"][6])  # created_at preserved

        # T-blocker is itself open/unclaimed/unblocked, so it remains
        # dispatchable even though it blocks another task.
        self.assertEqual(rows["T-blocker"][4], "open")
        self.assertEqual(rows["T-blocker"][5], 1)

        self.assertEqual(rows["T-blocked"][4], "open")
        self.assertEqual(rows["T-blocked"][5], 0)

        self.assertEqual(rows["T-done"][4], "done")
        self.assertEqual(rows["T-done"][5], 0)

    def test_dispatchable_is_stored_as_sqlite_integer_zero_or_one(self):
        self._create_task("T-open")
        self._create_task("T-blocker")
        self._create_task("T-blocked", blocked_by=["T-blocker"])
        path = symphony_projection.publish(self.ledger)

        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            values = {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT id, dispatchable FROM task_projection"
                ).fetchall()
            }
        finally:
            conn.close()
        self.assertEqual(values["T-open"], 1)
        self.assertEqual(values["T-blocked"], 0)
        for value in values.values():
            self.assertIn(value, (0, 1))

    def test_created_at_is_preserved_verbatim_in_the_published_row(self):
        self._create_task("T-1")
        canonical_created_at = self.ledger.get_work_item("T-1").created_at
        path = symphony_projection.publish(self.ledger)

        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            published_created_at = conn.execute(
                "SELECT created_at FROM task_projection WHERE id = ?", ("T-1",)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertIsNotNone(canonical_created_at)
        self.assertEqual(published_created_at, canonical_created_at)

    def test_identifier_replaces_colon_for_speckit_style_ids(self):
        self._create_task(
            "speckit:003-symphony-task-integration:T003",
            source_kind="speckit_task",
            source_locator="specs/003-symphony-task-integration/tasks.md#T003",
        )
        path = symphony_projection.publish(self.ledger)

        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            identifier = conn.execute(
                "SELECT identifier FROM task_projection WHERE id = ?",
                ("speckit:003-symphony-task-integration:T003",),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(identifier, "speckit-003-symphony-task-integration-T003")


class TestPublishDeterminism(LedgerTestCase):
    """specs/003-symphony-task-integration T017 (Acceptance Scenario 2.5,
    SC-006): two `publish()` calls against an unchanged ledger produce an
    equal `task_projection` result both times."""

    def test_two_publishes_from_unchanged_ledger_produce_equal_tables(self):
        self._create_task("T-a")
        self._create_task("T-b", blocked_by=["T-a"])
        self.assertTrue(self.ledger.mark_done("T-a"))
        self._create_milestone("M-1")

        first_path = symphony_projection.publish(self.ledger)
        first_conn = sqlite3.connect(f"file:{first_path}?mode=ro", uri=True)
        try:
            first_rows = first_conn.execute(
                "SELECT id, identifier, title, description, status, dispatchable "
                "FROM task_projection ORDER BY id"
            ).fetchall()
            first_version = first_conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            first_conn.close()

        second_path = symphony_projection.publish(self.ledger)
        second_conn = sqlite3.connect(f"file:{second_path}?mode=ro", uri=True)
        try:
            second_rows = second_conn.execute(
                "SELECT id, identifier, title, description, status, dispatchable "
                "FROM task_projection ORDER BY id"
            ).fetchall()
            second_version = second_conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            second_conn.close()

        self.assertEqual(first_path, second_path)
        self.assertEqual(first_rows, second_rows)
        self.assertEqual(first_version, second_version)

    def test_publish_fully_rewrites_rather_than_accumulates(self):
        # A row present at the first publish but no longer eligible under
        # the query (archived) must not linger in the export from a prior
        # publish — the table is dropped and recreated, never patched.
        self._create_task("T-1")
        symphony_projection.publish(self.ledger)
        self.assertTrue(self.ledger.mark_done("T-1"))
        self.assertTrue(self.ledger.archive_work_item("T-1"))

        path = symphony_projection.publish(self.ledger)
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT id FROM task_projection").fetchall()
        finally:
            conn.close()
        self.assertEqual(rows, [])


class TestClaimTaskConcurrency(LedgerTestCase):
    """specs/003-symphony-task-integration T020 (Acceptance Scenario 3.2,
    SC-008): mirrors tests/test_work_ledger.py's own
    `test_concurrent_claim_attempts_have_exactly_one_winner` real-thread
    technique — of any number of concurrent `claim_task()` attempts
    against one never-before-claimed task, exactly one succeeds and every
    other receives an immediate, unambiguous rejection."""

    def test_concurrent_claim_task_attempts_have_exactly_one_winner(self):
        self._create_task("T-race")

        thread_count = 8
        barrier = threading.Barrier(thread_count)
        results = [None] * thread_count

        def attempt(index):
            barrier.wait()
            results[index] = symphony_projection.claim_task(
                self.ledger, "T-race", f"owner-{index}"
            )

        threads = [
            threading.Thread(target=attempt, args=(i,)) for i in range(thread_count)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        oks = [r.ok for r in results]
        self.assertEqual(oks.count(True), 1)
        self.assertEqual(oks.count(False), thread_count - 1)
        for result in results:
            if not result.ok:
                self.assertEqual(result.reason, "already_claimed")


class TestReleaseAndCompleteTask(LedgerTestCase):
    """specs/003-symphony-task-integration T021 (Acceptance Scenarios
    3.1, 3.3, 3.4): `release_task()` by the recorded owner succeeds and
    is a no-op when the claim is already absent or held by someone else;
    `complete_task()` transitions an open, claimed task to done and is
    rejected — not silently reapplied — against a task that is not
    currently open."""

    def test_claim_then_release_by_recorded_owner_succeeds(self):
        self._create_task("T-1")
        claim_result = symphony_projection.claim_task(self.ledger, "T-1", "owner-1")
        self.assertTrue(claim_result.ok)

        release_result = symphony_projection.release_task(self.ledger, "T-1", "owner-1")
        self.assertTrue(release_result.ok)
        self.assertFalse(self.ledger.is_claimed("T-1"))

    def test_release_by_non_owner_is_a_no_op_not_an_error(self):
        self._create_task("T-1")
        self.assertTrue(symphony_projection.claim_task(self.ledger, "T-1", "owner-1").ok)

        result = symphony_projection.release_task(self.ledger, "T-1", "someone-else")
        self.assertTrue(result.ok)
        # The claim is untouched — still held by the real owner.
        self.assertTrue(self.ledger.is_claimed("T-1"))
        item = self.ledger.get_work_item("T-1")
        self.assertEqual(item.status, "open")

    def test_release_of_already_unclaimed_task_is_a_no_op(self):
        self._create_task("T-1")
        result = symphony_projection.release_task(self.ledger, "T-1", "owner-1")
        self.assertTrue(result.ok)
        self.assertFalse(self.ledger.is_claimed("T-1"))

    def test_complete_claimed_open_task_transitions_to_done(self):
        self._create_task("T-1")
        self.assertTrue(symphony_projection.claim_task(self.ledger, "T-1", "owner-1").ok)

        result = symphony_projection.complete_task(self.ledger, "T-1")
        self.assertTrue(result.ok)
        item = self.ledger.get_work_item("T-1")
        self.assertEqual(item.status, "done")

    def test_complete_against_a_task_that_is_not_open_is_rejected(self):
        self._create_task("T-1")
        self.assertTrue(symphony_projection.complete_task(self.ledger, "T-1").ok)

        result = symphony_projection.complete_task(self.ledger, "T-1")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_open")

    def test_claim_release_reclaim_and_complete_full_lifecycle(self):
        self._create_task("T-1")
        self.assertTrue(symphony_projection.claim_task(self.ledger, "T-1", "owner-1").ok)
        self.assertTrue(symphony_projection.release_task(self.ledger, "T-1", "owner-1").ok)
        self.assertTrue(symphony_projection.claim_task(self.ledger, "T-1", "owner-2").ok)
        self.assertTrue(symphony_projection.complete_task(self.ledger, "T-1").ok)
        self.assertEqual(self.ledger.get_work_item("T-1").status, "done")

    def test_claim_against_nonexistent_id_is_not_found(self):
        result = symphony_projection.claim_task(self.ledger, "no-such-id", "owner-1")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_found")

    def test_release_against_nonexistent_id_is_not_found(self):
        result = symphony_projection.release_task(self.ledger, "no-such-id", "owner-1")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_found")

    def test_complete_against_nonexistent_id_is_not_found(self):
        result = symphony_projection.complete_task(self.ledger, "no-such-id")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_found")


class TestWriteSurfaceRejectsMilestone(LedgerTestCase):
    """specs/003-symphony-task-integration T022 (Acceptance Scenario 3.5,
    FR-024): `claim_task`/`release_task`/`complete_task` each return a
    `not_a_task` result against a milestone id, rather than silently
    treating it as a task."""

    def test_claim_task_rejects_milestone(self):
        self._create_milestone("M-1")
        result = symphony_projection.claim_task(self.ledger, "M-1", "owner-1")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_a_task")
        self.assertFalse(self.ledger.is_claimed("M-1"))

    def test_release_task_rejects_milestone(self):
        self._create_milestone("M-1")
        # Even a real milestone claim (acquired directly through the
        # underlying ledger primitive, not through this write surface)
        # must not be released through the task-only surface.
        self.assertTrue(self.ledger.claim("M-1", "reviewer"))
        result = symphony_projection.release_task(self.ledger, "M-1", "reviewer")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_a_task")
        self.assertTrue(self.ledger.is_claimed("M-1"))

    def test_complete_task_rejects_milestone(self):
        self._create_milestone("M-1")
        result = symphony_projection.complete_task(self.ledger, "M-1")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_a_task")
        item = self.ledger.get_work_item("M-1")
        self.assertEqual(item.status, "open")


_QUICKSTART_TASKS_MD = """\
# Tasks: Example Feature

## Phase 1

- [ ] T001 First unblocked task.
- [ ] T002 Second task, blocked on the first. Depends on: T001.
- [ ] T003 Third, independent task.
"""


class TestQuickstartEndToEnd(LedgerTestCase):
    """specs/003-symphony-task-integration/quickstart.md, Scenarios 1-4,
    end to end: load a Spec Kit feature, publish the projection, and
    claim/release/complete a task through the write surface — mirroring
    tests/test_work_ledger.py's own `TestQuickstartEndToEnd` convention.
    """

    def test_quickstart_scenarios_1_through_4(self):
        from bindle import speckit_loader

        feature_dir_rel = "specs/999-example-feature"
        feature_dir_abs = os.path.join(self.repo_root, feature_dir_rel)
        os.makedirs(feature_dir_abs, exist_ok=True)
        with open(os.path.join(feature_dir_abs, "tasks.md"), "w") as f:
            f.write(_QUICKSTART_TASKS_MD)

        # -- Scenario 1: load, then reload idempotently ------------------
        result = speckit_loader.load_feature(self.ledger, feature_dir_rel)
        self.assertEqual(len(result.created), 3)
        self.assertEqual(result.resynced, ())
        t1, t2, t3 = (
            f"speckit:999-example-feature:T{n}" for n in ("001", "002", "003")
        )
        self.assertEqual(set(result.created), {t1, t2, t3})
        self.assertTrue(self.ledger.is_blocked(t2))
        self.assertFalse(self.ledger.is_blocked(t1))
        self.assertFalse(self.ledger.is_blocked(t3))

        self.ledger.mark_done(t1)
        self.ledger.claim(t3, owner="agent-A")

        result2 = speckit_loader.load_feature(self.ledger, feature_dir_rel)
        self.assertEqual(result2.created, ())
        self.assertEqual(result2.resynced, ())
        self.assertEqual(self.ledger.get_work_item(t1).status, "done")
        self.assertTrue(self.ledger.is_claimed(t3))

        # -- Scenario 2: publish, task-only, dispatchable is correct ------
        milestone_id = "M-1"
        self._create_milestone(milestone_id)
        export_path = symphony_projection.publish(self.ledger)

        conn = sqlite3.connect(f"file:{export_path}?mode=ro", uri=True)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
            rows = {
                row[0]: row
                for row in conn.execute(
                    "SELECT id, identifier, status, dispatchable FROM task_projection"
                ).fetchall()
            }
        finally:
            conn.close()

        self.assertNotIn(milestone_id, rows)
        self.assertEqual(rows[t1][2], "done")
        self.assertEqual(rows[t1][3], 0)  # done is never dispatchable
        self.assertEqual(rows[t2][3], 1)  # unblocked now that t1 is done
        self.assertEqual(rows[t3][3], 0)  # claimed

        # -- Scenario 3: regeneration is deterministic --------------------
        export_path_2 = symphony_projection.publish(self.ledger)
        conn = sqlite3.connect(f"file:{export_path_2}?mode=ro", uri=True)
        try:
            rows_2 = conn.execute(
                "SELECT id, identifier, status, dispatchable FROM task_projection ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        conn = sqlite3.connect(f"file:{export_path}?mode=ro", uri=True)
        try:
            rows_1 = conn.execute(
                "SELECT id, identifier, status, dispatchable FROM task_projection ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(rows_1, rows_2)

        # -- Scenario 4: claim / release / complete through the write surface
        self.ledger.release_claim(t3, owner="agent-A")
        claim_result = symphony_projection.claim_task(self.ledger, t2, owner="agent-B")
        self.assertTrue(claim_result.ok)  # t1 is done, so t2 is now unblocked

        second_claim = symphony_projection.claim_task(self.ledger, t2, owner="agent-C")
        self.assertFalse(second_claim.ok)
        self.assertEqual(second_claim.reason, "already_claimed")

        release_result = symphony_projection.release_task(self.ledger, t2, owner="agent-B")
        self.assertTrue(release_result.ok)

        symphony_projection.claim_task(self.ledger, t2, owner="agent-B")
        complete_result = symphony_projection.complete_task(self.ledger, t2)
        self.assertTrue(complete_result.ok)
        self.assertEqual(self.ledger.get_work_item(t2).status, "done")

        milestone_result = symphony_projection.claim_task(
            self.ledger, milestone_id, owner="agent-B"
        )
        self.assertFalse(milestone_result.ok)
        self.assertEqual(milestone_result.reason, "not_a_task")


class TestApplicationIdOwnership(LedgerTestCase):
    # Mirrors tests/test_work_ledger.py's own TestApplicationIdOwnership,
    # applied to the disposable, regenerated projection file: an absent
    # file is always safe to create; one already carrying
    # `_APPLICATION_ID`, or a pre-marker file whose `user_version`/table
    # set positively match the known projection shape, is safe to adopt
    # and regenerate; anything else must fail closed.
    def _db_path(self):
        return symphony_projection.projection_path(self.repo_root)

    def test_fresh_publish_stamps_the_application_id(self):
        symphony_projection.publish(self.ledger)
        conn = sqlite3.connect(self._db_path())
        try:
            self.assertEqual(
                conn.execute("PRAGMA application_id").fetchone()[0],
                symphony_projection._APPLICATION_ID,
            )
        finally:
            conn.close()

    def test_premarker_v1_projection_is_adopted_and_stamped(self):
        os.makedirs(os.path.dirname(self._db_path()), exist_ok=True)
        conn = sqlite3.connect(self._db_path())
        conn.execute(symphony_projection._CREATE_TASK_PROJECTION_SQL)
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()

        self._create_task("T-1")
        symphony_projection.publish(self.ledger)

        conn = sqlite3.connect(self._db_path())
        try:
            self.assertEqual(
                conn.execute("PRAGMA application_id").fetchone()[0],
                symphony_projection._APPLICATION_ID,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT identifier FROM task_projection"
                ).fetchall(),
                [("T-1",)],
            )
        finally:
            conn.close()

    def test_foreign_database_with_unrelated_tables_refuses(self):
        os.makedirs(os.path.dirname(self._db_path()), exist_ok=True)
        conn = sqlite3.connect(self._db_path())
        conn.execute("CREATE TABLE unrelated_stuff (id INTEGER PRIMARY KEY, val TEXT)")
        conn.execute("INSERT INTO unrelated_stuff (val) VALUES ('precious')")
        conn.commit()
        conn.close()

        with self.assertRaises(symphony_projection.ForeignDatabaseError):
            symphony_projection.publish(self.ledger)

        conn = sqlite3.connect(self._db_path())
        try:
            self.assertEqual(
                conn.execute("SELECT val FROM unrelated_stuff").fetchall(),
                [("precious",)],
            )
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertEqual(tables, {"unrelated_stuff"})
        finally:
            conn.close()

    def test_foreign_nonzero_application_id_refuses_even_with_matching_tables(self):
        os.makedirs(os.path.dirname(self._db_path()), exist_ok=True)
        conn = sqlite3.connect(self._db_path())
        conn.execute(symphony_projection._CREATE_TASK_PROJECTION_SQL)
        conn.execute("PRAGMA user_version = 1")
        conn.execute("PRAGMA application_id = 999999")
        conn.commit()
        conn.close()

        with self.assertRaises(symphony_projection.ForeignDatabaseError):
            symphony_projection.publish(self.ledger)

    def test_unreadable_file_refuses_with_foreign_database_error(self):
        os.makedirs(os.path.dirname(self._db_path()), exist_ok=True)
        with open(self._db_path(), "w") as f:
            f.write("this is not a sqlite database at all\n" * 50)

        with self.assertRaises(symphony_projection.ForeignDatabaseError):
            symphony_projection.publish(self.ledger)

    def test_absent_path_is_treated_as_fresh(self):
        self.assertFalse(os.path.exists(self._db_path()))

        symphony_projection.publish(self.ledger)

        conn = sqlite3.connect(self._db_path())
        try:
            self.assertEqual(
                conn.execute("PRAGMA application_id").fetchone()[0],
                symphony_projection._APPLICATION_ID,
            )
        finally:
            conn.close()

    def test_preexisting_zero_byte_file_refuses(self):
        # A 0-byte file already occupying the canonical path BEFORE
        # publish() ever runs is a placeholder Bindle never created —
        # unlike the identical-looking state connect() itself produces
        # for an absent path, this must refuse rather than be silently
        # adopted as fresh.
        os.makedirs(os.path.dirname(self._db_path()), exist_ok=True)
        open(self._db_path(), "w").close()
        self.assertEqual(os.path.getsize(self._db_path()), 0)

        with self.assertRaises(symphony_projection.ForeignDatabaseError):
            symphony_projection.publish(self.ledger)

        self.assertEqual(os.path.getsize(self._db_path()), 0)

    def test_matching_table_name_and_version_but_wrong_column_shape_refuses(self):
        # Adversarial case: a foreign database that happens to reuse
        # Bindle's exact table name and a recognized user_version, but
        # whose columns don't actually match.
        os.makedirs(os.path.dirname(self._db_path()), exist_ok=True)
        conn = sqlite3.connect(self._db_path())
        conn.execute(
            "CREATE TABLE task_projection (id TEXT PRIMARY KEY, definitely_not_ours TEXT)"
        )
        conn.execute(
            "INSERT INTO task_projection (id, definitely_not_ours) VALUES ('X', 'precious')"
        )
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()

        with self.assertRaises(symphony_projection.ForeignDatabaseError):
            symphony_projection.publish(self.ledger)

        conn = sqlite3.connect(self._db_path())
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT definitely_not_ours FROM task_projection WHERE id = 'X'"
                ).fetchall(),
                [("precious",)],
            )
            self.assertEqual(conn.execute("PRAGMA application_id").fetchone()[0], 0)
        finally:
            conn.close()

    def test_preexisting_nonzero_empty_sqlite_file_refuses_regardless_of_size(self):
        # File size is not a trustworthy ownership signal: an unrelated,
        # genuinely empty SQLite database (application_id=0, user_version=0,
        # no tables) that happens to be nonzero-size (e.g. because some
        # other process already opened it) must refuse exactly like a
        # literal 0-byte placeholder.
        db_path = self._db_path()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path, isolation_level=None)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.close()
        self.assertGreater(os.path.getsize(db_path), 0)

        with self.assertRaises(symphony_projection.ForeignDatabaseError):
            symphony_projection.publish(self.ledger)

        conn = sqlite3.connect(db_path)
        try:
            self.assertEqual(conn.execute("PRAGMA application_id").fetchone()[0], 0)
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertEqual(tables, set())
        finally:
            conn.close()

    def test_fresh_creation_is_stamped_before_publish_can_fail_and_retry_succeeds(self):
        # Mirrors work_ledger's identical retry-safety test: a path absent
        # before this invocation is stamped `_APPLICATION_ID` immediately,
        # before the regenerate transaction runs — so a crash mid-publish
        # still leaves a file the next `publish()` attempt positively
        # recognizes as its own, purely from the marker (no filesize/
        # content heuristic).
        db_path = self._db_path()
        self.assertFalse(os.path.exists(db_path))

        real_sql = symphony_projection._CREATE_TASK_PROJECTION_SQL
        symphony_projection._CREATE_TASK_PROJECTION_SQL = "CREATE TABLE this is not valid sql"
        try:
            with self.assertRaises(sqlite3.OperationalError):
                symphony_projection.publish(self.ledger)
        finally:
            symphony_projection._CREATE_TASK_PROJECTION_SQL = real_sql

        raw_conn = sqlite3.connect(db_path)
        try:
            self.assertEqual(
                raw_conn.execute("PRAGMA application_id").fetchone()[0],
                symphony_projection._APPLICATION_ID,
            )
            self.assertEqual(raw_conn.execute("PRAGMA user_version").fetchone()[0], 0)
            tables = {
                row[0]
                for row in raw_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertEqual(tables, set())
        finally:
            raw_conn.close()

        # A retry succeeds — recognized via the marker alone.
        symphony_projection.publish(self.ledger)
        conn = sqlite3.connect(db_path)
        try:
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0],
                symphony_projection._PROJECTION_VERSION,
            )
        finally:
            conn.close()


class TestProjectionEnsureGitignored(unittest.TestCase):
    # docs/DECISIONS.md: `bindle init` locally ignores exactly the
    # canonical projection artifact and its SQLite sidecars — never the
    # tracked `.gitignore`, never a broader `.bindle-work/` rule.
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        self._run(["git", "init", "--initial-branch=main"])
        self._run(["git", "config", "user.email", "test@example.com"])
        self._run(["git", "config", "user.name", "Test"])
        with open(os.path.join(self.repo, "README.md"), "w") as f:
            f.write("test\n")
        self._run(["git", "add", "README.md"])
        self._run(["git", "commit", "-m", "chore: initial commit"])
        self.git_common_dir = os.path.join(self.repo, ".git")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, args):
        subprocess.run(args, cwd=self.repo, check=True, capture_output=True, text=True)

    def _exclude_lines(self):
        path = os.path.join(self.git_common_dir, "info", "exclude")
        if not os.path.isfile(path):
            return []
        with open(path) as f:
            return f.read().splitlines()

    def test_adds_exactly_the_projection_and_its_three_sidecars(self):
        symphony_projection.ensure_gitignored(self.git_common_dir)
        lines = self._exclude_lines()
        self.assertIn("/.bindle-work/symphony-projection.sqlite3", lines)
        self.assertIn("/.bindle-work/symphony-projection.sqlite3-journal", lines)
        self.assertIn("/.bindle-work/symphony-projection.sqlite3-wal", lines)
        self.assertIn("/.bindle-work/symphony-projection.sqlite3-shm", lines)
        self.assertNotIn("/.bindle-work/ledger.sqlite3", lines)

    def test_idempotent_no_duplicate_lines(self):
        symphony_projection.ensure_gitignored(self.git_common_dir)
        symphony_projection.ensure_gitignored(self.git_common_dir)
        lines = self._exclude_lines()
        self.assertEqual(lines.count("/.bindle-work/symphony-projection.sqlite3"), 1)

    def test_never_writes_the_tracked_gitignore(self):
        gitignore = os.path.join(self.repo, ".gitignore")
        with open(gitignore, "w") as f:
            f.write("*.log\n")
        self._run(["git", "add", ".gitignore"])
        self._run(["git", "commit", "-m", "add gitignore"])

        symphony_projection.ensure_gitignored(self.git_common_dir)

        with open(gitignore) as f:
            self.assertEqual(f.read(), "*.log\n")


if __name__ == "__main__":
    unittest.main()
