import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle import work_ledger, work_status

_NOW = "2026-08-26T00:00:00Z"


class LedgerTestCase(unittest.TestCase):
    """Mirrors tests/test_work_ledger.py's own `LedgerTestCase` fixture."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_root = self.tmp.name
        self.ledger = work_ledger.WorkLedger(self.repo_root)

    def tearDown(self):
        self.tmp.cleanup()


class TestIsDispatchableCoherence(LedgerTestCase):
    """specs/005-work-state-visibility research.md: "dispatchable-next
    shares one authoritative predicate" — `is_dispatchable()` must agree
    with `list_available_work_items()`'s own live return value for every
    constructed task, across every (status, claimed, blocked) combination
    a real ledger can produce. This is the regression guard on
    `list_available_work_items()`'s internal refactor (data-model.md),
    not the mechanism that establishes the invariant — the refactored
    method's own shared function call is."""

    def test_coherence_across_mixed_status_claim_block_combinations(self):
        # open/unclaimed/unblocked
        self.ledger.create_work_item(
            id="open-free", title="t", source_kind="adhoc", source_locator="x"
        )
        # open/claimed/unblocked
        self.ledger.create_work_item(
            id="open-claimed", title="t", source_kind="adhoc", source_locator="x"
        )
        self.ledger.claim("open-claimed", owner="alice")
        # open/unclaimed/blocked
        self.ledger.create_work_item(
            id="blocker", title="t", source_kind="adhoc", source_locator="x"
        )
        self.ledger.create_work_item(
            id="open-blocked",
            title="t",
            source_kind="adhoc",
            source_locator="x",
            blocked_by=["blocker"],
        )
        # open/claimed/blocked
        self.ledger.create_work_item(
            id="blocker2", title="t", source_kind="adhoc", source_locator="x"
        )
        self.ledger.create_work_item(
            id="open-claimed-blocked",
            title="t",
            source_kind="adhoc",
            source_locator="x",
            blocked_by=["blocker2"],
        )
        self.ledger.claim("open-claimed-blocked", owner="bob")
        # done, superseded
        self.ledger.create_work_item(
            id="done-task", title="t", source_kind="adhoc", source_locator="x"
        )
        self.ledger.mark_done("done-task")
        self.ledger.create_work_item(
            id="superseded-task", title="t", source_kind="adhoc", source_locator="x"
        )
        self.ledger.mark_superseded("superseded-task", superseded_by="open-free")

        available = set(self.ledger.list_available_work_items())
        for task_id in (
            "open-free",
            "open-claimed",
            "blocker",
            "open-blocked",
            "blocker2",
            "open-claimed-blocked",
            "done-task",
            "superseded-task",
        ):
            item = self.ledger.get_work_item(task_id)
            claimed = self.ledger.is_claimed(task_id)
            blocked = self.ledger.is_blocked(task_id)
            expected = task_id in available
            self.assertEqual(
                work_ledger.is_dispatchable(item.status, claimed, blocked),
                expected,
                f"{task_id}: status={item.status} claimed={claimed} blocked={blocked}",
            )


