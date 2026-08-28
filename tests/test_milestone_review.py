import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bindle import milestone_review, work_ledger


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

    def _create_milestone(self, id, **kwargs):
        kwargs.setdefault("title", f"Milestone {id}")
        kwargs.setdefault("source_kind", "adhoc")
        kwargs.setdefault("source_locator", f"plans/active/example.md#{id}")
        self.ledger.create_work_item(id=id, type="milestone", **kwargs)

    def _create_task(self, id, **kwargs):
        kwargs.setdefault("title", f"Task {id}")
        kwargs.setdefault("source_kind", "adhoc")
        kwargs.setdefault("source_locator", f"plans/active/example.md#{id}")
        self.ledger.create_work_item(id=id, **kwargs)

    def _ready_milestone(self, milestone_id="M-1", child_id="T-1"):
        self._create_milestone(milestone_id)
        self._create_task(child_id, parent_id=milestone_id)
        self.assertTrue(self.ledger.mark_done(child_id))
        self.ledger.add_evidence(child_id, "commit", "abc123")
        return milestone_id, child_id


class TestReviewMilestone(LedgerTestCase):
    """T008 (US1): review_milestone() rejects not-found/not-a-milestone
    ids, reports the specific unmet readiness condition when not ready,
    and never disagrees with a direct is_review_ready() call (SC-001)."""

    def test_not_found_is_rejected(self):
        result = milestone_review.review_milestone(self.ledger, "does-not-exist")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_found")
        self.assertIsNone(result.view)

    def test_task_id_is_rejected_as_not_a_milestone(self):
        self._create_task("T-1")
        result = milestone_review.review_milestone(self.ledger, "T-1")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_a_milestone")
        self.assertIsNone(result.view)

    def test_zero_children_is_not_ready_with_no_children_reason(self):
        self._create_milestone("M-1")
        result = milestone_review.review_milestone(self.ledger, "M-1")
        self.assertTrue(result.ok)
        self.assertFalse(result.view.review_ready)
        self.assertIn("no_children", result.view.not_ready_reason)
        self.assertEqual(
            result.view.review_ready, self.ledger.is_review_ready("M-1")
        )

    def test_blocked_milestone_is_not_ready_even_with_every_child_resolved(self):
        self._create_task("Blocker")
        milestone_id, child_id = self._ready_milestone()
        self.ledger.add_blocked_by(milestone_id, "Blocker")

        result = milestone_review.review_milestone(self.ledger, milestone_id)
        self.assertTrue(result.ok)
        self.assertFalse(result.view.review_ready)
        self.assertIn("blocked", result.view.not_ready_reason)
        self.assertTrue(result.view.is_blocked)
        self.assertEqual(result.view.blocking_ids, ["Blocker"])
        self.assertEqual(
            result.view.review_ready, self.ledger.is_review_ready(milestone_id)
        )

    def test_blocking_ids_names_every_still_blocking_dependency(self):
        # spec.md Acceptance Scenario US1.4: "identifies the blocking
        # dependency" — not just a boolean.
        self._create_task("Blocker-1")
        self._create_task("Blocker-2")
        self._create_milestone("M-1")
        self.ledger.add_blocked_by("M-1", "Blocker-1")
        self.ledger.add_blocked_by("M-1", "Blocker-2")

        result = milestone_review.review_milestone(self.ledger, "M-1")
        self.assertEqual(result.view.blocking_ids, ["Blocker-1", "Blocker-2"])

        self.assertTrue(self.ledger.mark_done("Blocker-1"))
        result = milestone_review.review_milestone(self.ledger, "M-1")
        self.assertEqual(result.view.blocking_ids, ["Blocker-2"])

    def test_unblocked_milestone_reports_empty_blocking_ids(self):
        milestone_id, _ = self._ready_milestone()
        result = milestone_review.review_milestone(self.ledger, milestone_id)
        self.assertFalse(result.view.is_blocked)
        self.assertEqual(result.view.blocking_ids, [])

    def test_mixed_children_not_ready_names_outstanding_children(self):
        self._create_milestone("M-1")
        self._create_task("T-open", parent_id="M-1")
        self._create_task("T-done-evidenced", parent_id="M-1")
        self.assertTrue(self.ledger.mark_done("T-done-evidenced"))
        self.ledger.add_evidence("T-done-evidenced", "commit", "abc")
        self._create_task("T-done-unevidenced", parent_id="M-1")
        self.assertTrue(self.ledger.mark_done("T-done-unevidenced"))

        result = milestone_review.review_milestone(self.ledger, "M-1")
        self.assertTrue(result.ok)
        self.assertFalse(result.view.review_ready)
        self.assertIn("T-open", result.view.not_ready_reason)
        self.assertIn("T-done-unevidenced", result.view.not_ready_reason)
        self.assertNotIn("T-done-evidenced", result.view.not_ready_reason)
        self.assertEqual(
            result.view.review_ready, self.ledger.is_review_ready("M-1")
        )

    def test_every_condition_resolved_is_ready(self):
        milestone_id, _ = self._ready_milestone()
        result = milestone_review.review_milestone(self.ledger, milestone_id)
        self.assertTrue(result.ok)
        self.assertTrue(result.view.review_ready)
        self.assertEqual(result.view.not_ready_reason, [])
        self.assertEqual(
            result.view.review_ready, self.ledger.is_review_ready(milestone_id)
        )

    # -- T014 (US2): evidence, blocking, and claim detail on the view --

    def test_child_with_multiple_evidence_kinds_lists_every_pointer(self):
        self._create_milestone("M-1")
        self._create_task("T-1", parent_id="M-1")
        self.ledger.add_evidence("T-1", "commit", "abc123", note="the fix")
        self.ledger.add_evidence("T-1", "pull_request", "https://example.com/pr/9")
        self.assertTrue(self.ledger.mark_done("T-1"))

        result = milestone_review.review_milestone(self.ledger, "M-1")
        child = result.view.children[0]
        self.assertEqual(len(child.evidence), 2)
        self.assertEqual(child.evidence[0].kind, "commit")
        self.assertEqual(child.evidence[0].value, "abc123")
        self.assertEqual(child.evidence[0].note, "the fix")
        self.assertEqual(child.evidence[1].kind, "pull_request")
        self.assertEqual(child.evidence[1].value, "https://example.com/pr/9")

    def test_child_with_zero_pointers_reports_empty_not_omitted(self):
        self._create_milestone("M-1")
        self._create_task("T-1", parent_id="M-1")

        result = milestone_review.review_milestone(self.ledger, "M-1")
        child = result.view.children[0]
        self.assertEqual(child.evidence, [])
        self.assertFalse(child.has_qualifying_evidence)

    def test_blocked_child_reports_blocked_state_alongside_status_and_evidence(self):
        self._create_task("Blocker")
        self._create_milestone("M-1")
        self._create_task("T-1", parent_id="M-1")
        self.ledger.add_blocked_by("T-1", "Blocker")
        self.ledger.add_evidence("T-1", "commit", "abc")

        result = milestone_review.review_milestone(self.ledger, "M-1")
        child = result.view.children[0]
        self.assertTrue(child.is_blocked)
        self.assertEqual(child.status, "open")
        self.assertEqual(len(child.evidence), 1)

    def test_milestone_own_claim_is_reported_distinct_from_status(self):
        milestone_id, _ = self._ready_milestone()
        self.assertTrue(self.ledger.mark_in_review(milestone_id))
        self.assertTrue(self.ledger.claim(milestone_id, "alice"))

        result = milestone_review.review_milestone(self.ledger, milestone_id)
        self.assertEqual(result.view.status, "review")
        self.assertIsNotNone(result.view.claim)
        self.assertEqual(result.view.claim.owner, "alice")
        self.assertIsInstance(result.view.claim.claimed_at, str)
        self.assertTrue(result.view.claim.claimed_at)


