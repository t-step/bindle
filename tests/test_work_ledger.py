import inspect
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle import work_ledger

_NOW = "2026-08-26T00:00:00Z"


class LedgerTestCase(unittest.TestCase):
    """Base fixture: a temp directory standing in for a repository's Git
    common-directory-resolved `repo_root` (`RepoInfo.repo_root`) — this
    module never itself shells out to Git, so no real repository is
    needed, only a stable path other tests can also resolve the same
    ledger from (simulating a second worktree/session)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_root = self.tmp.name
        self.ledger = work_ledger.WorkLedger(self.repo_root)

    def tearDown(self):
        self.tmp.cleanup()


class TestSchemaBootstrap(LedgerTestCase):
    def test_fresh_database_initializes_all_tables(self):
        conn = work_ledger.connect(self.repo_root)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertEqual(
                tables,
                {
                    "work_items",
                    "work_item_blocked_by",
                    "work_item_claims",
                    "work_item_evidence",
                },
            )
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0],
                work_ledger._SCHEMA_VERSION,
            )
        finally:
            conn.close()

    def test_mandatory_pragmas_are_set(self):
        conn = work_ledger.connect(self.repo_root)
        try:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(
                conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal"
            )
            self.assertEqual(conn.execute("PRAGMA synchronous").fetchone()[0], 1)
        finally:
            conn.close()

    def test_reopening_does_not_recreate_or_reset_schema(self):
        conn1 = work_ledger.connect(self.repo_root)
        conn1.execute(
            "INSERT INTO work_items "
            "(id, type, status, source_kind, source_locator, created_at, updated_at) "
            "VALUES ('WI-1', 'task', 'open', 'adhoc', 'x', ?, ?)",
            (_NOW, _NOW),
        )
        conn1.close()

        conn2 = work_ledger.connect(self.repo_root)
        try:
            row = conn2.execute(
                "SELECT id FROM work_items WHERE id = 'WI-1'"
            ).fetchone()
            self.assertEqual(row[0], "WI-1")
        finally:
            conn2.close()

    def test_mismatched_schema_version_raises(self):
        conn = work_ledger.connect(self.repo_root)
        conn.execute("PRAGMA user_version = 99")
        conn.close()

        with self.assertRaises(work_ledger.SchemaVersionError):
            work_ledger.connect(self.repo_root)

    def test_foreign_key_violation_is_rejected_at_write_time(self):
        conn = work_ledger.connect(self.repo_root)
        try:
            conn.execute(
                "INSERT INTO work_items "
                "(id, type, status, source_kind, source_locator, created_at, updated_at) "
                "VALUES ('WI-1', 'task', 'open', 'adhoc', 'x', ?, ?)",
                (_NOW, _NOW),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO work_item_blocked_by (work_item_id, blocked_on_id) "
                    "VALUES ('WI-1', 'does-not-exist')"
                )
        finally:
            conn.close()

    def test_self_cycle_is_rejected_at_write_time(self):
        conn = work_ledger.connect(self.repo_root)
        try:
            conn.execute(
                "INSERT INTO work_items "
                "(id, type, status, source_kind, source_locator, created_at, updated_at) "
                "VALUES ('WI-1', 'task', 'open', 'adhoc', 'x', ?, ?)",
                (_NOW, _NOW),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO work_item_blocked_by (work_item_id, blocked_on_id) "
                    "VALUES ('WI-1', 'WI-1')"
                )
        finally:
            conn.close()

    def test_failed_fresh_initialization_rolls_back_schema_and_then_succeeds(self):
        """A failure partway through fresh schema initialization must not
        leave a half-created schema behind (the bug this test guards
        against: each CREATE TABLE previously committed individually under
        autocommit, so a failure after some tables existed but before
        `PRAGMA user_version` was set left the ledger permanently
        unopenable — the next `connect()` would see `user_version == 0`
        again and fail trying to recreate already-existing tables).

        Fault injection: temporarily replace `_SCHEMA_STATEMENTS` with a
        tuple containing the first two real CREATE TABLE statements
        followed by deliberately invalid SQL, so `_ensure_schema` raises
        partway through fresh initialization.
        """
        real_statements = work_ledger._SCHEMA_STATEMENTS
        broken_statements = real_statements[:2] + ("CREATE TABLE this is not valid sql",)
        work_ledger._SCHEMA_STATEMENTS = broken_statements
        try:
            with self.assertRaises(sqlite3.OperationalError):
                work_ledger.connect(self.repo_root)
        finally:
            work_ledger._SCHEMA_STATEMENTS = real_statements

        # Inspect on a fresh, raw connection — bypassing work_ledger.connect
        # entirely — so this inspection step does not re-trigger fault
        # injection or re-run _ensure_schema itself.
        db_path = work_ledger.ledger_path(self.repo_root)
        raw_conn = sqlite3.connect(db_path)
        try:
            self.assertEqual(
                raw_conn.execute("PRAGMA user_version").fetchone()[0], 0
            )
            tables = {
                row[0]
                for row in raw_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertEqual(tables, set())
        finally:
            raw_conn.close()

        # Subsequent open (with the real schema restored) initializes
        # normally and produces a fully-initialized schema — the second
        # half of the same guarantee, exercised end-to-end rather than
        # merely implied.
        conn = work_ledger.connect(self.repo_root)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertEqual(
                tables,
                {
                    "work_items",
                    "work_item_blocked_by",
                    "work_item_claims",
                    "work_item_evidence",
                },
            )
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0],
                work_ledger._SCHEMA_VERSION,
            )
        finally:
            conn.close()

        # Indirect signal that connect()'s failure path actually closed the
        # connection it opened (rather than leaking it): an ordinary
        # connect() immediately after the fault-injected failure above
        # succeeds without "database is locked" — a lingering, unclosed
        # connection holding SQLite's write lock would manifest as exactly
        # that error.
        conn2 = work_ledger.connect(self.repo_root)
        conn2.close()


class TestWorkItemCreationAndDurability(LedgerTestCase):
    def test_create_stores_stable_id_title_and_source_pointer(self):
        self.ledger.create_work_item(
            id="WI-1",
            title="Write research.md",
            source_kind="plan",
            source_locator="plans/active/example.md#work",
            source_promoted_by="agent-A",
        )
        item = self.ledger.get_work_item("WI-1")
        self.assertEqual(item.id, "WI-1")
        self.assertEqual(item.title, "Write research.md")
        self.assertEqual(item.status, "open")
        self.assertEqual(item.source_kind, "plan")
        self.assertEqual(item.source_locator, "plans/active/example.md#work")
        self.assertEqual(item.source_promoted_by, "agent-A")
        self.assertIsNone(item.superseded_by)
        self.assertIsNone(item.archived_at)

    def test_created_item_is_recoverable_from_a_second_independent_ledger_handle(self):
        self.ledger.create_work_item(
            id="WI-1",
            title="Write research.md",
            source_kind="plan",
            source_locator="plans/active/example.md#work",
        )

        # A second, independent WorkLedger over the same repo_root —
        # simulating a fresh session in a different worktree, with no
        # state carried from the first.
        second = work_ledger.WorkLedger(self.repo_root)
        item = second.get_work_item("WI-1")
        self.assertIsNotNone(item)
        self.assertEqual(item.title, "Write research.md")
        self.assertEqual(item.source_locator, "plans/active/example.md#work")
        self.assertEqual(item.status, "open")

        listed = second.list_work_items()
        self.assertEqual([i.id for i in listed], ["WI-1"])

    def test_no_item_is_created_without_an_explicit_create_call(self):
        # Nothing analogous to editing an upstream tasks.md happens here —
        # merely opening/bootstrapping the ledger must not create any item
        # on its own.
        self.assertEqual(self.ledger.list_work_items(), [])
        self.assertIsNone(self.ledger.get_work_item("WI-1"))

    def test_create_with_initial_blocked_by_is_atomic(self):
        self.ledger.create_work_item(
            id="WI-1", title="A", source_kind="adhoc", source_locator="x"
        )
        self.ledger.create_work_item(
            id="WI-2",
            title="B",
            source_kind="adhoc",
            source_locator="y",
            blocked_by=["WI-1"],
        )
        conn = work_ledger.connect(self.repo_root)
        try:
            edges = conn.execute(
                "SELECT work_item_id, blocked_on_id FROM work_item_blocked_by"
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(edges, [("WI-2", "WI-1")])

    def test_create_with_dangling_blocked_by_creates_neither_item_nor_edge(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.create_work_item(
                id="WI-2",
                title="B",
                source_kind="adhoc",
                source_locator="y",
                blocked_by=["does-not-exist"],
            )
        self.assertIsNone(self.ledger.get_work_item("WI-2"))
        conn = work_ledger.connect(self.repo_root)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM work_item_blocked_by"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)


class TestBlockingAndAvailability(LedgerTestCase):
    """User Story 2 (T019-T022): blocking, claim, and availability facts,
    computed fresh from repository state per data-model.md's "Derived
    facts" and "Available to start"."""

    def _create(self, id, blocked_by=()):
        self.ledger.create_work_item(
            id=id,
            title=f"Item {id}",
            source_kind="adhoc",
            source_locator=f"plans/active/example.md#{id}",
            blocked_by=blocked_by,
        )

    def test_chain_of_blocking_relationships_excludes_blocked_items(self):
        # T019 (Acceptance Scenario 2.1, SC-002): A blocked_by B, B blocked_by C.
        self._create("C")
        self._create("B", blocked_by=["C"])
        self._create("A", blocked_by=["B"])

        self.assertTrue(self.ledger.is_blocked("A"))
        self.assertTrue(self.ledger.is_blocked("B"))
        self.assertFalse(self.ledger.is_blocked("C"))

        available = self.ledger.list_available_work_items()
        self.assertEqual(available, ["C"])
        self.assertNotIn("A", available)
        self.assertNotIn("B", available)

    def test_unblocked_unclaimed_item_is_available(self):
        # T020 (Acceptance Scenario 2.2).
        self._create("WI-1")

        self.assertFalse(self.ledger.is_blocked("WI-1"))
        self.assertFalse(self.ledger.is_claimed("WI-1"))
        self.assertIn("WI-1", self.ledger.list_available_work_items())

    def test_marking_blocker_done_unblocks_its_dependent(self):
        # T021 (Acceptance Scenario 2.3).
        self._create("B")
        self._create("A", blocked_by=["B"])

        self.assertTrue(self.ledger.is_blocked("A"))
        self.assertNotIn("A", self.ledger.list_available_work_items())

        self.assertTrue(self.ledger.mark_done("B"))

        self.assertFalse(self.ledger.is_blocked("A"))
        available = self.ledger.list_available_work_items()
        self.assertIn("A", available)
        self.assertNotIn("B", available)  # B is now done, not open

    def test_guarded_transitions_are_no_ops_when_not_open(self):
        self._create("WI-1")
        self.assertTrue(self.ledger.mark_done("WI-1"))
        # Already done: a second transition attempt does not double-apply.
        self.assertFalse(self.ledger.mark_done("WI-1"))
        self.assertFalse(self.ledger.mark_superseded("WI-1", "WI-2"))
        # Nonexistent item: no row to update.
        self.assertFalse(self.ledger.mark_done("does-not-exist"))

    def test_full_set_availability_enumeration(self):
        # T022 (User Story 2's own Independent Test): a mix of
        # open/unclaimed, open/claimed, blocked, done, and superseded
        # items. The open/claimed fixture is constructed by inserting
        # directly into work_item_claims via a raw connection — never by
        # calling a claim() method, which belongs to the concurrently
        # implemented S4 claims slice and does not exist in this
        # worktree. This keeps S3's availability-computation assertion
        # independent of S4's claim-acquisition correctness.
        self._create("open-unclaimed")

        self._create("open-claimed")
        conn = work_ledger.connect(self.repo_root)
        try:
            conn.execute(
                "INSERT INTO work_item_claims (work_item_id, owner, claimed_at) "
                "VALUES (?, ?, ?)",
                ("open-claimed", "test-owner", _NOW),
            )
        finally:
            conn.close()

        self._create("blocker-open")
        self._create("blocked", blocked_by=["blocker-open"])

        self._create("done-item")
        self.assertTrue(self.ledger.mark_done("done-item"))

        self._create("superseded-target")
        self._create("superseded-item")
        self.assertTrue(
            self.ledger.mark_superseded("superseded-item", "superseded-target")
        )

        available = set(self.ledger.list_available_work_items())
        self.assertEqual(
            available,
            {"open-unclaimed", "blocker-open", "superseded-target"},
        )
        self.assertNotIn("open-claimed", available)
        self.assertNotIn("blocked", available)
        self.assertNotIn("done-item", available)
        self.assertNotIn("superseded-item", available)

        # Cross-check against the individual derived facts too.
        self.assertTrue(self.ledger.is_claimed("open-claimed"))
        self.assertFalse(self.ledger.is_claimed("open-unclaimed"))
        self.assertTrue(self.ledger.is_blocked("blocked"))
        self.assertFalse(self.ledger.is_blocked("blocker-open"))