class TestBuildSnapshot(LedgerTestCase):
    """specs/005-work-state-visibility User Story 1 (spec.md SC-001/SC-002):
    every fact `build_snapshot()` reports must equal a direct call to the
    underlying `WorkLedger`/`milestone_review` method on the same ledger —
    never a second, independently-derived computation."""

    def test_empty_ledger_produces_empty_but_valid_snapshot(self):
        snapshot = work_status.build_snapshot(self.ledger)
        self.assertEqual(snapshot.tasks, [])
        self.assertEqual(snapshot.milestones, [])

    def test_claimed_task_is_claimed_and_not_dispatchable(self):
        self.ledger.create_work_item(
            id="T-1", title="T", source_kind="adhoc", source_locator="x"
        )
        self.ledger.claim("T-1", owner="alice", worktree_path="/wt", branch="feature/x")
        snapshot = work_status.build_snapshot(self.ledger)
        task = snapshot.tasks[0]
        self.assertEqual(task.claim, self.ledger.get_claim("T-1"))
        self.assertEqual(task.claim.owner, "alice")
        self.assertFalse(task.dispatchable)

    def test_open_unclaimed_unblocked_task_is_dispatchable(self):
        self.ledger.create_work_item(
            id="T-1", title="T", source_kind="adhoc", source_locator="x"
        )
        snapshot = work_status.build_snapshot(self.ledger)
        task = snapshot.tasks[0]
        self.assertTrue(task.dispatchable)
        self.assertEqual(task.blocking_ids, [])

    def test_blocked_task_names_specific_blocking_ids_not_merely_a_bool(self):
        self.ledger.create_work_item(
            id="A", title="A", source_kind="adhoc", source_locator="x"
        )
        self.ledger.create_work_item(
            id="B", title="B", source_kind="adhoc", source_locator="x"
        )
        self.ledger.create_work_item(
            id="C",
            title="C",
            source_kind="adhoc",
            source_locator="x",
            blocked_by=["A", "B"],
        )
        snapshot = work_status.build_snapshot(self.ledger)
        by_id = {t.id: t for t in snapshot.tasks}
        self.assertEqual(by_id["C"].blocking_ids, self.ledger.list_blocking("C"))
        self.assertEqual(by_id["C"].blocking_ids, ["A", "B"])
        self.assertFalse(by_id["C"].dispatchable)

    def test_every_task_fact_matches_direct_ledger_calls(self):
        self.ledger.create_work_item(
            id="A", title="A", source_kind="adhoc", source_locator="x"
        )
        self.ledger.create_work_item(
            id="B",
            title="B",
            source_kind="adhoc",
            source_locator="x",
            blocked_by=["A"],
        )
        self.ledger.claim("B", owner="carol")
        available = set(self.ledger.list_available_work_items())
        snapshot = work_status.build_snapshot(self.ledger)
        for task in snapshot.tasks:
            self.assertEqual(task.claim, self.ledger.get_claim(task.id))
            self.assertEqual(task.blocking_ids, self.ledger.list_blocking(task.id))
            self.assertEqual(task.dispatchable, task.id in available)

    def test_archived_task_is_excluded(self):
        self.ledger.create_work_item(
            id="T-1", title="T", source_kind="adhoc", source_locator="x"
        )
        self.ledger.mark_done("T-1")
        self.ledger.archive_work_item("T-1")
        snapshot = work_status.build_snapshot(self.ledger)
        self.assertEqual(snapshot.tasks, [])

    def test_milestones_span_status_and_readiness_matching_review_milestone(self):
        from bindle import milestone_review

        self.ledger.create_work_item(
            id="M-open-not-ready", title="M1", source_kind="adhoc",
            source_locator="x", type="milestone",
        )
        self.ledger.create_work_item(
            id="M-open-ready", title="M2", source_kind="adhoc",
            source_locator="x", type="milestone",
        )
        self.ledger.create_work_item(
            id="T-ready-child", title="T", source_kind="adhoc",
            source_locator="x", parent_id="M-open-ready",
        )
        self.ledger.mark_done("T-ready-child")
        self.ledger.add_evidence("T-ready-child", "commit", "abc123")

        snapshot = work_status.build_snapshot(self.ledger)
        by_id = {m.id: m for m in snapshot.milestones}

        for milestone_id in ("M-open-not-ready", "M-open-ready"):
            expected = milestone_review.review_milestone(self.ledger, milestone_id).view
            actual = by_id[milestone_id]
            self.assertEqual(actual.status, expected.status)
            self.assertEqual(actual.review_ready, expected.review_ready)
            self.assertEqual(actual.not_ready_reason, expected.not_ready_reason)
            self.assertEqual(actual.blocking_ids, expected.blocking_ids)
            self.assertEqual(actual.claim, expected.claim)

        self.assertFalse(by_id["M-open-not-ready"].review_ready)
        self.assertTrue(by_id["M-open-ready"].review_ready)
        self.assertEqual(by_id["M-open-not-ready"].not_ready_reason, ["no_children"])

    def test_ordering_matches_list_work_items_id_order(self):
        for task_id in ("C", "A", "B"):
            self.ledger.create_work_item(
                id=task_id, title=task_id, source_kind="adhoc", source_locator="x"
            )
        snapshot = work_status.build_snapshot(self.ledger)
        self.assertEqual([t.id for t in snapshot.tasks], ["A", "B", "C"])

    def test_build_snapshot_never_mutates_the_ledger(self):
        self.ledger.create_work_item(
            id="A", title="A", source_kind="adhoc", source_locator="x"
        )
        self.ledger.claim("A", owner="alice")
        before = self.ledger.list_work_items()
        before_claim = self.ledger.get_claim("A")
        work_status.build_snapshot(self.ledger)
        work_status.build_snapshot(self.ledger)
        self.assertEqual(self.ledger.list_work_items(), before)
        self.assertEqual(self.ledger.get_claim("A"), before_claim)