class TestListMilestones(LedgerTestCase):
    """T009 (US1): list_milestones() enumerates only milestones, in
    list_work_items()'s own id order, each with correct status/
    review_ready."""

    def test_empty_ledger_returns_empty_list(self):
        self.assertEqual(milestone_review.list_milestones(self.ledger), [])

    def test_only_milestones_are_enumerated(self):
        self._create_milestone("M-2")
        self._create_task("T-1")
        milestone_id, _ = self._ready_milestone("M-1", "T-child")

        entries = milestone_review.list_milestones(self.ledger)
        ids = [e.id for e in entries]
        self.assertEqual(ids, ["M-1", "M-2"])

        by_id = {e.id: e for e in entries}
        self.assertEqual(by_id["M-1"].status, "open")
        self.assertTrue(by_id["M-1"].review_ready)
        self.assertEqual(by_id["M-2"].status, "open")
        self.assertFalse(by_id["M-2"].review_ready)

    def test_ordering_matches_list_work_items_order(self):
        self._create_milestone("M-b")
        self._create_milestone("M-a")
        self._create_milestone("M-c")

        expected = [
            wi.id for wi in self.ledger.list_work_items() if wi.type == "milestone"
        ]
        actual = [e.id for e in milestone_review.list_milestones(self.ledger)]
        self.assertEqual(actual, expected)


