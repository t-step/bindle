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


if __name__ == "__main__":
    unittest.main()