class TestSnapshotToJson(LedgerTestCase):
    """specs/005-work-state-visibility User Story 2 (spec.md SC-003/SC-004,
    contracts/work-status-json-v1.md)."""

    def _mixed_snapshot(self):
        self.ledger.create_work_item(
            id="M", title="Ship visibility", source_kind="adhoc",
            source_locator="x", type="milestone",
        )
        self.ledger.create_work_item(
            id="A", title="A", source_kind="adhoc", source_locator="x", parent_id="M"
        )
        self.ledger.create_work_item(
            id="B", title="B", source_kind="adhoc", source_locator="x", parent_id="M"
        )
        self.ledger.create_work_item(
            id="C", title="C (needs A and B)", source_kind="adhoc",
            source_locator="x", parent_id="M", blocked_by=["A", "B"],
        )
        self.ledger.create_work_item(
            id="D", title="D (needs A only)", source_kind="adhoc",
            source_locator="x", parent_id="M", blocked_by=["A"],
        )
        self.ledger.claim("D", owner="alice")
        return work_status.build_snapshot(self.ledger)

    def test_matches_contract_shape_field_for_field(self):
        snapshot = self._mixed_snapshot()
        payload = work_status.snapshot_to_json(snapshot)
        self.assertEqual(set(payload.keys()), {"tasks", "milestones"})
        by_id = {t["id"]: t for t in payload["tasks"]}
        self.assertEqual(
            by_id["A"],
            {
                "id": "A",
                "title": "A",
                "status": "open",
                "claim": None,
                "dispatchable": True,
                "blocking_ids": [],
            },
        )
        self.assertEqual(by_id["C"]["blocking_ids"], ["A", "B"])
        self.assertEqual(by_id["C"]["dispatchable"], False)
        self.assertEqual(
            by_id["D"]["claim"],
            {
                "owner": "alice",
                "claimed_at": self.ledger.get_claim("D").claimed_at,
                "worktree_path": None,
                "branch": None,
            },
        )
        milestone = payload["milestones"][0]
        self.assertEqual(milestone["id"], "M")
        self.assertEqual(milestone["review_ready"], False)
        self.assertEqual(milestone["not_ready_reason"], ["A", "B", "C", "D"])
        self.assertEqual(milestone["blocking_ids"], [])

    def test_blocking_ids_never_omitted_or_null_when_empty(self):
        self.ledger.create_work_item(
            id="A", title="A", source_kind="adhoc", source_locator="x"
        )
        snapshot = work_status.build_snapshot(self.ledger)
        payload = work_status.snapshot_to_json(snapshot)
        self.assertIn("blocking_ids", payload["tasks"][0])
        self.assertEqual(payload["tasks"][0]["blocking_ids"], [])

    def test_text_and_json_report_identical_semantic_facts(self):
        snapshot = self._mixed_snapshot()
        text = work_status.render_status_text(snapshot)
        payload = work_status.snapshot_to_json(snapshot)
        for task in payload["tasks"]:
            self.assertIn(task["id"], text)
            if task["dispatchable"]:
                self.assertIn("dispatchable", text)
            for blocker in task["blocking_ids"]:
                self.assertIn(f"blocked on:", text)
                self.assertIn(blocker, text)
        for milestone in payload["milestones"]:
            self.assertIn(milestone["id"], text)

    def test_json_is_byte_identical_across_two_serializations_of_one_snapshot(self):
        snapshot = self._mixed_snapshot()
        first = json.dumps(work_status.snapshot_to_json(snapshot), indent=2)
        second = json.dumps(work_status.snapshot_to_json(snapshot), indent=2)
        self.assertEqual(first, second)

    def test_json_is_byte_identical_across_two_fresh_builds_of_an_unchanged_ledger(self):
        self._mixed_snapshot()
        first = json.dumps(
            work_status.snapshot_to_json(work_status.build_snapshot(self.ledger)), indent=2
        )
        second = json.dumps(
            work_status.snapshot_to_json(work_status.build_snapshot(self.ledger)), indent=2
        )
        self.assertEqual(first, second)

    def test_no_timestamp_field_anywhere_in_the_serialized_structure(self):
        snapshot = self._mixed_snapshot()
        payload = work_status.snapshot_to_json(snapshot)
        # The only ISO-8601 timestamp anywhere in the payload is the
        # claim's own recorded `claimed_at` — nothing else (task/milestone
        # level) carries a wall-clock "generated at" value.
        flat = json.dumps(payload)
        occurrences = flat.count(self.ledger.get_claim("D").claimed_at)
        self.assertEqual(occurrences, 1)