class TestEnterReviewClaimRelease(LedgerTestCase):
    """T016 (US3): enter_review()/claim_milestone()/release_milestone()
    are thin, type-checked wrappers delegating directly to
    mark_in_review()/claim()/release_claim() — no new arbitration."""

    def test_enter_review_succeeds_only_when_ready_and_open(self):
        self._create_milestone("M-1")
        self._create_task("T-1", parent_id="M-1")
        result = milestone_review.enter_review(self.ledger, "M-1")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_ready_or_not_open")

        self.assertTrue(self.ledger.mark_done("T-1"))
        self.ledger.add_evidence("T-1", "commit", "abc")
        result = milestone_review.enter_review(self.ledger, "M-1")
        self.assertTrue(result.ok)
        self.assertEqual(self.ledger.get_work_item("M-1").status, "review")

        result = milestone_review.enter_review(self.ledger, "M-1")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_ready_or_not_open")

    def test_not_found_and_not_a_milestone_guard_all_three_functions(self):
        self._create_task("T-1")
        for fn, extra_args in (
            (milestone_review.enter_review, ()),
            (milestone_review.claim_milestone, ("alice",)),
            (milestone_review.release_milestone, ("alice",)),
        ):
            with self.subTest(fn=fn.__name__, case="not_found"):
                result = fn(self.ledger, "does-not-exist", *extra_args)
                self.assertFalse(result.ok)
                self.assertEqual(result.reason, "not_found")
            with self.subTest(fn=fn.__name__, case="not_a_milestone"):
                result = fn(self.ledger, "T-1", *extra_args)
                self.assertFalse(result.ok)
                self.assertEqual(result.reason, "not_a_milestone")

    def test_claim_milestone_records_owner(self):
        milestone_id, _ = self._ready_milestone()
        self.assertTrue(self.ledger.mark_in_review(milestone_id))

        result = milestone_review.claim_milestone(self.ledger, milestone_id, "alice")
        self.assertTrue(result.ok)
        self.assertEqual(self.ledger.get_claim(milestone_id).owner, "alice")

        result = milestone_review.claim_milestone(self.ledger, milestone_id, "bob")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "already_claimed")

    def test_release_milestone_wrong_owner_is_a_noop(self):
        milestone_id, _ = self._ready_milestone()
        self.assertTrue(self.ledger.mark_in_review(milestone_id))
        self.assertTrue(self.ledger.claim(milestone_id, "alice"))

        result = milestone_review.release_milestone(self.ledger, milestone_id, "bob")
        self.assertTrue(result.ok)
        self.assertIsNotNone(self.ledger.get_claim(milestone_id))
        self.assertEqual(self.ledger.get_claim(milestone_id).owner, "alice")

        result = milestone_review.release_milestone(self.ledger, milestone_id, "alice")
        self.assertTrue(result.ok)
        self.assertIsNone(self.ledger.get_claim(milestone_id))

    def test_concurrent_enter_review_has_exactly_one_winner(self):
        milestone_id, _ = self._ready_milestone()

        results = []

        def attempt():
            results.append(milestone_review.enter_review(self.ledger, milestone_id).ok)

        threads = [threading.Thread(target=attempt) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sum(1 for r in results if r), 1)
        self.assertEqual(self.ledger.get_work_item(milestone_id).status, "review")