class TestClaimsEvidenceAndReconciliation(LedgerTestCase):
    """T023-T033, T040-T042: claim arbitration, release, override release,
    evidence, and the reconciliation report's five in-scope findings."""

    def _create(self, item_id, **overrides):
        kwargs = dict(
            id=item_id,
            title=f"Item {item_id}",
            source_kind="adhoc",
            source_locator=f"loc-{item_id}",
        )
        kwargs.update(overrides)
        self.ledger.create_work_item(**kwargs)

    # -- T028: independent claims across two items/worktrees -----------

    def test_two_independent_claims_do_not_affect_each_other(self):
        self._create("WI-1")
        self._create("WI-2")
        wt1 = tempfile.mkdtemp()
        wt2 = tempfile.mkdtemp()
        try:
            self.assertTrue(self.ledger.claim("WI-1", "agent-A", worktree_path=wt1))
            self.assertTrue(self.ledger.claim("WI-2", "agent-B", worktree_path=wt2))

            conn = work_ledger.connect(self.repo_root)
            try:
                rows = {
                    row[0]: row[1:]
                    for row in conn.execute(
                        "SELECT work_item_id, owner, worktree_path "
                        "FROM work_item_claims ORDER BY work_item_id"
                    ).fetchall()
                }
            finally:
                conn.close()
            self.assertEqual(rows["WI-1"], ("agent-A", wt1))
            self.assertEqual(rows["WI-2"], ("agent-B", wt2))
        finally:
            os.rmdir(wt1)
            os.rmdir(wt2)

    # -- T029: exactly one of many attempts against the same item wins --

    def test_only_one_of_many_claim_attempts_on_the_same_item_succeeds(self):
        for trial in range(25):
            item_id = f"WI-trial-{trial}"
            self._create(item_id)

            self.assertTrue(self.ledger.claim(item_id, "owner-0"))
            for attempt in range(5):
                self.assertFalse(
                    self.ledger.claim(item_id, f"owner-{attempt + 1}")
                )

    def test_concurrent_claim_attempts_have_exactly_one_winner(self):
        # FR-018/SC-004a's actual concurrency guarantee: real threads
        # racing against the same never-before-claimed item via SQLite's
        # own primary-key constraint and single-writer serialization —
        # not merely sequential calls, which the test above already
        # covers at the Python-level contract only.
        item_id = "WI-race"
        self._create(item_id)

        thread_count = 8
        barrier = threading.Barrier(thread_count)
        results = [None] * thread_count

        def attempt(index):
            barrier.wait()
            results[index] = self.ledger.claim(item_id, f"owner-{index}")

        threads = [
            threading.Thread(target=attempt, args=(i,)) for i in range(thread_count)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), thread_count - 1)

    def test_claim_against_nonexistent_item_raises_not_already_claimed(self):
        # Asserts precise error classification (sqlite_errorcode), not
        # message-text substring matching: a foreign-key violation (no
        # such work_item_id) must be distinguishable from the
        # primary-key violation claim() treats as an ordinary "already
        # claimed" outcome.
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.ledger.claim("does-not-exist", "agent-A")
        self.assertEqual(
            ctx.exception.sqlite_errorcode, sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY
        )
        self.assertNotEqual(
            ctx.exception.sqlite_errorcode, sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY
        )
        self.assertIn("FOREIGN KEY", str(ctx.exception))

    def test_claim_collision_is_classified_as_primary_key_violation(self):
        # The specific constraint claim() matches on to return False —
        # verified directly, so a future change that widens the except
        # clause to catch unrelated IntegrityErrors is caught here.
        self._create("WI-1")
        self.assertTrue(self.ledger.claim("WI-1", "agent-A"))
        conn = work_ledger.connect(self.repo_root)
        try:
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                conn.execute(
                    "INSERT INTO work_item_claims "
                    "(work_item_id, owner, claimed_at) VALUES (?, ?, ?)",
                    ("WI-1", "agent-B", work_ledger._now()),
                )
        finally:
            conn.close()
        self.assertEqual(
            ctx.exception.sqlite_errorcode, sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY
        )
        # And claim() itself, going through its own except clause,
        # returns False rather than raising for this exact case.
        self.assertFalse(self.ledger.claim("WI-1", "agent-C"))

    def test_release_claim_is_idempotent_and_owner_scoped(self):
        self._create("WI-1")
        self.ledger.release_claim("WI-1", "nobody")  # no-op, never claimed
        self.assertTrue(self.ledger.claim("WI-1", "agent-A"))
        self.ledger.release_claim("WI-1", "agent-B")  # wrong owner: no-op

        conn = work_ledger.connect(self.repo_root)
        try:
            row = conn.execute(
                "SELECT owner FROM work_item_claims WHERE work_item_id = 'WI-1'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "agent-A")

        self.ledger.release_claim("WI-1", "agent-A")
        conn = work_ledger.connect(self.repo_root)
        try:
            row = conn.execute(
                "SELECT owner FROM work_item_claims WHERE work_item_id = 'WI-1'"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNone(row)

    # -- T030: stale_claim, non-mutating -------------------------------

    def test_reconcile_reports_stale_claim_for_deleted_worktree(self):
        self._create("WI-1")
        vanished = tempfile.mkdtemp()
        self.assertTrue(self.ledger.claim("WI-1", "agent-A", worktree_path=vanished))
        os.rmdir(vanished)

        findings = self.ledger.reconcile()
        stale = [f for f in findings if f.finding == "stale_claim"]
        self.assertEqual([f.item_id for f in stale], ["WI-1"])
        self.assertIn(vanished, stale[0].detail)

        # Reconciliation must not mutate the claim row.
        conn = work_ledger.connect(self.repo_root)
        try:
            row = conn.execute(
                "SELECT owner, worktree_path FROM work_item_claims "
                "WHERE work_item_id = 'WI-1'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("agent-A", vanished))

    # -- T031: corrupt_claim, distinct from stale_claim -----------------

    def test_reconcile_reports_corrupt_claim_for_empty_owner(self):
        self._create("WI-1")
        conn = work_ledger.connect(self.repo_root)
        try:
            conn.execute(
                "INSERT INTO work_item_claims "
                "(work_item_id, owner, claimed_at, worktree_path, branch) "
                "VALUES ('WI-1', '', ?, NULL, NULL)",
                (work_ledger._now(),),
            )
        finally:
            conn.close()

        findings = self.ledger.reconcile()
        corrupt = [f for f in findings if f.finding == "corrupt_claim"]
        stale = [f for f in findings if f.finding == "stale_claim"]
        self.assertEqual([f.item_id for f in corrupt], ["WI-1"])
        self.assertEqual(stale, [])

    # -- T032: override release does not itself grant a claim -----------

    def test_override_release_does_not_grant_a_claim(self):
        self._create("WI-1")
        vanished = tempfile.mkdtemp()
        self.assertTrue(self.ledger.claim("WI-1", "agent-A", worktree_path=vanished))
        os.rmdir(vanished)

        self.ledger.override_release_claim("WI-1", note="worktree deleted")

        # The override itself created no claim row.
        conn = work_ledger.connect(self.repo_root)
        try:
            row = conn.execute(
                "SELECT * FROM work_item_claims WHERE work_item_id = 'WI-1'"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNone(row)

        # A subsequent claim() call goes through ordinary arbitration and
        # succeeds because nothing else claimed it first.
        self.assertTrue(self.ledger.claim("WI-1", "agent-B"))

    def test_override_release_records_optional_evidence_note(self):
        self._create("WI-1")
        self.assertTrue(self.ledger.claim("WI-1", "agent-A"))
        self.ledger.override_release_claim("WI-1", note="stale worktree gone")

        conn = work_ledger.connect(self.repo_root)
        try:
            row = conn.execute(
                "SELECT kind, value, note FROM work_item_evidence "
                "WHERE work_item_id = 'WI-1'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("other", "claim-override", "stale worktree gone"))

    def test_override_release_without_note_records_no_evidence(self):
        self._create("WI-1")
        self.assertTrue(self.ledger.claim("WI-1", "agent-A"))
        self.ledger.override_release_claim("WI-1")

        conn = work_ledger.connect(self.repo_root)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM work_item_evidence WHERE work_item_id = 'WI-1'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)

    # -- T033: evidence is left unchanged; no mutation path exists -------

    def test_evidence_pointer_is_immutable_and_unaffected_by_reconcile(self):
        self._create("WI-1")
        self.ledger.add_evidence(
            "WI-1", "branch", "feature/example", note="initial branch"
        )

        conn = work_ledger.connect(self.repo_root)
        try:
            before = conn.execute(
                "SELECT kind, value, note FROM work_item_evidence "
                "WHERE work_item_id = 'WI-1'"
            ).fetchone()
        finally:
            conn.close()

        # Simulate the branch later being rebased/squashed/deleted: this
        # module never re-validates evidence against Git, so nothing
        # should change it. Running reconcile() (which never mutates)
        # confirms there is no accidental side effect either.
        self.ledger.reconcile()

        conn = work_ledger.connect(self.repo_root)
        try:
            after = conn.execute(
                "SELECT kind, value, note FROM work_item_evidence "
                "WHERE work_item_id = 'WI-1'"
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(before, ("branch", "feature/example", "initial branch"))
        self.assertEqual(after, before)
        self.assertFalse(hasattr(self.ledger, "update_evidence"))

    # -- T040: dangling_blocker, distinguishable from a genuinely done --
    # -- dependency ------------------------------------------------------

    def test_reconcile_reports_dangling_blocker_distinct_from_done_dependency(self):
        self._create("WI-1")  # will become a genuinely completed dependency
        self._create("WI-2")  # will declare a dangling reference

        conn = work_ledger.connect(self.repo_root)
        try:
            conn.execute(
                "UPDATE work_items SET status = 'done', updated_at = ? WHERE id = 'WI-1'",
                (work_ledger._now(),),
            )
            conn.execute(
                "INSERT INTO work_item_blocked_by (work_item_id, blocked_on_id) "
                "VALUES ('WI-2', 'WI-1')"
            )
        finally:
            conn.close()

        conn = work_ledger.connect(self.repo_root)
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                "INSERT INTO work_item_blocked_by (work_item_id, blocked_on_id) "
                "VALUES ('WI-2', 'never-existed')"
            )
        finally:
            conn.close()

        findings = self.ledger.reconcile()
        dangling = [f for f in findings if f.finding == "dangling_blocker"]
        self.assertEqual(len(dangling), 1)
        self.assertEqual(dangling[0].item_id, "WI-2")
        self.assertIn("never-existed", dangling[0].detail)
        # The edge to the genuinely completed WI-1 must not be reported.
        self.assertNotIn("WI-1", dangling[0].detail)

    # -- T041: duplicate_source ------------------------------------------

    def test_reconcile_reports_duplicate_source(self):
        self.ledger.create_work_item(
            id="WI-1",
            title="A",
            source_kind="plan",
            source_locator="plans/active/example.md#work",
        )
        self.ledger.create_work_item(
            id="WI-2",
            title="B",
            source_kind="plan",
            source_locator="plans/active/example.md#work",
        )

        findings = self.ledger.reconcile()
        duplicates = [f for f in findings if f.finding == "duplicate_source"]
        self.assertEqual(len(duplicates), 1)
        self.assertIsNone(duplicates[0].item_id)
        self.assertIn("WI-1", duplicates[0].detail)
        self.assertIn("WI-2", duplicates[0].detail)

    # -- T042: cycle_detected (indirect cycle) ----------------------------

    def test_reconcile_reports_indirect_cycle(self):
        self._create("WI-A")
        self._create("WI-B")

        conn = work_ledger.connect(self.repo_root)
        try:
            conn.execute(
                "INSERT INTO work_item_blocked_by (work_item_id, blocked_on_id) "
                "VALUES ('WI-A', 'WI-B')"
            )
            conn.execute(
                "INSERT INTO work_item_blocked_by (work_item_id, blocked_on_id) "
                "VALUES ('WI-B', 'WI-A')"
            )
        finally:
            conn.close()

        findings = self.ledger.reconcile()
        cycles = {f.item_id for f in findings if f.finding == "cycle_detected"}
        self.assertEqual(cycles, {"WI-A", "WI-B"})


def _run_git(args, cwd):
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout


class TestReconcileBranchExistence(unittest.TestCase):
    """Regression for the bug where reconcile()'s stale_claim query only
    ever selected rows with `worktree_path IS NOT NULL`, so a claim
    recorded with only a `branch` (no `worktree_path`) could never be
    reported stale, no matter how long that branch had been gone
    (FR-009, data-model.md's "Staleness", tasks.md's T027). Uses a real
    temporary Git repository (rather than mocking the branch check) so
    the assertions exercise the actual `git show-ref` semantics
    `_local_branch_exists` relies on."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_root = self.tmp.name
        _run_git(["init", "-q"], self.repo_root)
        _run_git(["config", "user.email", "test@example.com"], self.repo_root)
        _run_git(["config", "user.name", "Test"], self.repo_root)
        with open(os.path.join(self.repo_root, "README.md"), "w") as f:
            f.write("x\n")
        _run_git(["add", "README.md"], self.repo_root)
        _run_git(["commit", "-q", "-m", "init"], self.repo_root)
        self.ledger = work_ledger.WorkLedger(self.repo_root)

    def tearDown(self):
        self.tmp.cleanup()

    def _create(self, item_id):
        self.ledger.create_work_item(
            id=item_id,
            title=f"Item {item_id}",
            source_kind="adhoc",
            source_locator=f"loc-{item_id}",
        )

    def test_branch_only_claim_with_nonexistent_branch_is_reported_stale(self):
        self._create("WI-1")
        self.assertTrue(
            self.ledger.claim(
                "WI-1", "agent-A", branch="feature/nonexistent-branch-xyz"
            )
        )

        findings = self.ledger.reconcile()
        stale = [f for f in findings if f.finding == "stale_claim"]
        self.assertEqual([f.item_id for f in stale], ["WI-1"])
        self.assertIn("feature/nonexistent-branch-xyz", stale[0].detail)

        # Reconciliation must remain read-only: the claim row survives.
        conn = work_ledger.connect(self.repo_root)
        try:
            row = conn.execute(
                "SELECT owner FROM work_item_claims WHERE work_item_id = 'WI-1'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("agent-A",))
        # And it must continue to make the item unavailable.
        self.assertNotIn("WI-1", self.ledger.list_available_work_items())

    def test_branch_only_claim_with_existing_branch_is_not_stale(self):
        _run_git(["branch", "feature/real-branch"], self.repo_root)
        self._create("WI-2")
        self.assertTrue(
            self.ledger.claim("WI-2", "agent-B", branch="feature/real-branch")
        )

        findings = self.ledger.reconcile()
        stale = [f for f in findings if f.finding == "stale_claim"]
        self.assertEqual(stale, [])

    def test_checked_out_branch_of_the_ledger_repo_itself_is_not_stale(self):
        # Confirms the check discriminates using the real current branch
        # (main or master, whichever `git init` used), not by always
        # returning True/False.
        current_branch = _run_git(
            ["symbolic-ref", "--short", "HEAD"], self.repo_root
        ).strip()
        self._create("WI-3")
        self.assertTrue(self.ledger.claim("WI-3", "agent-C", branch=current_branch))

        findings = self.ledger.reconcile()
        stale = [f for f in findings if f.finding == "stale_claim"]
        self.assertEqual(stale, [])


class TestReconcileWorktreeRegistration(unittest.TestCase):
    """Regression for the bug where reconcile()'s stale_claim check used
    `os.path.isdir(worktree_path)`, which only proves *some* directory
    exists at the recorded path — not that it is still a worktree Git
    itself knows about (FR-009, data-model.md's "Staleness": "no longer
    exists as a worktree on this machine", not "no longer exists as a
    directory"). A worktree properly removed with `git worktree remove`
    frees its path for an unrelated, ordinary directory to occupy later;
    `os.path.isdir` would then incorrectly report the claim as not
    stale. Uses a real temporary Git repository (mirroring
    `TestReconcileBranchExistence`'s own style) so the assertions
    exercise the actual `git worktree list --porcelain` semantics
    `_registered_worktree_paths` relies on."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_root = self.tmp.name
        _run_git(["init", "-q"], self.repo_root)
        _run_git(["config", "user.email", "test@example.com"], self.repo_root)
        _run_git(["config", "user.name", "Test"], self.repo_root)
        with open(os.path.join(self.repo_root, "README.md"), "w") as f:
            f.write("x\n")
        _run_git(["add", "README.md"], self.repo_root)
        _run_git(["commit", "-q", "-m", "init"], self.repo_root)
        self.ledger = work_ledger.WorkLedger(self.repo_root)

    def tearDown(self):
        self.tmp.cleanup()

    def _create(self, item_id):
        self.ledger.create_work_item(
            id=item_id,
            title=f"Item {item_id}",
            source_kind="adhoc",
            source_locator=f"loc-{item_id}",
        )

    def test_directory_at_recorded_path_that_is_not_a_registered_worktree_is_stale(
        self,
    ):
        # A plain directory that was never a Git worktree at all.
        not_a_worktree = tempfile.mkdtemp()
        self.addCleanup(lambda: os.path.isdir(not_a_worktree) and os.rmdir(not_a_worktree))

        self._create("WI-1")
        self.assertTrue(
            self.ledger.claim("WI-1", "agent-A", worktree_path=not_a_worktree)
        )

        findings = self.ledger.reconcile()
        stale = [f for f in findings if f.finding == "stale_claim"]
        self.assertEqual([f.item_id for f in stale], ["WI-1"])
        self.assertIn("not a currently registered Git worktree", stale[0].detail)

        # Reconciliation must remain read-only: the claim row survives.
        conn = work_ledger.connect(self.repo_root)
        try:
            row = conn.execute(
                "SELECT owner FROM work_item_claims WHERE work_item_id = 'WI-1'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("agent-A",))

    def test_ordinary_directory_recreated_at_a_properly_removed_worktrees_path_is_stale(
        self,
    ):
        # The exact scenario the bug allowed through: a worktree is
        # properly removed (both its directory and Git's own
        # administrative registration go away), and something unrelated
        # later creates a plain directory at that same path.
        worktree_path = os.path.join(self.repo_root + "-wt", "reused-path")
        os.makedirs(os.path.dirname(worktree_path), exist_ok=True)
        self.addCleanup(
            lambda: subprocess.run(
                ["rm", "-rf", os.path.dirname(worktree_path)], check=False
            )
        )
        _run_git(
            ["worktree", "add", "-q", "-b", "wt-reused-branch", worktree_path],
            self.repo_root,
        )
        _run_git(["worktree", "remove", worktree_path], self.repo_root)
        os.makedirs(worktree_path)  # an ordinary, unrelated directory now

        self._create("WI-2")
        self.assertTrue(
            self.ledger.claim("WI-2", "agent-B", worktree_path=worktree_path)
        )

        findings = self.ledger.reconcile()
        stale = [f for f in findings if f.finding == "stale_claim"]
        self.assertEqual([f.item_id for f in stale], ["WI-2"])

    def test_real_registered_worktree_is_not_reported_stale(self):
        worktree_path = os.path.join(self.repo_root + "-wt2", "live")
        os.makedirs(os.path.dirname(worktree_path), exist_ok=True)
        self.addCleanup(
            lambda: subprocess.run(
                ["rm", "-rf", os.path.dirname(worktree_path)], check=False
            )
        )
        _run_git(
            ["worktree", "add", "-q", "-b", "wt-live-branch", worktree_path],
            self.repo_root,
        )

        self._create("WI-3")
        self.assertTrue(
            self.ledger.claim("WI-3", "agent-C", worktree_path=worktree_path)
        )

        findings = self.ledger.reconcile()
        stale = [f for f in findings if f.finding == "stale_claim"]
        self.assertEqual(stale, [])


class TestCoordinatorProjection(LedgerTestCase):
    """User Story 4 (T034-T037): a generated, disposable coordinator-facing
    projection (contracts/coordinator-projection.md), never a second
    durable store the ledger falls out of sync with (FR-013/FR-014)."""

    def _create(self, id, blocked_by=()):
        self.ledger.create_work_item(
            id=id,
            title=f"Item {id}",
            source_kind="adhoc",
            source_locator=f"plans/active/example.md#{id}",
            blocked_by=blocked_by,
        )

    def test_blocked_item_is_not_eligible_in_projection(self):
        # T035 (Acceptance Scenario 4.1): a still-blocked item must be
        # withheld from eligibility by the projection step itself, even
        # though nothing about the flat projection shape would otherwise
        # stop an unsophisticated adapter (Symphony's shipped `local`
        # tracker, per the contract) from treating it as dispatchable.
        # This asserts against the *projection's* `eligible` field
        # specifically, not merely `list_available_work_items()` again —
        # that would only re-test S3, not this projection step.
        self._create("blocker-open")
        self._create("blocked", blocked_by=["blocker-open"])

        projection = self.ledger.generate_projection()
        by_id = {item.id: item for item in projection}

        self.assertFalse(by_id["blocked"].eligible)
        self.assertFalse(by_id["blocked"].terminal)
        self.assertTrue(by_id["blocker-open"].eligible)

    def test_projection_is_deterministic_and_performs_no_write(self):
        # T036 (Acceptance Scenario 4.2, SC-005): regenerating a
        # projection twice from the same, unchanged ledger state produces
        # an equal result both times, and generating it performs no write
        # to the ledger's own durable state.
        self._create("blocker-open")
        self._create("blocked", blocked_by=["blocker-open"])
        self._create("done-item")
        self.assertTrue(self.ledger.mark_done("done-item"))

        conn = work_ledger.connect(self.repo_root)
        try:
            before = conn.execute(
                "SELECT * FROM work_items ORDER BY id"
            ).fetchall()
        finally:
            conn.close()

        first = self.ledger.generate_projection()
        second = self.ledger.generate_projection()

        self.assertEqual(first, second)

        conn = work_ledger.connect(self.repo_root)
        try:
            after = conn.execute(
                "SELECT * FROM work_items ORDER BY id"
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual(before, after)
        self.assertEqual(self.ledger.list_work_items(), self.ledger.list_work_items())

    def test_projection_opens_exactly_one_connection_and_query(self):
        # Regression for the bug where generate_projection() called
        # list_available_work_items() (its own connection) and then
        # opened a *second* connection to read id/title/status — a claim
        # landing in the gap between the two reads could produce a
        # stale eligible=True for an item already claimed by the time
        # the call returned. The fix derives both facts from one SELECT
        # on one connection, which this test asserts directly (by
        # instrumentation) rather than only by absence-of-flakiness.
        self._create("WI-1")

        connect_count = 0
        executed_queries = []
        real_connect = self.ledger._connect

        def counting_connect():
            nonlocal connect_count
            connect_count += 1
            conn = real_connect()
            # sqlite3.Connection.execute is a read-only C-level attribute
            # (cannot be monkeypatched directly) — set_trace_callback is
            # the supported way to observe every SQL statement actually
            # executed on this connection.
            conn.set_trace_callback(executed_queries.append)
            return conn

        self.ledger._connect = counting_connect
        try:
            self.ledger.generate_projection()
        finally:
            self.ledger._connect = real_connect

        self.assertEqual(connect_count, 1)
        self.assertEqual(len(executed_queries), 1)

    def test_coordination_facts_available_without_ever_generating_projection(self):
        # T037 (Acceptance Scenario 4.3): every user-facing coordination
        # fact remains fully usable and correct even when
        # generate_projection() is never called at all — no other method
        # has a hidden dependency on projection state, since none exists.
        self._create("blocker-open")
        self._create("blocked", blocked_by=["blocker-open"])
        self.assertTrue(self.ledger.claim("blocker-open", owner="agent-1"))
        self.ledger.add_evidence("blocker-open", kind="branch", value="feature/x")

        item = self.ledger.get_work_item("blocked")
        self.assertEqual(item.status, "open")
        self.assertTrue(self.ledger.is_blocked("blocked"))
        self.assertTrue(self.ledger.is_claimed("blocker-open"))

        conn = work_ledger.connect(self.repo_root)
        try:
            evidence_rows = conn.execute(
                "SELECT kind, value FROM work_item_evidence "
                "WHERE work_item_id = ?",
                ("blocker-open",),
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(evidence_rows, [("branch", "feature/x")])


class TestArchival(LedgerTestCase):
    """T038-T039: archiving a terminal work item thins its row in place
    (data-model.md's "Archival") without ever breaking another item's
    dependency resolution against it (FR-020, FR-021, SC-008)."""

    def _create(self, item_id, **overrides):
        kwargs = dict(
            id=item_id,
            title=f"Item {item_id}",
            source_kind="adhoc",
            source_locator=f"loc-{item_id}",
        )
        kwargs.update(overrides)
        self.ledger.create_work_item(**kwargs)

    # -- T039 (SC-008): archiving a satisfied prerequisite never turns a
    # -- satisfied dependency into an unresolved/unknown one -------------

    def test_archiving_satisfied_prerequisite_keeps_dependent_unblocked(self):
        self._create("A")
        self._create("B", blocked_by=["A"])

        self.assertTrue(self.ledger.mark_done("A"))
        self.assertFalse(self.ledger.is_blocked("B"))

        self.assertTrue(self.ledger.archive_work_item("A"))

        # Archival must not change the answer: still satisfied.
        self.assertFalse(self.ledger.is_blocked("B"))
        self.assertIn("B", self.ledger.list_available_work_items())

    # -- Thinned-row shape: cleared columns vs. permanently retained ones -

    def test_archived_done_item_is_thinned_but_keeps_identity_and_status(self):
        self._create("A", source_promoted_by="agent-A")
        self.assertTrue(self.ledger.mark_done("A"))

        self.assertTrue(self.ledger.archive_work_item("A"))

        item = self.ledger.get_work_item("A")
        self.assertEqual(item.id, "A")
        self.assertEqual(item.status, "done")
        self.assertIsNone(item.superseded_by)
        self.assertIsNotNone(item.archived_at)
        self.assertIsNone(item.title)
        self.assertIsNone(item.source_kind)
        self.assertIsNone(item.source_locator)
        self.assertIsNone(item.source_promoted_by)
        self.assertIsNone(item.created_at)

    def test_archived_superseded_item_keeps_superseded_by(self):
        self._create("A")
        self._create("B")
        self.assertTrue(self.ledger.mark_superseded("A", "B"))

        self.assertTrue(self.ledger.archive_work_item("A"))

        item = self.ledger.get_work_item("A")
        self.assertEqual(item.status, "superseded")
        self.assertEqual(item.superseded_by, "B")
        self.assertIsNotNone(item.archived_at)
        self.assertIsNone(item.title)
        self.assertIsNone(item.source_kind)
        self.assertIsNone(item.source_locator)
        self.assertIsNone(item.created_at)

    # -- Evidence and any lingering claim are deleted at archival ---------

    def test_archival_deletes_evidence_and_lingering_claim(self):
        self._create("A")
        self.ledger.add_evidence("A", "branch", "feature/example")
        self.assertTrue(self.ledger.claim("A", "agent-A"))
        # The model does not require a claim to be released before an
        # item transitions to done — archival's own claim delete is
        # explicitly defensive (data-model.md's "Archival").
        self.assertTrue(self.ledger.mark_done("A"))

        self.assertTrue(self.ledger.archive_work_item("A"))

        conn = work_ledger.connect(self.repo_root)
        try:
            evidence_count = conn.execute(
                "SELECT COUNT(*) FROM work_item_evidence WHERE work_item_id = 'A'"
            ).fetchone()[0]
            claim_row = conn.execute(
                "SELECT * FROM work_item_claims WHERE work_item_id = 'A'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(evidence_count, 0)
        self.assertIsNone(claim_row)

    # -- Only the archived item's own declared edges are deleted ----------

    def test_archival_deletes_only_its_own_declared_edges(self):
        self._create("C")  # A's own prerequisite, already done
        self.assertTrue(self.ledger.mark_done("C"))
        self._create("A", blocked_by=["C"])
        self._create("B", blocked_by=["A"])  # an edge declared *against* A

        self.assertTrue(self.ledger.mark_done("A"))
        self.assertTrue(self.ledger.archive_work_item("A"))

        conn = work_ledger.connect(self.repo_root)
        try:
            rows = set(
                conn.execute(
                    "SELECT work_item_id, blocked_on_id FROM work_item_blocked_by"
                ).fetchall()
            )
        finally:
            conn.close()
        # B's edge onto A — declared by another item against A — survives.
        self.assertIn(("B", "A"), rows)
        # A's own edge onto C — A's own declared dependency, moot once A
        # is terminal and archived — is gone.
        self.assertNotIn(("A", "C"), rows)

        # And B's own blocking evaluation against archived A is unaffected.
        self.assertFalse(self.ledger.is_blocked("B"))

    # -- Archiving a non-terminal item is a guarded no-op ------------------

    def test_archiving_open_item_is_a_no_op(self):
        self._create("A")
        before = self.ledger.get_work_item("A")

        self.assertFalse(self.ledger.archive_work_item("A"))

        after = self.ledger.get_work_item("A")
        self.assertEqual(after, before)

    def test_archiving_nonexistent_item_returns_false(self):
        self.assertFalse(self.ledger.archive_work_item("does-not-exist"))

    # -- Archiving a non-terminal item must not delete its related rows --

    def test_archiving_open_item_leaves_evidence_claim_and_edges_untouched(self):
        # Regression for the bug where the guarded UPDATE not matching
        # (item still `open`) did not stop the three cleanup DELETEs from
        # running unconditionally, silently destroying an open item's
        # evidence, claim, and self-declared blocked_by edge even though
        # archive_work_item() correctly reported `False`.
        self._create("blocker")  # A's own blocked_by target
        self._create("A", blocked_by=["blocker"])
        self.ledger.add_evidence("A", "branch", "feature/example")
        self.assertTrue(self.ledger.claim("A", "agent-A"))

        before = self.ledger.get_work_item("A")

        self.assertFalse(self.ledger.archive_work_item("A"))

        after = self.ledger.get_work_item("A")
        self.assertEqual(after, before)

        conn = work_ledger.connect(self.repo_root)
        try:
            evidence_count = conn.execute(
                "SELECT COUNT(*) FROM work_item_evidence WHERE work_item_id = 'A'"
            ).fetchone()[0]
            claim_row = conn.execute(
                "SELECT owner FROM work_item_claims WHERE work_item_id = 'A'"
            ).fetchone()
            edge_row = conn.execute(
                "SELECT 1 FROM work_item_blocked_by "
                "WHERE work_item_id = 'A' AND blocked_on_id = 'blocker'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(evidence_count, 1)
        self.assertEqual(claim_row, ("agent-A",))
        self.assertIsNotNone(edge_row)

    # -- Re-archiving an already-archived item is safe, not corrupting ----

    def test_archiving_already_archived_item_is_idempotent(self):
        self._create("A")
        # Attach evidence and a claim before the *first* archival so that
        # call's cleanup DELETEs have something real to remove — proving
        # the first call's `if archived:` cleanup actually ran, not just
        # that there was nothing to clean up in the first place.
        self.ledger.add_evidence("A", "branch", "feature/example")
        self.assertTrue(self.ledger.claim("A", "agent-A"))
        self.assertTrue(self.ledger.mark_done("A"))
        self.assertTrue(self.ledger.archive_work_item("A"))
        first = self.ledger.get_work_item("A")

        # A second archival attempt on an already-archived item must now
        # be a determinate, correct `False` — the guard's
        # `AND archived_at IS NULL` means the UPDATE no longer matches
        # this row at all, so nothing about it is touched a second time.
        second_result = self.ledger.archive_work_item("A")
        self.assertFalse(second_result)

        second = self.ledger.get_work_item("A")
        self.assertEqual(second.id, first.id)
        self.assertEqual(second.status, first.status)
        self.assertEqual(second.superseded_by, first.superseded_by)
        self.assertIsNone(second.title)
        self.assertIsNone(second.source_kind)
        self.assertIsNone(second.source_locator)
        self.assertIsNone(second.source_promoted_by)
        self.assertIsNone(second.created_at)
        self.assertIsNotNone(second.archived_at)
        # The core of the fix: archived_at/updated_at are permanent —
        # the second call must not bump either forward to a later
        # timestamp.
        self.assertEqual(second.archived_at, first.archived_at)
        self.assertEqual(second.updated_at, first.updated_at)

        # No cleanup mutation of any kind on the second call: nothing
        # errors, and there is nothing left to double-delete (the first
        # call's cleanup already removed the evidence/claim rows).
        conn = work_ledger.connect(self.repo_root)
        try:
            evidence_count = conn.execute(
                "SELECT COUNT(*) FROM work_item_evidence WHERE work_item_id = 'A'"
            ).fetchone()[0]
            claim_row = conn.execute(
                "SELECT * FROM work_item_claims WHERE work_item_id = 'A'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(evidence_count, 0)
        self.assertIsNone(claim_row)


class TestQuickstartEndToEnd(LedgerTestCase):
    """T043: quickstart.md Scenarios 1-5, end to end, as one coherent pass
    over creation, availability/blocking/archival, claim/reconcile/
    override, concurrent claim arbitration, and projection generation.

    quickstart.md's own Scenario 3 step 1 ("Claim WI-1 from worktree A")
    presumes WI-1 is still an active, claimable item — but Scenario 2's
    own step 5 already archives WI-1 (`done`, thinned). The two top-level
    scenarios are independent narrative illustrations sharing conceptual
    item names, not one strictly cumulative object timeline (quickstart.md
    itself marks several steps "New" as hypothetical continuations, not a
    single unbroken state machine). This test therefore carries Scenario
    1 and 2's own item ids (`WI-1`..`WI-3`) forward only within those two
    scenarios, and introduces fresh ids for Scenarios 3-5 — preserving
    every behavior quickstart.md actually specifies without forcing a
    contradiction quickstart.md itself doesn't resolve.
    """

    def test_quickstart_scenarios_1_through_5(self):
        # -- Scenario 1: decompose and recover (User Story 1) -----------
        self.ledger.create_work_item(
            id="WI-1",
            title="write research.md",
            source_kind="plan",
            source_locator="specs/001-durable-work-ledger/plan.md",
        )
        self.ledger.create_work_item(
            id="WI-2",
            title="write data-model.md",
            source_kind="plan",
            source_locator="specs/001-durable-work-ledger/plan.md",
        )
        self.ledger.create_work_item(
            id="WI-3",
            title="write quickstart.md",
            source_kind="plan",
            source_locator="specs/001-durable-work-ledger/plan.md",
        )

        # A fresh WorkLedger handle over the same repo_root stands in for
        # "a fresh reader with no memory of the creating session."
        fresh = work_ledger.WorkLedger(self.repo_root)
        listed = {item.id: item for item in fresh.list_work_items()}
        self.assertEqual(set(listed), {"WI-1", "WI-2", "WI-3"})
        for item_id in ("WI-1", "WI-2", "WI-3"):
            self.assertEqual(listed[item_id].status, "open")
            self.assertEqual(
                listed[item_id].source_locator,
                "specs/001-durable-work-ledger/plan.md",
            )

        # -- Scenario 2: availability, including across archival --------
        # (User Story 2)
        self.ledger.add_blocked_by("WI-2", "WI-1")

        self.assertFalse(self.ledger.is_blocked("WI-1"))
        self.assertTrue(self.ledger.is_blocked("WI-2"))
        self.assertFalse(self.ledger.is_blocked("WI-3"))

        available = set(self.ledger.list_available_work_items())
        self.assertEqual(available, {"WI-1", "WI-3"})

        self.assertTrue(self.ledger.mark_done("WI-1"))
        self.assertFalse(self.ledger.is_blocked("WI-2"))
        self.assertIn("WI-2", self.ledger.list_available_work_items())

        # Archiving the now-satisfied prerequisite must not change the
        # answer (SC-008) — resolved via the same single-table lookup,
        # whether WI-1's row is active or thinned.
        self.assertTrue(self.ledger.archive_work_item("WI-1"))
        self.assertFalse(self.ledger.is_blocked("WI-2"))
        self.assertIn("WI-2", self.ledger.list_available_work_items())

        # A dangling blocker (a typo'd id that never validly identified a
        # work item) is only reachable, in the normal write path, via a
        # connection that ran without foreign keys enabled — the
        # misconfiguration research.md itself names as the practical
        # trigger. Confirm it is reported distinctly from WI-1's
        # thinned-but-resolvable, satisfied case above (SC-009).
        conn = work_ledger.connect(self.repo_root)
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                "INSERT INTO work_item_blocked_by (work_item_id, blocked_on_id) "
                "VALUES ('WI-2', 'WI-0-never-existed')"
            )
        finally:
            conn.close()

        self.assertTrue(self.ledger.is_blocked("WI-2"))  # dangling -> still blocking
        findings = self.ledger.reconcile()
        dangling = [f for f in findings if f.finding == "dangling_blocker"]
        self.assertEqual([f.item_id for f in dangling], ["WI-2"])
        self.assertIn("WI-0-never-existed", dangling[0].detail)
        # WI-1's satisfied, archived dependency must not itself be
        # reported dangling.
        self.assertNotIn("WI-1", [f.item_id for f in findings if f.finding == "dangling_blocker"])

        # -- Scenario 3: claim across worktrees; detect and recover a ---
        # -- stale claim (User Story 3) ----------------------------------
        self.ledger.create_work_item(
            id="WI-4", title="Task A", source_kind="adhoc", source_locator="adhoc-a"
        )
        self.ledger.create_work_item(
            id="WI-5", title="Task B", source_kind="adhoc", source_locator="adhoc-b"
        )

        worktree_a = tempfile.mkdtemp()
        worktree_b = tempfile.mkdtemp()
        self.addCleanup(lambda: os.path.isdir(worktree_b) and os.rmdir(worktree_b))

        self.assertTrue(
            self.ledger.claim("WI-4", "agent-A", worktree_path=worktree_a)
        )
        self.assertTrue(
            self.ledger.claim("WI-5", "agent-B", worktree_path=worktree_b)
        )

        conn = work_ledger.connect(self.repo_root)
        try:
            rows = {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT work_item_id, owner FROM work_item_claims"
                ).fetchall()
            }
        finally:
            conn.close()
        self.assertEqual(rows, {"WI-4": "agent-A", "WI-5": "agent-B"})

        # Worktree A disappears without releasing its claim; worktree B
        # remains, so WI-5's claim must NOT be reported stale.
        os.rmdir(worktree_a)

        findings = self.ledger.reconcile()
        stale = [f for f in findings if f.finding == "stale_claim"]
        self.assertEqual([f.item_id for f in stale], ["WI-4"])
        # Reconciliation must not mutate the claim or the item's
        # computed availability.
        self.assertNotIn("WI-4", self.ledger.list_available_work_items())

        # Explicit recovery: override-release on the stale-claim
        # evidence, then a fresh, ordinary claim attempt.
        self.ledger.override_release_claim("WI-4", note="worktree deleted")
        conn = work_ledger.connect(self.repo_root)
        try:
            leftover = conn.execute(
                "SELECT * FROM work_item_claims WHERE work_item_id = 'WI-4'"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNone(leftover)  # override does not itself grant a claim
        self.assertTrue(self.ledger.claim("WI-4", "agent-C"))

        # An Evidence Pointer remains a historical observation, unaffected
        # by anything that happens to the branch it names afterward.
        self.ledger.add_evidence("WI-5", "branch", "agent-b-wi5")
        conn = work_ledger.connect(self.repo_root)
        try:
            evidence = conn.execute(
                "SELECT kind, value FROM work_item_evidence WHERE work_item_id = 'WI-5'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(evidence, ("branch", "agent-b-wi5"))

        # -- Scenario 4: concurrent claim race on the same item ----------
        # (User Story 3, FR-018)
        self.ledger.create_work_item(
            id="WI-6", title="Task C", source_kind="adhoc", source_locator="adhoc-c"
        )
        self.assertTrue(self.ledger.claim("WI-6", "agent-D"))
        self.assertFalse(self.ledger.claim("WI-6", "agent-E"))
        self.assertFalse(self.ledger.claim("WI-6", "agent-F"))

        # -- Scenario 5: generate a coordinator projection ---------------
        # (User Story 4)
        self.ledger.create_work_item(
            id="WI-7", title="Blocker", source_kind="adhoc", source_locator="adhoc-g"
        )
        self.ledger.create_work_item(
            id="WI-8",
            title="Blocked",
            source_kind="adhoc",
            source_locator="adhoc-h",
            blocked_by=["WI-7"],
        )

        conn = work_ledger.connect(self.repo_root)
        try:
            before = conn.execute("SELECT * FROM work_items ORDER BY id").fetchall()
        finally:
            conn.close()

        first_projection = self.ledger.generate_projection()
        by_id = {item.id: item for item in first_projection}
        self.assertTrue(by_id["WI-7"].eligible)
        self.assertFalse(by_id["WI-8"].eligible)
        self.assertFalse(by_id["WI-8"].terminal)
        # WI-4's claim (Scenario 3) also withholds eligibility.
        self.assertFalse(by_id["WI-4"].eligible)
        # WI-1, archived in Scenario 2, is not part of the projection at
        # all (archived items are a permanent tombstone, not a
        # coordinator-facing item).
        self.assertNotIn("WI-1", by_id)

        second_projection = self.ledger.generate_projection()
        self.assertEqual(first_projection, second_projection)

        # Generating a projection (twice) performed no write to the
        # ledger's own durable state.
        conn = work_ledger.connect(self.repo_root)
        try:
            after = conn.execute("SELECT * FROM work_items ORDER BY id").fetchall()
        finally:
            conn.close()
        self.assertEqual(before, after)

        # Every coordination fact used throughout this test (creation,
        # blocking, archival, claim, reconciliation, evidence) was
        # determined entirely without this projection step ever having
        # run until this final scenario — confirming User Story 4's own
        # Acceptance Scenario 3.
        self.assertEqual(self.ledger.get_work_item("WI-6").status, "open")
        self.assertTrue(self.ledger.is_claimed("WI-6"))


# ============================================================================
# specs/002-milestone-task-work-items: milestone/task work-item model.
# ============================================================================

# The exact version-1 schema (specs/001-durable-work-ledger/data-model.md),
# frozen here verbatim so TestSchemaMigrationV1ToV2 can construct a real
# pre-migration database independent of whatever work_ledger._SCHEMA_STATEMENTS
# currently contains.
_V1_WORK_ITEMS_SQL = """
CREATE TABLE work_items (
  id                TEXT PRIMARY KEY,
  title             TEXT,
  status            TEXT NOT NULL CHECK (status IN ('open', 'done', 'superseded')),
  superseded_by     TEXT REFERENCES work_items(id),
  source_kind       TEXT CHECK (source_kind IN ('speckit_task', 'plan', 'adhoc')),
  source_locator    TEXT,
  source_promoted_by TEXT,
  created_at        TEXT,
  updated_at        TEXT NOT NULL,
  archived_at       TEXT,
  CHECK (
    (status = 'superseded' AND superseded_by IS NOT NULL) OR
    (status != 'superseded' AND superseded_by IS NULL)
  )
)
"""

_V1_OTHER_TABLES_SQL = (
    """
    CREATE TABLE work_item_blocked_by (
      work_item_id      TEXT NOT NULL REFERENCES work_items(id),
      blocked_on_id     TEXT NOT NULL REFERENCES work_items(id),
      PRIMARY KEY (work_item_id, blocked_on_id),
      CHECK (work_item_id != blocked_on_id)
    )
    """,
    """
    CREATE TABLE work_item_claims (
      work_item_id      TEXT PRIMARY KEY REFERENCES work_items(id),
      owner             TEXT NOT NULL,
      claimed_at        TEXT NOT NULL,
      worktree_path     TEXT,
      branch            TEXT
    )
    """,
    """
    CREATE TABLE work_item_evidence (
      evidence_id       INTEGER PRIMARY KEY,
      work_item_id      TEXT NOT NULL REFERENCES work_items(id),
      kind              TEXT NOT NULL CHECK (kind IN ('branch', 'commit', 'pull_request', 'other')),
      value             TEXT NOT NULL,
      recorded_at       TEXT NOT NULL,
      note              TEXT
    )
    """,
)


class TestSchemaMigrationV1ToV2(LedgerTestCase):
    """T005: an existing version-1 database migrates forward to v2
    automatically and safely (research.md's "Decision: schema migration
    from version 1 to version 2")."""

    def _create_v1_database(self, rows=()):
        db_path = work_ledger.ledger_path(self.repo_root)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(_V1_WORK_ITEMS_SQL)
            for statement in _V1_OTHER_TABLES_SQL:
                conn.execute(statement)
            for row_id in rows:
                conn.execute(
                    "INSERT INTO work_items "
                    "(id, title, status, source_kind, source_locator, created_at, updated_at) "
                    "VALUES (?, ?, 'open', 'adhoc', ?, ?, ?)",
                    (row_id, f"Item {row_id}", f"loc-{row_id}", _NOW, _NOW),
                )
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
        finally:
            conn.close()

    def test_existing_v1_database_migrates_to_v2_on_open(self):
        self._create_v1_database(rows=["WI-1", "WI-2"])

        conn = work_ledger.connect(self.repo_root)
        try:
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0],
                work_ledger._SCHEMA_VERSION,
            )
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(work_items)").fetchall()
            }
            self.assertTrue({"type", "parent_id", "description"} <= cols)
        finally:
            conn.close()

    def test_v1_rows_are_backfilled_as_type_task_with_no_parent(self):
        self._create_v1_database(rows=["WI-1"])

        item = work_ledger.WorkLedger(self.repo_root).get_work_item("WI-1")
        self.assertEqual(item.type, "task")
        self.assertIsNone(item.parent_id)
        self.assertEqual(item.status, "open")
        self.assertEqual(item.title, "Item WI-1")

    def test_compound_check_is_enforced_after_migration(self):
        self._create_v1_database()
        conn = work_ledger.connect(self.repo_root)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO work_items (id, type, status, updated_at) "
                    "VALUES (?, 'milestone', 'done', ?)",
                    ("M-bad", _NOW),
                )
        finally:
            conn.close()

    def test_migration_crash_mid_rebuild_leaves_v1_database_intact(self):
        self._create_v1_database(rows=["WI-1"])

        real_create_sql = work_ledger._work_items_create_sql

        def broken(table_name):
            if table_name == "work_items_new":
                return "CREATE TABLE this is not valid sql"
            return real_create_sql(table_name)

        work_ledger._work_items_create_sql = broken
        try:
            with self.assertRaises(sqlite3.OperationalError):
                work_ledger.connect(self.repo_root)
        finally:
            work_ledger._work_items_create_sql = real_create_sql

        # Inspect on a raw connection, bypassing work_ledger.connect
        # entirely, so this inspection does not re-trigger the fault.
        raw_conn = sqlite3.connect(work_ledger.ledger_path(self.repo_root))
        try:
            self.assertEqual(raw_conn.execute("PRAGMA user_version").fetchone()[0], 1)
            cols = {
                row[1]
                for row in raw_conn.execute("PRAGMA table_info(work_items)").fetchall()
            }
            self.assertNotIn("type", cols)
            row = raw_conn.execute(
                "SELECT id FROM work_items WHERE id = 'WI-1'"
            ).fetchone()
            self.assertEqual(row[0], "WI-1")
        finally:
            raw_conn.close()

        # A subsequent, ordinary open (fault removed) migrates fully.
        conn = work_ledger.connect(self.repo_root)
        try:
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0],
                work_ledger._SCHEMA_VERSION,
            )
        finally:
            conn.close()
        item = work_ledger.WorkLedger(self.repo_root).get_work_item("WI-1")
        self.assertEqual(item.type, "task")


class TestWorkItemTypeAndParent(LedgerTestCase):
    """T006: type immutability (no mutator exists), parent_id creation
    validation (FR-002/FR-003), and type-aware blocking resolution across
    every type combination."""

    def test_type_has_no_mutator_in_the_public_api(self):
        public_methods = [
            name
            for name in dir(work_ledger.WorkLedger)
            if not name.startswith("_")
            and callable(getattr(work_ledger.WorkLedger, name))
        ]
        for name in public_methods:
            if name == "create_work_item":
                continue
            params = inspect.signature(getattr(work_ledger.WorkLedger, name)).parameters
            self.assertNotIn("type", params, f"{name} must not accept a type parameter")

    def test_task_with_nonexistent_parent_is_rejected_atomically(self):
        with self.assertRaises(ValueError):
            self.ledger.create_work_item(
                id="T-1",
                title="Task",
                source_kind="adhoc",
                source_locator="x",
                parent_id="does-not-exist",
            )
        self.assertIsNone(self.ledger.get_work_item("T-1"))

    def test_task_with_task_typed_parent_is_rejected_atomically(self):
        self.ledger.create_work_item(
            id="T-parent", title="P", source_kind="adhoc", source_locator="x"
        )
        with self.assertRaises(ValueError):
            self.ledger.create_work_item(
                id="T-child",
                title="C",
                source_kind="adhoc",
                source_locator="y",
                parent_id="T-parent",
            )
        self.assertIsNone(self.ledger.get_work_item("T-child"))

    def test_task_with_valid_milestone_parent_is_created(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.ledger.create_work_item(
            id="T-1",
            title="T",
            source_kind="adhoc",
            source_locator="y",
            parent_id="M-1",
        )
        item = self.ledger.get_work_item("T-1")
        self.assertEqual(item.type, "task")
        self.assertEqual(item.parent_id, "M-1")

    def test_milestone_with_parent_id_is_rejected_by_schema_check(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.create_work_item(
                id="M-2",
                title="M2",
                source_kind="adhoc",
                source_locator="y",
                type="milestone",
                parent_id="M-1",
            )

    def test_mark_done_on_a_milestone_violates_the_compound_check(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.mark_done("M-1")
        self.assertEqual(self.ledger.get_work_item("M-1").status, "open")

    def test_type_aware_blocking_resolution_task_on_milestone(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.ledger.create_work_item(
            id="T-1",
            title="T",
            source_kind="adhoc",
            source_locator="y",
            blocked_by=["M-1"],
        )
        self.assertTrue(self.ledger.is_blocked("T-1"))

        # Force M-1 to its terminal state directly, isolating resolution
        # semantics from review-readiness/transition mechanics (mirroring
        # 001's own T022 direct-fixture-construction precedent).
        conn = work_ledger.connect(self.repo_root)
        try:
            conn.execute("UPDATE work_items SET status = 'accepted' WHERE id = 'M-1'")
        finally:
            conn.close()
        self.assertFalse(self.ledger.is_blocked("T-1"))

    def test_type_aware_blocking_resolution_milestone_on_task(self):
        self.ledger.create_work_item(
            id="T-1", title="T", source_kind="adhoc", source_locator="x"
        )
        self.ledger.create_work_item(
            id="M-1",
            title="M",
            source_kind="adhoc",
            source_locator="y",
            type="milestone",
            blocked_by=["T-1"],
        )
        self.assertTrue(self.ledger.is_blocked("M-1"))
        self.assertTrue(self.ledger.mark_done("T-1"))
        self.assertFalse(self.ledger.is_blocked("M-1"))

    def test_milestone_review_state_does_not_resolve_a_dependent(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.ledger.create_work_item(
            id="T-1",
            title="T",
            source_kind="adhoc",
            source_locator="y",
            blocked_by=["M-1"],
        )
        conn = work_ledger.connect(self.repo_root)
        try:
            conn.execute("UPDATE work_items SET status = 'review' WHERE id = 'M-1'")
        finally:
            conn.close()
        self.assertTrue(self.ledger.is_blocked("T-1"))


class TestMilestoneTaskAttribution(LedgerTestCase):
    """T007 (User Story 1): a milestone and its attributed tasks survive
    a fresh ledger handle, and every 001-defined behavior (claim,
    evidence) works identically against a milestone row."""

    def test_attribution_survives_a_fresh_ledger_handle(self):
        self.ledger.create_work_item(
            id="M-1",
            title="Ship the thing",
            source_kind="plan",
            source_locator="plans/x",
            type="milestone",
        )
        self.ledger.create_work_item(
            id="T-1",
            title="Do part 1",
            source_kind="plan",
            source_locator="plans/x#1",
            parent_id="M-1",
        )
        self.ledger.create_work_item(
            id="T-2",
            title="Do part 2",
            source_kind="plan",
            source_locator="plans/x#2",
            parent_id="M-1",
        )

        fresh = work_ledger.WorkLedger(self.repo_root)
        m1 = fresh.get_work_item("M-1")
        t1 = fresh.get_work_item("T-1")
        t2 = fresh.get_work_item("T-2")
        self.assertEqual(m1.type, "milestone")
        self.assertIsNone(m1.parent_id)
        self.assertEqual(t1.parent_id, "M-1")
        self.assertEqual(t2.parent_id, "M-1")

    def test_001_behaviors_work_identically_against_a_milestone_row(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )

        self.assertTrue(self.ledger.claim("M-1", "reviewer-1"))
        self.assertFalse(self.ledger.claim("M-1", "reviewer-2"))
        self.assertTrue(self.ledger.is_claimed("M-1"))

        self.ledger.add_evidence("M-1", "other", "decision-record-link")
        conn = work_ledger.connect(self.repo_root)
        try:
            evidence = conn.execute(
                "SELECT kind, value FROM work_item_evidence WHERE work_item_id = 'M-1'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(evidence, ("other", "decision-record-link"))

        self.ledger.release_claim("M-1", "reviewer-1")
        self.assertFalse(self.ledger.is_claimed("M-1"))


class TestQualifyingMechanicalEvidence(LedgerTestCase):
    """T009 (User Story 2): has_qualifying_evidence is a pure, read-only
    derived predicate; mark_done's own behavior/signature is unchanged
    from 001."""

    def test_done_task_without_evidence_does_not_qualify(self):
        self.ledger.create_work_item(
            id="T-1", title="T", source_kind="adhoc", source_locator="x"
        )
        self.assertTrue(self.ledger.mark_done("T-1"))
        self.assertFalse(self.ledger.has_qualifying_evidence("T-1"))

    def test_done_task_with_any_evidence_kind_qualifies(self):
        for kind, value in (
            ("branch", "b"),
            ("commit", "c"),
            ("pull_request", "p"),
            ("other", "o"),
        ):
            with self.subTest(kind=kind):
                item_id = f"T-{kind}"
                self.ledger.create_work_item(
                    id=item_id, title="T", source_kind="adhoc", source_locator="x"
                )
                self.assertFalse(self.ledger.has_qualifying_evidence(item_id))
                self.ledger.add_evidence(item_id, kind, value)
                self.assertTrue(self.ledger.has_qualifying_evidence(item_id))

    def test_evidence_recorded_before_done_and_mark_done_is_unaffected(self):
        self.ledger.create_work_item(
            id="T-1", title="T", source_kind="adhoc", source_locator="x"
        )
        self.ledger.add_evidence("T-1", "commit", "abc123")
        self.assertTrue(self.ledger.mark_done("T-1"))
        self.assertTrue(self.ledger.has_qualifying_evidence("T-1"))


class TestMilestoneReviewReadiness(LedgerTestCase):
    """T012 (User Story 3): is_review_ready is correct across
    child-state combinations (SC-002); mark_in_review is a guarded,
    single-winner transition (SC-003); claim() works against a milestone
    with no code changes needed."""

    def _milestone_with_children(self, n):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        for i in range(n):
            self.ledger.create_work_item(
                id=f"T-{i}",
                title=f"T{i}",
                source_kind="adhoc",
                source_locator=f"y{i}",
                parent_id="M-1",
            )
        return [f"T-{i}" for i in range(n)]

    def test_empty_milestone_is_never_review_ready(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.assertFalse(self.ledger.is_review_ready("M-1"))

    def test_review_ready_requires_every_child_resolved_and_evidenced(self):
        children = self._milestone_with_children(2)
        self.assertFalse(self.ledger.is_review_ready("M-1"))

        self.assertTrue(self.ledger.mark_done(children[0]))
        self.assertFalse(self.ledger.is_review_ready("M-1"))

        self.ledger.add_evidence(children[0], "commit", "abc")
        self.assertFalse(self.ledger.is_review_ready("M-1"))

        self.assertTrue(self.ledger.mark_done(children[1]))
        self.ledger.add_evidence(children[1], "branch", "feature/x")
        self.assertTrue(self.ledger.is_review_ready("M-1"))

    def test_superseded_child_counts_as_resolved_without_evidence(self):
        children = self._milestone_with_children(2)
        self.assertTrue(self.ledger.mark_done(children[0]))
        self.ledger.add_evidence(children[0], "commit", "abc")
        self.assertTrue(self.ledger.mark_superseded(children[1], children[0]))
        self.assertTrue(self.ledger.is_review_ready("M-1"))

    def test_five_children_all_resolved_and_evidenced_is_ready(self):
        children = self._milestone_with_children(5)
        for child in children[:4]:
            self.assertTrue(self.ledger.mark_done(child))
            self.ledger.add_evidence(child, "commit", f"sha-{child}")
        self.assertFalse(self.ledger.is_review_ready("M-1"))

        self.assertTrue(self.ledger.mark_done(children[4]))
        self.ledger.add_evidence(children[4], "commit", "sha-last")
        self.assertTrue(self.ledger.is_review_ready("M-1"))

    def test_blocked_milestone_is_not_review_ready_even_with_resolved_children(self):
        self.ledger.create_work_item(
            id="Blocker", title="B", source_kind="adhoc", source_locator="z"
        )
        children = self._milestone_with_children(1)
        self.ledger.add_blocked_by("M-1", "Blocker")
        self.assertTrue(self.ledger.mark_done(children[0]))
        self.ledger.add_evidence(children[0], "commit", "abc")
        self.assertFalse(self.ledger.is_review_ready("M-1"))

        self.assertTrue(self.ledger.mark_done("Blocker"))
        self.assertTrue(self.ledger.is_review_ready("M-1"))

    def test_mark_in_review_succeeds_only_when_ready_and_open(self):
        children = self._milestone_with_children(1)
        self.assertFalse(self.ledger.mark_in_review("M-1"))

        self.assertTrue(self.ledger.mark_done(children[0]))
        self.ledger.add_evidence(children[0], "commit", "abc")
        self.assertTrue(self.ledger.is_review_ready("M-1"))
        self.assertTrue(self.ledger.mark_in_review("M-1"))
        self.assertEqual(self.ledger.get_work_item("M-1").status, "review")

        self.assertFalse(self.ledger.mark_in_review("M-1"))

    def test_concurrent_mark_in_review_has_exactly_one_winner(self):
        children = self._milestone_with_children(1)
        self.assertTrue(self.ledger.mark_done(children[0]))
        self.ledger.add_evidence(children[0], "commit", "abc")

        results = []

        def attempt():
            results.append(self.ledger.mark_in_review("M-1"))

        threads = [threading.Thread(target=attempt) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sum(1 for r in results if r), 1)
        self.assertEqual(self.ledger.get_work_item("M-1").status, "review")

    def test_claim_works_against_a_milestone_in_review(self):
        children = self._milestone_with_children(1)
        self.assertTrue(self.ledger.mark_done(children[0]))
        self.ledger.add_evidence(children[0], "commit", "abc")
        self.assertTrue(self.ledger.mark_in_review("M-1"))

        self.assertTrue(self.ledger.claim("M-1", "reviewer-1"))
        self.assertFalse(self.ledger.claim("M-1", "reviewer-2"))


class TestMilestoneDeclineAndAccept(LedgerTestCase):
    """T014 (User Story 4): decline_review/accept_milestone are guarded
    transitions; declining never mutates a child task's record; a new
    corrective task is accepted normally and readiness recomputes."""

    def _ready_milestone(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.ledger.create_work_item(
            id="T-1",
            title="T1",
            source_kind="adhoc",
            source_locator="y",
            parent_id="M-1",
        )
        self.assertTrue(self.ledger.mark_done("T-1"))
        self.ledger.add_evidence("T-1", "commit", "abc")
        self.assertTrue(self.ledger.mark_in_review("M-1"))

    def test_decline_review_leaves_child_records_byte_identical(self):
        self._ready_milestone()
        before = self.ledger.get_work_item("T-1")

        self.assertTrue(self.ledger.decline_review("M-1"))
        self.assertEqual(self.ledger.get_work_item("M-1").status, "open")

        after = self.ledger.get_work_item("T-1")
        self.assertEqual(before, after)

    def test_corrective_task_recomputes_readiness(self):
        self._ready_milestone()
        self.assertTrue(self.ledger.decline_review("M-1"))

        self.ledger.create_work_item(
            id="T-2",
            title="Fix flagged issue",
            source_kind="adhoc",
            source_locator="z",
            parent_id="M-1",
        )
        self.assertFalse(self.ledger.is_review_ready("M-1"))

        self.assertTrue(self.ledger.mark_done("T-2"))
        self.ledger.add_evidence("T-2", "commit", "def")
        self.assertTrue(self.ledger.is_review_ready("M-1"))
        self.assertTrue(self.ledger.mark_in_review("M-1"))

    def test_accept_milestone_fails_when_not_in_review(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.assertFalse(self.ledger.accept_milestone("M-1"))
        self.assertEqual(self.ledger.get_work_item("M-1").status, "open")

    def test_accept_milestone_transitions_review_to_accepted(self):
        self._ready_milestone()
        self.assertTrue(self.ledger.accept_milestone("M-1"))
        self.assertEqual(self.ledger.get_work_item("M-1").status, "accepted")
        self.assertFalse(self.ledger.accept_milestone("M-1"))

    def test_no_public_method_accepts_rationale_text(self):
        for name in ("decline_review", "accept_milestone", "mark_in_review"):
            params = inspect.signature(getattr(work_ledger.WorkLedger, name)).parameters
            self.assertNotIn("rationale", params)
            self.assertNotIn("reason", params)


class TestMilestoneMembershipFreeze(LedgerTestCase):
    """FR-003a: a task may be attached to a milestone (via `parent_id` at
    creation) only while that milestone is `status='open'`. Membership is
    frozen the instant a milestone leaves `open` — `review`, `accepted`,
    and `superseded` all reject a new attach attempt outright, with no
    partial row written — while the corrective-work flow (`review` ->
    `decline_review` -> `open` -> attach -> `review` again) keeps working
    exactly as FR-011 already establishes. The parent's existence/type/
    status check and the child `INSERT` are atomic with respect to a
    concurrent milestone lifecycle transition."""

    def _milestone_ready_for_review(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.ledger.create_work_item(
            id="T-1", title="T1", source_kind="adhoc", source_locator="y", parent_id="M-1"
        )
        self.assertTrue(self.ledger.mark_done("T-1"))
        self.ledger.add_evidence("T-1", "commit", "abc")

    def _assert_attach_rejected(self, item_id="T-race"):
        with self.assertRaises(ValueError):
            self.ledger.create_work_item(
                id=item_id,
                title="Racer",
                source_kind="adhoc",
                source_locator=item_id,
                parent_id="M-1",
            )
        self.assertIsNone(self.ledger.get_work_item(item_id))

    def test_task_may_be_attached_while_milestone_is_open(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.ledger.create_work_item(
            id="T-1", title="T", source_kind="adhoc", source_locator="y", parent_id="M-1"
        )
        self.assertEqual(self.ledger.get_work_item("T-1").parent_id, "M-1")

    def test_task_may_not_be_attached_while_milestone_in_review(self):
        self._milestone_ready_for_review()
        self.assertTrue(self.ledger.mark_in_review("M-1"))
        self._assert_attach_rejected()

    def test_task_may_not_be_attached_after_accepted(self):
        self._milestone_ready_for_review()
        self.assertTrue(self.ledger.mark_in_review("M-1"))
        self.assertTrue(self.ledger.accept_milestone("M-1"))
        self._assert_attach_rejected()

    def test_task_may_not_be_attached_after_superseded(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.ledger.create_work_item(
            id="M-2", title="M2", source_kind="adhoc", source_locator="y", type="milestone"
        )
        self.assertTrue(self.ledger.mark_superseded("M-1", "M-2"))
        self._assert_attach_rejected()

    def test_task_may_not_be_attached_after_archival(self):
        self._milestone_ready_for_review()
        self.assertTrue(self.ledger.mark_in_review("M-1"))
        self.assertTrue(self.ledger.accept_milestone("M-1"))
        self.assertTrue(self.ledger.archive_work_item("M-1"))
        self._assert_attach_rejected()

    def test_corrective_task_may_be_attached_after_decline_review(self):
        self._milestone_ready_for_review()
        self.assertTrue(self.ledger.mark_in_review("M-1"))
        self.assertTrue(self.ledger.decline_review("M-1"))

        self.ledger.create_work_item(
            id="T-2", title="Fix", source_kind="adhoc", source_locator="z", parent_id="M-1"
        )
        self.assertEqual(self.ledger.get_work_item("T-2").parent_id, "M-1")

    def test_concurrent_mark_in_review_vs_task_attach_never_produces_invalid_membership(
        self,
    ):
        """A milestone that is review-ready right now (one resolved,
        evidenced child) races two operations against each other: moving
        it into `review`, and attaching a fresh, unresolved task to it.
        Whichever operation's write commits first must determine the
        other's outcome correctly — never both succeeding (a milestone in
        `review` with a brand-new unresolved child underneath it) and
        never both failing (a live application bug, not a race)."""
        self._milestone_ready_for_review()

        barrier = threading.Barrier(2)
        results = {}

        def do_mark_in_review():
            barrier.wait()
            results["mark_in_review"] = self.ledger.mark_in_review("M-1")

        def do_attach():
            barrier.wait()
            try:
                self.ledger.create_work_item(
                    id="T-race",
                    title="Racer",
                    source_kind="adhoc",
                    source_locator="race",
                    parent_id="M-1",
                )
                results["attach"] = True
            except ValueError:
                results["attach"] = False

        t1 = threading.Thread(target=do_mark_in_review)
        t2 = threading.Thread(target=do_attach)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertIn("mark_in_review", results)
        self.assertIn("attach", results)
        self.assertFalse(
            results["mark_in_review"] and results["attach"],
            "a milestone must never enter review while a concurrently "
            "attached, unresolved task lands on it",
        )
        self.assertTrue(
            results["mark_in_review"] or results["attach"],
            "at least one of the two non-conflicting operations must succeed",
        )

        milestone = self.ledger.get_work_item("M-1")
        t_race = self.ledger.get_work_item("T-race")
        if results["attach"]:
            self.assertIsNotNone(t_race)
            self.assertEqual(t_race.status, "open")
            self.assertNotEqual(milestone.status, "review")
        else:
            self.assertIsNone(t_race)
            self.assertEqual(milestone.status, "review")


class TestProjectionExcludesMilestones(LedgerTestCase):
    """T017 (User Story 5, SC-005): no milestone row ever appears in a
    generated projection, under any status/claim combination; a task
    blocked by a milestone is projected as ineligible while the
    milestone itself never appears."""

    def test_no_milestone_appears_in_projection_open_or_superseded(self):
        self.ledger.create_work_item(
            id="M-open", title="M", source_kind="adhoc", source_locator="o", type="milestone"
        )
        self.ledger.create_work_item(
            id="M-other", title="M", source_kind="adhoc", source_locator="p", type="milestone"
        )
        self.assertTrue(self.ledger.mark_superseded("M-other", "M-open"))

        by_id = {p.id for p in self.ledger.generate_projection()}
        self.assertNotIn("M-open", by_id)
        self.assertNotIn("M-other", by_id)

    def test_no_milestone_appears_in_projection_review_or_accepted(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.ledger.create_work_item(
            id="T-1", title="T", source_kind="adhoc", source_locator="y", parent_id="M-1"
        )
        self.assertTrue(self.ledger.mark_done("T-1"))
        self.ledger.add_evidence("T-1", "commit", "abc")
        self.assertTrue(self.ledger.mark_in_review("M-1"))

        by_id = {p.id for p in self.ledger.generate_projection()}
        self.assertNotIn("M-1", by_id)

        self.assertTrue(self.ledger.accept_milestone("M-1"))
        by_id = {p.id for p in self.ledger.generate_projection()}
        self.assertNotIn("M-1", by_id)

    def test_claimed_milestone_still_excluded(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.assertTrue(self.ledger.claim("M-1", "reviewer"))
        by_id = {p.id for p in self.ledger.generate_projection()}
        self.assertNotIn("M-1", by_id)

    def test_task_blocked_by_milestone_is_projected_ineligible_milestone_absent(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.ledger.create_work_item(
            id="T-1",
            title="T",
            source_kind="adhoc",
            source_locator="y",
            blocked_by=["M-1"],
        )

        by_id = {p.id: p for p in self.ledger.generate_projection()}
        self.assertNotIn("M-1", by_id)
        self.assertIn("T-1", by_id)
        self.assertFalse(by_id["T-1"].eligible)

    def test_projection_determinism_unchanged_with_milestones_present(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.ledger.create_work_item(
            id="T-1", title="T", source_kind="adhoc", source_locator="y", parent_id="M-1"
        )
        first = self.ledger.generate_projection()
        second = self.ledger.generate_projection()
        self.assertEqual(first, second)


class TestAvailableWorkItemsExcludesMilestones(LedgerTestCase):
    """FR-017a: `list_available_work_items()` reports only `type='task'`
    rows — a milestone is a human acceptance unit, never a startable unit
    of work, so an open/unclaimed/unblocked milestone must never appear,
    mirroring `generate_projection()`'s own `type='task'` filter."""

    def test_open_unclaimed_unblocked_milestone_is_never_available(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.assertNotIn("M-1", self.ledger.list_available_work_items())

    def test_task_remains_available_alongside_an_available_looking_milestone(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.ledger.create_work_item(
            id="T-1", title="T", source_kind="adhoc", source_locator="y", parent_id="M-1"
        )
        available = self.ledger.list_available_work_items()
        self.assertIn("T-1", available)
        self.assertNotIn("M-1", available)


class TestMilestoneArchival(LedgerTestCase):
    """T017 (SC-006/SC-007): archiving a milestone with an unresolved
    child is refused and leaves the row untouched; archiving succeeds
    once every child is resolved; a child's parent_id still resolves the
    archived milestone's surviving type/status afterward."""

    def _accepted_milestone_with_one_child(self):
        self.ledger.create_work_item(
            id="M-1", title="M", source_kind="adhoc", source_locator="x", type="milestone"
        )
        self.ledger.create_work_item(
            id="T-1", title="T", source_kind="adhoc", source_locator="y", parent_id="M-1"
        )
        self.assertTrue(self.ledger.mark_done("T-1"))
        self.ledger.add_evidence("T-1", "commit", "abc")
        self.assertTrue(self.ledger.mark_in_review("M-1"))
        self.assertTrue(self.ledger.accept_milestone("M-1"))

    def test_archiving_milestone_with_unresolved_child_is_refused(self):
        self._accepted_milestone_with_one_child()

        # FR-003a forbids attaching a task to an already-accepted milestone
        # through the public API (see TestMilestoneMembershipFreeze) — by
        # the time a milestone reaches `accepted`, every child present at
        # that moment is already resolved by construction (mark_in_review's
        # own review-readiness precondition), and no operation can un-
        # resolve a task or attach a new one afterward. FR-015's archival
        # precondition is therefore defense-in-depth against a state the
        # normal API can no longer produce; constructing it here requires
        # a direct raw-SQL insert bypassing `create_work_item()`'s own
        # validation entirely, isolating archival's own precondition
        # enforcement from creation-time enforcement (mirroring this
        # module's existing "direct-fixture construction" precedent, e.g.
        # `TestWorkItemTypeAndParent.test_type_aware_blocking_resolution_task_on_milestone`).
        conn = work_ledger.connect(self.repo_root)
        try:
            conn.execute(
                "INSERT INTO work_items "
                "(id, type, parent_id, title, status, created_at, updated_at) "
                "VALUES ('T-2', 'task', 'M-1', 'T2', 'open', ?, ?)",
                (_NOW, _NOW),
            )
        finally:
            conn.close()
        before = self.ledger.get_work_item("M-1")

        self.assertFalse(self.ledger.archive_work_item("M-1"))
        after = self.ledger.get_work_item("M-1")
        self.assertEqual(before, after)

    def test_archiving_succeeds_once_every_child_resolved(self):
        self._accepted_milestone_with_one_child()

        self.assertTrue(self.ledger.archive_work_item("M-1"))
        item = self.ledger.get_work_item("M-1")
        self.assertEqual(item.status, "accepted")
        self.assertIsNotNone(item.archived_at)
        self.assertIsNone(item.title)
        self.assertIsNone(item.description)

    def test_child_parent_id_resolves_archived_milestones_surviving_type_and_status(
        self,
    ):
        self._accepted_milestone_with_one_child()
        self.assertTrue(self.ledger.archive_work_item("M-1"))

        t1 = self.ledger.get_work_item("T-1")
        self.assertEqual(t1.parent_id, "M-1")

        parent = self.ledger.get_work_item("M-1")
        self.assertEqual(parent.type, "milestone")
        self.assertEqual(parent.status, "accepted")

        self.ledger.create_work_item(
            id="T-2",
            title="T2",
            source_kind="adhoc",
            source_locator="z",
            blocked_by=["M-1"],
        )
        self.assertFalse(self.ledger.is_blocked("T-2"))

    def test_archival_precondition_is_atomic_against_a_concurrent_child_insertion(self):
        """Regression for the archival check-then-act race: pre-fix,
        `archive_work_item()` evaluated "any unresolved child?" as a plain
        `SELECT` *before* opening its own transaction, then archived in a
        separate later transaction. That left a window in which a
        concurrent writer could insert a new open child between the check
        and the mutation, producing an archived milestone with live,
        unresolved child work underneath it.

        Constructed with a second, raw connection under direct manual
        transaction control so the interleaving this regression targets is
        forced deterministically rather than left to scheduler luck: a
        `BEGIN IMMEDIATE` transaction that inserts a fresh open child under
        M-1 is opened and left uncommitted *before* `archive_work_item()`
        is ever invoked, on the same milestone this test's own fixture
        just confirmed has zero unresolved children. `archive_work_item()`
        is then run concurrently on a separate thread — its own
        `BEGIN IMMEDIATE` can only proceed once the held write lock is
        released (SQLite serializes writers), so its resolved-children
        precondition is necessarily evaluated against the *post-insert*
        state, never a stale pre-insert snapshot, proving the fix closes
        the race rather than merely making it less likely."""
        self._accepted_milestone_with_one_child()  # M-1 accepted; T-1 resolved.

        now = "2026-08-27T00:00:00Z"
        conn_holder = work_ledger.connect(self.repo_root)
        conn_holder.execute("BEGIN IMMEDIATE")
        conn_holder.execute(
            "INSERT INTO work_items "
            "(id, type, parent_id, title, status, created_at, updated_at) "
            "VALUES ('T-race', 'task', 'M-1', 'Racer', 'open', ?, ?)",
            (now, now),
        )
        # conn_holder now holds the ledger's single write lock with an
        # uncommitted, unresolved child inserted under M-1 — this is the
        # exact mid-race state a pre-fix check would already have missed.

        archive_result = []

        def do_archive():
            archive_result.append(self.ledger.archive_work_item("M-1"))

        t = threading.Thread(target=do_archive)
        t.start()
        # A brief window for archive_work_item()'s own BEGIN IMMEDIATE to
        # be issued and block behind the held lock (not required for
        # correctness — busy_timeout=2000ms covers any scheduling delay —
        # but makes the intended lock-contention interleaving concrete
        # rather than merely possible).
        time.sleep(0.05)
        conn_holder.execute("COMMIT")
        conn_holder.close()
        t.join(timeout=5)
        self.assertFalse(t.is_alive(), "archive_work_item() did not return")

        self.assertEqual(
            archive_result,
            [False],
            "archival must be refused once an unresolved child exists, "
            "even one inserted after the initial fixture setup",
        )
        item = self.ledger.get_work_item("M-1")
        self.assertIsNone(item.archived_at)
        self.assertEqual(item.status, "accepted")


class TestTaskArchivalParentLifecycle(LedgerTestCase):
    """FR-015a regression: archiving a task deletes that task's own
    evidence rows (data-model.md's "Archival"), so archiving an
    attributed, done+evidenced task while its parent milestone is still
    `open` or `review` can silently invalidate the parent's
    review-readiness — or the very evidence that justified an
    already-in-flight review — out from underneath it. An attributed
    task's archival is refused while its parent is `open`/`review`, and
    permitted once the parent reaches its own terminal state
    (`accepted`/`superseded`, at which point its child set can never
    change again). An unattributed task (no `parent_id`) keeps 001's
    original, parent-independent archival behavior unchanged."""

    def _milestone_with_done_evidenced_child(self, milestone_id="M-1", task_id="T-1"):
        self.ledger.create_work_item(
            id=milestone_id,
            title="M",
            source_kind="adhoc",
            source_locator=milestone_id,
            type="milestone",
        )
        self.ledger.create_work_item(
            id=task_id,
            title="T",
            source_kind="adhoc",
            source_locator=task_id,
            parent_id=milestone_id,
        )
        self.assertTrue(self.ledger.mark_done(task_id))
        self.ledger.add_evidence(task_id, "commit", "abc")

    def test_attributed_done_evidenced_task_cannot_be_archived_while_parent_open(self):
        self._milestone_with_done_evidenced_child()
        self.assertTrue(self.ledger.is_review_ready("M-1"))
        before = self.ledger.get_work_item("T-1")

        self.assertFalse(self.ledger.archive_work_item("T-1"))

        after = self.ledger.get_work_item("T-1")
        self.assertEqual(before, after)
        # The invariant this regression exists for: archival must not be
        # allowed to quietly knock a review-ready milestone off of
        # review-ready by deleting the evidence that made it so.
        self.assertTrue(self.ledger.is_review_ready("M-1"))

    def test_attributed_task_cannot_be_archived_while_parent_in_review(self):
        self._milestone_with_done_evidenced_child()
        self.assertTrue(self.ledger.mark_in_review("M-1"))
        before = self.ledger.get_work_item("T-1")

        self.assertFalse(self.ledger.archive_work_item("T-1"))

        after = self.ledger.get_work_item("T-1")
        self.assertEqual(before, after)
        self.assertEqual(self.ledger.get_work_item("M-1").status, "review")

    def test_attributed_task_can_be_archived_after_parent_accepted(self):
        self._milestone_with_done_evidenced_child()
        self.assertTrue(self.ledger.mark_in_review("M-1"))
        self.assertTrue(self.ledger.accept_milestone("M-1"))

        self.assertTrue(self.ledger.archive_work_item("T-1"))

        item = self.ledger.get_work_item("T-1")
        self.assertIsNotNone(item.archived_at)
        self.assertEqual(item.status, "done")
        self.assertEqual(item.parent_id, "M-1")

    def test_attributed_task_can_be_archived_after_parent_superseded(self):
        self._milestone_with_done_evidenced_child()
        self.ledger.create_work_item(
            id="M-2",
            title="M2",
            source_kind="adhoc",
            source_locator="M-2",
            type="milestone",
        )
        self.assertTrue(self.ledger.mark_superseded("M-1", "M-2"))

        self.assertTrue(self.ledger.archive_work_item("T-1"))

        item = self.ledger.get_work_item("T-1")
        self.assertIsNotNone(item.archived_at)

    def test_unattributed_terminal_task_retains_001_archival_behavior(self):
        # No parent_id at all — 001's original archival path, entirely
        # unaffected by FR-015a's parent-lifecycle precondition.
        self.ledger.create_work_item(
            id="T-solo",
            title="Solo",
            source_kind="adhoc",
            source_locator="solo",
        )
        self.assertTrue(self.ledger.mark_done("T-solo"))

        self.assertTrue(self.ledger.archive_work_item("T-solo"))

        item = self.ledger.get_work_item("T-solo")
        self.assertIsNotNone(item.archived_at)
        self.assertIsNone(item.parent_id)

    def test_failed_archival_leaves_task_and_evidence_completely_unchanged(self):
        self._milestone_with_done_evidenced_child()
        before = self.ledger.get_work_item("T-1")

        self.assertFalse(self.ledger.archive_work_item("T-1"))

        after = self.ledger.get_work_item("T-1")
        self.assertEqual(before, after)
        self.assertTrue(self.ledger.has_qualifying_evidence("T-1"))
        conn = work_ledger.connect(self.repo_root)
        try:
            evidence_count = conn.execute(
                "SELECT COUNT(*) FROM work_item_evidence WHERE work_item_id = 'T-1'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(evidence_count, 1)

    def test_concurrent_archive_refused_while_review_commit_is_still_in_flight(self):
        """One of the two valid race orderings between `accept_milestone`
        and `archive_work_item(child)`: `archive_work_item`'s own
        `BEGIN IMMEDIATE` acquires the write lock first (forced here by
        holding an unrelated write lock open on a second connection while
        M-1 is still `review`, then releasing it only once the archival
        thread is already blocked waiting on it) and evaluates the
        parent-lifecycle precondition against the still-`review` parent —
        refused. `accept_milestone` proceeds only afterward and succeeds
        normally. This proves archival never observes a stale pre-review
        snapshot that could let it slip through before an in-flight review
        commits."""
        self._milestone_with_done_evidenced_child()
        self.assertTrue(self.ledger.mark_in_review("M-1"))

        conn_holder = work_ledger.connect(self.repo_root)
        conn_holder.execute("BEGIN IMMEDIATE")
        # Holds the ledger's single write lock with M-1 still 'review' —
        # the exact state archive_work_item's own transaction must observe
        # once it acquires the lock in turn.

        archive_result = []

        def do_archive():
            archive_result.append(self.ledger.archive_work_item("T-1"))

        t = threading.Thread(target=do_archive)
        t.start()
        time.sleep(0.05)
        conn_holder.execute("COMMIT")
        conn_holder.close()
        t.join(timeout=5)
        self.assertFalse(t.is_alive(), "archive_work_item() did not return")

        self.assertEqual(
            archive_result,
            [False],
            "archival must be refused while the parent milestone is "
            "still in review, never racing ahead of a pending review",
        )
        item = self.ledger.get_work_item("T-1")
        self.assertIsNone(item.archived_at)

        # The parent's own lifecycle is unaffected by the refused archival
        # attempt — acceptance still proceeds normally afterward.
        self.assertTrue(self.ledger.accept_milestone("M-1"))

    def test_concurrent_archive_serializes_after_an_in_flight_accept_commits(self):
        """The other valid race ordering: `accept_milestone`'s own
        transition to `accepted` is held open, uncommitted, on a second
        connection while `archive_work_item(child)` runs concurrently on a
        thread. `archive_work_item`'s `BEGIN IMMEDIATE` can only proceed
        once the held write lock is released (SQLite serializes writers),
        so its parent-lifecycle precondition is necessarily evaluated
        against the *post-accept* state, never a stale pre-accept `review`
        snapshot — proving the fix closes the race in this direction too,
        not merely in the archive-goes-first direction."""
        self._milestone_with_done_evidenced_child()
        self.assertTrue(self.ledger.mark_in_review("M-1"))

        now = "2026-08-27T00:00:00Z"
        conn_holder = work_ledger.connect(self.repo_root)
        conn_holder.execute("BEGIN IMMEDIATE")
        conn_holder.execute(
            "UPDATE work_items SET status = 'accepted', updated_at = ? "
            "WHERE id = 'M-1' AND type = 'milestone' AND status = 'review'",
            (now,),
        )
        # conn_holder now holds the write lock with an uncommitted
        # M-1 -> accepted transition — the exact mid-race state a
        # pre-fix (or non-atomic) precondition check could still miss.

        archive_result = []

        def do_archive():
            archive_result.append(self.ledger.archive_work_item("T-1"))

        t = threading.Thread(target=do_archive)
        t.start()
        time.sleep(0.05)
        conn_holder.execute("COMMIT")
        conn_holder.close()
        t.join(timeout=5)
        self.assertFalse(t.is_alive(), "archive_work_item() did not return")

        self.assertEqual(
            archive_result,
            [True],
            "archival must succeed once the parent's acceptance has "
            "actually committed, even when that commit lands mid-race",
        )
        item = self.ledger.get_work_item("T-1")
        self.assertIsNotNone(item.archived_at)


class TestQuickstartEndToEndV2(LedgerTestCase):
    """T018: specs/002-milestone-task-work-items/quickstart.md's five
    scenarios end to end, mirroring TestQuickstartEndToEnd's own
    convention."""

    def test_quickstart_v2_scenarios_1_through_5(self):
        # -- Scenario 1 ---------------------------------------------------
        self.ledger.create_work_item(
            id="M-1",
            title="Ship the milestone/task model",
            source_kind="plan",
            source_locator="plans/active/x",
            type="milestone",
        )
        self.ledger.create_work_item(
            id="T-1",
            title="Write data-model.md",
            source_kind="plan",
            source_locator="plans/active/x#1",
            parent_id="M-1",
        )
        self.ledger.create_work_item(
            id="T-2",
            title="Implement schema v2",
            source_kind="plan",
            source_locator="plans/active/x#2",
            parent_id="M-1",
        )
        self.assertEqual(self.ledger.get_work_item("T-1").parent_id, "M-1")
        self.assertIsNone(self.ledger.get_work_item("M-1").parent_id)

        with self.assertRaises(ValueError):
            self.ledger.create_work_item(
                id="T-3",
                title="Bad parent",
                source_kind="plan",
                source_locator="x",
                parent_id="T-1",
            )
        self.assertIsNone(self.ledger.get_work_item("T-3"))

        # -- Scenario 2 ---------------------------------------------------
        self.assertTrue(self.ledger.mark_done("T-1"))
        self.assertFalse(self.ledger.has_qualifying_evidence("T-1"))
        self.ledger.add_evidence("T-1", "commit", "abc123")
        self.assertTrue(self.ledger.has_qualifying_evidence("T-1"))

        # -- Scenario 3 ---------------------------------------------------
        self.assertFalse(self.ledger.is_review_ready("M-1"))
        self.assertTrue(self.ledger.mark_done("T-2"))
        self.ledger.add_evidence("T-2", "pull_request", "https://example/pr/1")
        self.assertTrue(self.ledger.is_review_ready("M-1"))
        self.assertTrue(self.ledger.mark_in_review("M-1"))
        self.assertTrue(self.ledger.claim("M-1", "reviewer-1"))
        self.assertFalse(self.ledger.claim("M-1", "reviewer-2"))

        # -- Scenario 4 ---------------------------------------------------
        snapshot_t1 = self.ledger.get_work_item("T-1")
        snapshot_t2 = self.ledger.get_work_item("T-2")
        self.ledger.release_claim("M-1", "reviewer-1")
        self.assertTrue(self.ledger.decline_review("M-1"))
        self.ledger.create_work_item(
            id="T-4",
            title="Fix flagged issue",
            source_kind="plan",
            source_locator="plans/active/x#4",
            parent_id="M-1",
        )
        self.assertEqual(self.ledger.get_work_item("T-1"), snapshot_t1)
        self.assertEqual(self.ledger.get_work_item("T-2"), snapshot_t2)
        self.assertFalse(self.ledger.is_review_ready("M-1"))

        # -- Scenario 5 ---------------------------------------------------
        self.assertTrue(self.ledger.mark_done("T-4"))
        self.ledger.add_evidence("T-4", "commit", "def456")
        projection = self.ledger.generate_projection()
        ids = {p.id for p in projection}
        self.assertNotIn("M-1", ids)
        self.assertTrue({"T-1", "T-2", "T-4"} <= ids)
        second_projection = self.ledger.generate_projection()
        self.assertEqual(projection, second_projection)


if __name__ == "__main__":
    unittest.main()