class TestBuildForecast(LedgerTestCase):
    """specs/005-work-state-visibility User Story 4 (spec.md SC-007/SC-008):
    `build_forecast()` is a pure relate over an already-built
    `WorkStatusSnapshot` — no ledger access, no re-derivation of
    blocking/dispatchable rules."""

    def _worked_example(self):
        # spec.md's own worked example: C blocked on {A, B}; D blocked on
        # {A} and claimed (Acceptance Scenario US4.5).
        self.ledger.create_work_item(
            id="A", title="A", source_kind="adhoc", source_locator="x"
        )
        self.ledger.create_work_item(
            id="B", title="B", source_kind="adhoc", source_locator="x"
        )
        self.ledger.create_work_item(
            id="C", title="C", source_kind="adhoc", source_locator="x",
            blocked_by=["A", "B"],
        )
        self.ledger.create_work_item(
            id="D", title="D", source_kind="adhoc", source_locator="x",
            blocked_by=["A"],
        )
        self.ledger.claim("D", owner="alice")
        return work_status.build_snapshot(self.ledger)

    def test_dispatchable_now_matches_snapshot_dispatchable_tasks(self):
        snapshot = self._worked_example()
        frontier = work_status.build_forecast(snapshot)
        self.assertEqual(frontier.dispatchable_now, ["A", "B"])

    def test_convergence_point_named_for_item_blocked_by_more_than_one(self):
        snapshot = self._worked_example()
        frontier = work_status.build_forecast(snapshot)
        self.assertEqual(frontier.convergence_points, ["C"])

    def test_single_dependency_block_is_not_a_convergence_point(self):
        snapshot = self._worked_example()
        frontier = work_status.build_forecast(snapshot)
        self.assertNotIn("D", frontier.convergence_points)

    def test_unblocked_next_excludes_convergence_item_still_needing_another_blocker(self):
        snapshot = self._worked_example()
        frontier = work_status.build_forecast(snapshot)
        by_blocker = {e.resolved_blocker_id: e for e in frontier.frontier}
        # C needs both A and B -- resolving only A must not include C.
        self.assertEqual(by_blocker["A"].unblocked_next, ["D"])
        self.assertEqual(by_blocker["B"].unblocked_next, [])

    def test_dispatchable_next_task_only_and_uses_authoritative_predicate(self):
        # Rebuild without D's claim so it would actually become
        # dispatchable-next once A resolves.
        self.ledger.create_work_item(
            id="A", title="A", source_kind="adhoc", source_locator="x"
        )
        self.ledger.create_work_item(
            id="E", title="E", source_kind="adhoc", source_locator="x",
            blocked_by=["A"],
        )
        snapshot = work_status.build_snapshot(self.ledger)
        frontier = work_status.build_forecast(snapshot)
        by_blocker = {e.resolved_blocker_id: e for e in frontier.frontier}
        self.assertEqual(by_blocker["A"].unblocked_next, ["E"])
        self.assertEqual(by_blocker["A"].dispatchable_next, ["E"])

    def test_dispatchable_next_calls_authoritative_is_dispatchable(self):
        from unittest import mock

        snapshot = self._worked_example()
        with mock.patch(
            "bindle.work_ledger.is_dispatchable", wraps=work_ledger.is_dispatchable
        ) as spy:
            work_status.build_forecast(snapshot)
        self.assertTrue(spy.called)

    def test_claimed_task_becomes_unblocked_next_but_not_dispatchable_next(self):
        snapshot = self._worked_example()
        frontier = work_status.build_forecast(snapshot)
        by_blocker = {e.resolved_blocker_id: e for e in frontier.frontier}
        self.assertIn("D", by_blocker["A"].unblocked_next)
        self.assertNotIn("D", by_blocker["A"].dispatchable_next)

    def test_non_open_task_would_not_be_dispatchable_next(self):
        self.ledger.create_work_item(
            id="A", title="A", source_kind="adhoc", source_locator="x"
        )
        self.ledger.create_work_item(
            id="F", title="F", source_kind="adhoc", source_locator="x",
            blocked_by=["A"],
        )
        self.ledger.mark_done("F")
        snapshot = work_status.build_snapshot(self.ledger)
        frontier = work_status.build_forecast(snapshot)
        by_blocker = {e.resolved_blocker_id: e for e in frontier.frontier}
        self.assertIn("F", by_blocker["A"].unblocked_next)
        self.assertNotIn("F", by_blocker["A"].dispatchable_next)

    def test_dangling_blocking_id_is_grouped_exactly_as_declared(self):
        # A genuinely dangling blocker (an id that never validly identified
        # a work item) is only reachable, in the normal write path, via a
        # connection that ran without foreign keys enabled — mirrors
        # tests/test_work_ledger.py's own "dangling blocker" fixture.
        self.ledger.create_work_item(
            id="G", title="G", source_kind="adhoc", source_locator="x",
        )
        conn = work_ledger.connect(self.repo_root)
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                "INSERT INTO work_item_blocked_by (work_item_id, blocked_on_id) "
                "VALUES ('G', 'nonexistent')"
            )
        finally:
            conn.close()

        snapshot = work_status.build_snapshot(self.ledger)
        frontier = work_status.build_forecast(snapshot)
        by_blocker = {e.resolved_blocker_id: e for e in frontier.frontier}
        self.assertIn("nonexistent", by_blocker)
        self.assertEqual(by_blocker["nonexistent"].unblocked_next, ["G"])

    def test_milestone_review_frontier_is_snapshot_milestones_not_a_second_structure(self):
        self.ledger.create_work_item(
            id="M", title="M", source_kind="adhoc", source_locator="x",
            type="milestone",
        )
        snapshot = work_status.build_snapshot(self.ledger)
        frontier = work_status.build_forecast(snapshot)
        self.assertFalse(hasattr(frontier, "milestones"))
        self.assertEqual(len(snapshot.milestones), 1)

    def test_forecast_ordering_is_deterministic(self):
        snapshot = self._worked_example()
        first = work_status.build_forecast(snapshot)
        second = work_status.build_forecast(snapshot)
        self.assertEqual(first, second)
        self.assertEqual(
            [e.resolved_blocker_id for e in first.frontier], ["A", "B"]
        )

    def test_build_forecast_never_mutates_the_ledger(self):
        snapshot = self._worked_example()
        before = self.ledger.list_work_items()
        before_claim = self.ledger.get_claim("D")
        work_status.build_forecast(snapshot)
        self.assertEqual(self.ledger.list_work_items(), before)
        self.assertEqual(self.ledger.get_claim("D"), before_claim)


