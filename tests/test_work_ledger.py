import os
import sqlite3
import sys
import tempfile
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
            "(id, status, source_kind, source_locator, created_at, updated_at) "
            "VALUES ('WI-1', 'open', 'adhoc', 'x', ?, ?)",
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
                "(id, status, source_kind, source_locator, created_at, updated_at) "
                "VALUES ('WI-1', 'open', 'adhoc', 'x', ?, ?)",
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
                "(id, status, source_kind, source_locator, created_at, updated_at) "
                "VALUES ('WI-1', 'open', 'adhoc', 'x', ?, ?)",
                (_NOW, _NOW),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO work_item_blocked_by (work_item_id, blocked_on_id) "
                    "VALUES ('WI-1', 'WI-1')"
                )
        finally:
            conn.close()


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

    def test_claim_against_nonexistent_item_raises_not_already_claimed(self):
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.ledger.claim("does-not-exist", "agent-A")
        self.assertIn("FOREIGN KEY", str(ctx.exception))

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

    # -- Re-archiving an already-archived item is safe, not corrupting ----

    def test_archiving_already_archived_item_is_idempotent(self):
        self._create("A")
        self.assertTrue(self.ledger.mark_done("A"))
        self.assertTrue(self.ledger.archive_work_item("A"))
        first = self.ledger.get_work_item("A")

        # Whatever this implementation returns for a second archival
        # attempt, it must not raise, and the thinned shape must be
        # unchanged afterward.
        second_result = self.ledger.archive_work_item("A")
        self.assertIn(second_result, (True, False))

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


if __name__ == "__main__":
    unittest.main()