class TestAcceptDecline(LedgerTestCase):
    """T020 (US4): accept()/decline() are guarded transitions that
    optionally record a rationale-locator evidence pointer only after
    the transition itself succeeds (FR-010), with the transition and the
    rationale recording as two separately committed operations
    (FR-010a)."""

    def _in_review_milestone(self, milestone_id="M-1", child_id="T-1"):
        self._ready_milestone(milestone_id, child_id)
        self.assertTrue(self.ledger.mark_in_review(milestone_id))
        return milestone_id, child_id

    def test_accept_and_decline_succeed_only_from_review(self):
        self._create_milestone("M-1")
        result = milestone_review.accept(self.ledger, "M-1")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_in_review")
        self.assertIsNone(result.rationale_error)

        result = milestone_review.decline(self.ledger, "M-1")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_in_review")
        self.assertIsNone(result.rationale_error)

    def test_not_found_and_not_a_milestone_guard(self):
        self._create_task("T-1")
        for fn in (milestone_review.accept, milestone_review.decline):
            with self.subTest(fn=fn.__name__, case="not_found"):
                result = fn(self.ledger, "does-not-exist")
                self.assertFalse(result.ok)
                self.assertEqual(result.reason, "not_found")
            with self.subTest(fn=fn.__name__, case="not_a_milestone"):
                result = fn(self.ledger, "T-1")
                self.assertFalse(result.ok)
                self.assertEqual(result.reason, "not_a_milestone")

    def test_evidence_locator_on_success_records_exactly_one_pointer(self):
        milestone_id, _ = self._in_review_milestone()
        result = milestone_review.accept(
            self.ledger, milestone_id, evidence_locator="docs/DECISIONS.md#D999",
            note="matches scope",
        )
        self.assertTrue(result.ok)
        self.assertIsNone(result.reason)
        self.assertIsNone(result.rationale_error)

        pointers = self.ledger.list_evidence(milestone_id)
        self.assertEqual(len(pointers), 1)
        self.assertEqual(pointers[0].kind, "other")
        self.assertEqual(pointers[0].value, "docs/DECISIONS.md#D999")
        self.assertEqual(pointers[0].note, "matches scope")

    def test_rejected_transition_records_zero_evidence_pointers(self):
        self._create_milestone("M-1")
        result = milestone_review.decline(
            self.ledger, "M-1", evidence_locator="docs/DECISIONS.md#D999"
        )
        self.assertFalse(result.ok)
        self.assertEqual(self.ledger.list_evidence("M-1"), [])

    def test_omitting_evidence_locator_records_nothing(self):
        milestone_id, _ = self._in_review_milestone()
        result = milestone_review.accept(self.ledger, milestone_id)
        self.assertTrue(result.ok)
        self.assertEqual(self.ledger.list_evidence(milestone_id), [])

    def test_accept_and_decline_succeed_regardless_of_claim(self):
        milestone_id, _ = self._in_review_milestone()
        self.assertIsNone(self.ledger.get_claim(milestone_id))
        result = milestone_review.accept(self.ledger, milestone_id)
        self.assertTrue(result.ok)

        milestone_id2, _ = self._in_review_milestone("M-2", "T-2")
        self.assertTrue(self.ledger.claim(milestone_id2, "someone-else"))
        result = milestone_review.decline(self.ledger, milestone_id2)
        self.assertTrue(result.ok)

    def test_decline_leaves_every_child_record_byte_identical(self):
        milestone_id, child_id = self._in_review_milestone()
        before_item = self.ledger.get_work_item(child_id)
        before_evidence = self.ledger.list_evidence(child_id)
        before_claim = self.ledger.get_claim(child_id)

        result = milestone_review.decline(
            self.ledger, milestone_id, evidence_locator="docs/DECISIONS.md#D1"
        )
        self.assertTrue(result.ok)
        self.assertEqual(self.ledger.get_work_item(milestone_id).status, "open")

        after_item = self.ledger.get_work_item(child_id)
        after_evidence = self.ledger.list_evidence(child_id)
        after_claim = self.ledger.get_claim(child_id)
        self.assertEqual(before_item, after_item)
        self.assertEqual(before_evidence, after_evidence)
        self.assertEqual(before_claim, after_claim)

    def test_concurrent_accept_has_exactly_one_winner(self):
        milestone_id, _ = self._in_review_milestone()
        results = []

        def attempt():
            results.append(milestone_review.accept(self.ledger, milestone_id).ok)

        threads = [threading.Thread(target=attempt) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sum(1 for r in results if r), 1)
        self.assertEqual(self.ledger.get_work_item(milestone_id).status, "accepted")

    def test_concurrent_decline_has_exactly_one_winner(self):
        milestone_id, _ = self._in_review_milestone()
        results = []

        def attempt():
            results.append(milestone_review.decline(self.ledger, milestone_id).ok)

        threads = [threading.Thread(target=attempt) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sum(1 for r in results if r), 1)
        self.assertEqual(self.ledger.get_work_item(milestone_id).status, "open")

    def test_rationale_recording_failure_leaves_transition_committed(self):
        milestone_id, _ = self._in_review_milestone()

        with mock.patch.object(
            self.ledger, "add_evidence", side_effect=RuntimeError("storage error")
        ):
            result = milestone_review.accept(
                self.ledger, milestone_id, evidence_locator="docs/DECISIONS.md#D1"
            )

        self.assertTrue(result.ok)
        self.assertIsNone(result.reason)
        self.assertIsNotNone(result.rationale_error)
        self.assertIn("storage error", result.rationale_error)
        self.assertEqual(self.ledger.get_work_item(milestone_id).status, "accepted")
        self.assertEqual(self.ledger.list_evidence(milestone_id), [])

    def test_rationale_recording_failure_on_decline_leaves_transition_committed(self):
        milestone_id, _ = self._in_review_milestone()

        with mock.patch.object(
            self.ledger, "add_evidence", side_effect=RuntimeError("storage error")
        ):
            result = milestone_review.decline(
                self.ledger, milestone_id, evidence_locator="docs/DECISIONS.md#D1"
            )

        self.assertTrue(result.ok)
        self.assertIsNone(result.reason)
        self.assertIsNotNone(result.rationale_error)
        self.assertEqual(self.ledger.get_work_item(milestone_id).status, "open")
        self.assertEqual(self.ledger.list_evidence(milestone_id), [])