class TestRenderForecastText(LedgerTestCase):
    """spec.md SC-008: `bindle work forecast`'s plain-text output must
    never name a time, date, duration, or ETA."""

    def test_no_time_date_or_eta_language_anywhere_in_output(self):
        self.ledger.create_work_item(
            id="A", title="A", source_kind="adhoc", source_locator="x"
        )
        self.ledger.create_work_item(
            id="B", title="B", source_kind="adhoc", source_locator="x"
        )
        self.ledger.create_work_item(
            id="C", title="C", source_kind="adhoc", source_locator="x",
            blocked_by=["A", "B"],
        )
        self.ledger.create_work_item(
            id="D", title="D", source_kind="adhoc", source_locator="x",
            blocked_by=["A"],
        )
        self.ledger.claim("D", owner="alice")
        snapshot = work_status.build_snapshot(self.ledger)
        frontier = work_status.build_forecast(snapshot)
        text = work_status.render_forecast_text(snapshot, frontier)
        lowered = text.lower()
        for forbidden in ("eta", "duration", "estimated", "minutes", "hours"):
            self.assertNotIn(forbidden, lowered)

    def test_convergence_point_and_gap_reason_are_rendered(self):
        self.ledger.create_work_item(
            id="A", title="A", source_kind="adhoc", source_locator="x"
        )
        self.ledger.create_work_item(
            id="B", title="B", source_kind="adhoc", source_locator="x"
        )
        self.ledger.create_work_item(
            id="C", title="C", source_kind="adhoc", source_locator="x",
            blocked_by=["A", "B"],
        )
        self.ledger.create_work_item(
            id="D", title="D", source_kind="adhoc", source_locator="x",
            blocked_by=["A"],
        )
        self.ledger.claim("D", owner="alice")
        snapshot = work_status.build_snapshot(self.ledger)
        frontier = work_status.build_forecast(snapshot)
        text = work_status.render_forecast_text(snapshot, frontier)
        self.assertIn("dispatchable now: A, B", text)
        self.assertIn("(convergence point)", text)
        self.assertIn("if A resolves:", text)
        self.assertIn("unblocked-next: D", text)
        self.assertIn("dispatchable-next: (none — D remains claimed)", text)


class TestWatchIntervalResolution(unittest.TestCase):
    """T015 (specs/005-work-state-visibility, Phase 5 - US3): FR-011's
    clamping rule is a small, pure function — no override, an
    at-or-above-minimum override, and a below-minimum override are the
    only three cases."""

    def test_no_override_uses_default(self):
        self.assertEqual(
            work_status.resolve_watch_interval(None),
            work_status.DEFAULT_WATCH_INTERVAL_SECONDS,
        )

    def test_override_at_or_above_minimum_is_used_as_given(self):
        self.assertEqual(work_status.resolve_watch_interval(5.0), 5.0)
        self.assertEqual(
            work_status.resolve_watch_interval(work_status.MIN_WATCH_INTERVAL_SECONDS),
            work_status.MIN_WATCH_INTERVAL_SECONDS,
        )

    def test_override_below_minimum_is_clamped_up_not_rejected(self):
        self.assertEqual(
            work_status.resolve_watch_interval(0.001),
            work_status.MIN_WATCH_INTERVAL_SECONDS,
        )
        self.assertEqual(
            work_status.resolve_watch_interval(0.0),
            work_status.MIN_WATCH_INTERVAL_SECONDS,
        )

    def test_non_finite_override_is_rejected(self):
        for requested in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(requested=requested):
                with self.assertRaises(ValueError):
                    work_status.resolve_watch_interval(requested)