class TestMilestoneOnlyGuard(LedgerTestCase):
    """T024 (US5): every function this module adds rejects a `task` id
    with `not_a_milestone` and leaves the task's own record, evidence,
    and claim state completely unchanged — the mirror of
    task-write-surface.md's "categorically rejected" milestone guard."""

    def test_every_function_rejects_a_task_id_without_side_effects(self):
        self._create_task("T-1")
        self.ledger.add_evidence("T-1", "commit", "abc")
        self.assertTrue(self.ledger.claim("T-1", "alice"))

        before_item = self.ledger.get_work_item("T-1")
        before_evidence = self.ledger.list_evidence("T-1")
        before_claim = self.ledger.get_claim("T-1")

        calls = (
            lambda: milestone_review.review_milestone(self.ledger, "T-1"),
            lambda: milestone_review.enter_review(self.ledger, "T-1"),
            lambda: milestone_review.claim_milestone(self.ledger, "T-1", "bob"),
            lambda: milestone_review.release_milestone(self.ledger, "T-1", "alice"),
            lambda: milestone_review.accept(self.ledger, "T-1"),
            lambda: milestone_review.decline(self.ledger, "T-1"),
        )
        for call in calls:
            with self.subTest(call=call):
                result = call()
                self.assertFalse(result.ok)
                self.assertEqual(result.reason, "not_a_milestone")

        self.assertEqual(self.ledger.get_work_item("T-1"), before_item)
        self.assertEqual(self.ledger.list_evidence("T-1"), before_evidence)
        self.assertEqual(self.ledger.get_claim("T-1"), before_claim)

    def test_list_milestones_never_includes_a_task_id(self):
        self._create_task("T-1")
        self._create_milestone("M-1")
        ids = [e.id for e in milestone_review.list_milestones(self.ledger)]
        self.assertNotIn("T-1", ids)
        self.assertIn("M-1", ids)


if __name__ == "__main__":
    unittest.main()