class TestWatchSnapshots(LedgerTestCase):
    """T016/T017 (specs/005-work-state-visibility, Phase 5 - US3):
    `watch_snapshots()` is the smallest testable seam over an otherwise
    infinite loop — an injected `sleep` callable lets these tests drive
    a bounded number of iterations with no real wall-clock wait, no
    thread, and no subprocess."""

    def _sleep_recorder(self):
        calls: list[float] = []

        def fake_sleep(seconds: float) -> None:
            calls.append(seconds)

        return calls, fake_sleep

    def test_first_snapshot_is_produced_before_any_sleep(self):
        calls, fake_sleep = self._sleep_recorder()
        gen = work_status.watch_snapshots(self.ledger, 5.0, sleep=fake_sleep)
        snapshot = next(gen)
        self.assertIsInstance(snapshot, work_status.WorkStatusSnapshot)
        self.assertEqual(calls, [])

    def test_repeated_snapshot_generation_uses_build_snapshot_each_time(self):
        calls, fake_sleep = self._sleep_recorder()
        gen = work_status.watch_snapshots(self.ledger, 3.0, sleep=fake_sleep)
        first = next(gen)
        second = next(gen)
        self.assertEqual(first, second)  # unchanged ledger -> deterministic
        self.assertEqual(calls, [3.0])

    def test_sleep_uses_the_resolved_interval_every_iteration(self):
        calls, fake_sleep = self._sleep_recorder()
        gen = work_status.watch_snapshots(self.ledger, 1.5, sleep=fake_sleep)
        for _ in range(3):
            next(gen)
        self.assertEqual(calls, [1.5, 1.5])

    def test_changed_ledger_state_appears_on_the_next_iteration(self):
        self.ledger.create_work_item(
            id="A", title="A", source_kind="adhoc", source_locator="x"
        )
        calls, fake_sleep = self._sleep_recorder()
        gen = work_status.watch_snapshots(self.ledger, 1.0, sleep=fake_sleep)
        first = next(gen)
        self.assertIsNone(first.tasks[0].claim)

        self.ledger.claim("A", owner="bob")
        second = next(gen)
        self.assertIsNotNone(second.tasks[0].claim)
        self.assertEqual(second.tasks[0].claim.owner, "bob")
        # the first snapshot object itself is untouched by the later claim
        self.assertIsNone(first.tasks[0].claim)

    def test_never_mutates_the_ledger(self):
        self.ledger.create_work_item(
            id="A", title="A", source_kind="adhoc", source_locator="x"
        )
        before = self.ledger.list_work_items()
        before_claim = self.ledger.get_claim("A")
        _, fake_sleep = self._sleep_recorder()
        gen = work_status.watch_snapshots(self.ledger, 1.0, sleep=fake_sleep)
        for _ in range(3):
            next(gen)
        self.assertEqual(self.ledger.list_work_items(), before)
        self.assertEqual(self.ledger.get_claim("A"), before_claim)

    def test_keyboard_interrupt_during_sleep_propagates_after_already_yielded_snapshots(self):
        calls: list[float] = []

        def interrupting_sleep(seconds: float) -> None:
            calls.append(seconds)
            if len(calls) == 2:
                raise KeyboardInterrupt

        gen = work_status.watch_snapshots(self.ledger, 1.0, sleep=interrupting_sleep)
        collected = []
        with self.assertRaises(KeyboardInterrupt):
            for snapshot in gen:
                collected.append(snapshot)
        # two full refreshes were already yielded before the interrupt —
        # no partial/half-built snapshot is ever produced (SC-006)
        self.assertEqual(len(collected), 2)


if __name__ == "__main__":
    unittest.main()
