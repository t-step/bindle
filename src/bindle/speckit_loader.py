"""Spec Kit `tasks.md` loader: idempotently loads one settled Spec Kit
feature directory's task decomposition into the durable work ledger.

Implements the accepted design in specs/003-symphony-task-integration/
(spec.md, plan.md, research.md, data-model.md,
contracts/speckit-task-load.md) — read those first for the "why" behind
anything here. In short: `load_feature()` is a narrow, explicitly-invoked
operation (never a file watcher, never a Git hook) that reads exactly one
`specs/NNN-slug/tasks.md` file in the one line shape
`specs/001-durable-work-ledger/tasks.md` and
`specs/002-milestone-task-work-items/tasks.md` already use, and turns each
parseable task line into a `type='task'` `WorkLedger` work item —
idempotently, so a reload never duplicates a work item, never disturbs a
previously loaded task's runtime-owned state (status, claim, evidence),
and only ever adds a `blocked_by` edge, never removes one.

This module is not a general Markdown parser or workflow engine — it
recognizes exactly one fixed line shape (research.md's "Decision:
tasks.md line parsing strategy") and has no extension point for any
other. It never creates, moves, or deletes a milestone work item —
Spec Kit's own task lines have no milestone concept — and it never
deletes or archives a work item.
"""

from __future__ import annotations

import dataclasses
import os
import re
import sqlite3

from .work_ledger import WorkLedger, connect

# research.md's "Decision: tasks.md line parsing strategy": a task line is
# `- [ ]` or `- [x]` (checkbox state parsed but never surfaced as
# meaningful, per FR-012), a Spec Kit task id (`T\d{3}`, optionally suffixed
# with one lowercase letter — `T016a`, `T017a`, observed in
# specs/002-milestone-task-work-items/tasks.md), zero or more bracketed
# story tags (`[US1]`, `[P]`, ...), then free-text description.
_CHECKBOX_PREFIX_RE = re.compile(r"^-\s*\[[ xX]\]\s*")

_TASK_LINE_RE = re.compile(
    r"""
    ^-\s*\[[ xX]\]\s+                # checkbox, ignored (FR-012)
    (?P<task_id>T\d{3}[a-z]?)\s+     # Spec Kit task id
    (?:\[[^\]]*\]\s+)*               # zero or more bracketed tags, ignored
    (?P<rest>.+)$                    # description, plus an optional
                                      # trailing "Depends on:" clause
    """,
    re.VERBOSE,
)

# A "Depends on: T00X, T00Y." clause, always the trailing clause of a task
# line's free text — extracted separately from the description it trails.
_DEPENDS_ON_RE = re.compile(
    r"""
    \s*Depends\ on:\s*
    (?P<ids>T\d{3}[a-z]?(?:\s*,\s*T\d{3}[a-z]?)*)
    \.\s*$
    """,
    re.VERBOSE,
)

# `title` is the description text up to its first sentence boundary — a
# period/question mark/exclamation point followed by whitespace or the end
# of the text (data-model.md's "Loaded Task Work Item" table). Deliberately
# simple: a period not followed by whitespace-or-end (e.g. the one inside
# `work_ledger.py`) is not treated as a boundary, which is enough to avoid
# the most common false split (a file extension or module path) without
# building a real sentence tokenizer this feature does not need.
_SENTENCE_BOUNDARY_RE = re.compile(r"(.+?[.!?])(?:\s|$)")


class TasksFileError(RuntimeError):
    """Raised when a feature directory's `tasks.md` is missing or empty.

    spec.md's Edge Cases: "Loading is invoked against a feature directory
    whose tasks.md does not exist, or exists but is empty — the operation
    reports this clearly rather than silently creating zero work items
    with no explanation." Also raised when `tasks.md` exists and is
    non-empty but contains zero parseable task lines (T004) — from a
    caller's perspective this is the same "nothing to load, and here is
    why" outcome as a missing or genuinely empty file.
    """


@dataclasses.dataclass(frozen=True)
class ParsedTaskLine:
    """One successfully parsed task line from a `tasks.md` file."""

    task_id: str
    title: str
    description: str | None
    depends_on: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class SkippedLine:
    """One line reported as skipped rather than silently ignored (FR-011).

    Only a line that looks like it was *trying* to be a task line (starts
    with a `- [ ]`/`- [x]` checkbox) but does not fully match the expected
    shape is reported this way — a section header, blank line, or ordinary
    prose line is silently ignored instead, never reported.
    """

    line_number: int
    text: str
    reason: str


@dataclasses.dataclass(frozen=True)
class UnresolvedDependency:
    """A `Depends on:` reference naming a task id absent from this same
    `tasks.md` file (FR-010) — reported to the caller rather than silently
    discarded or silently recorded against a nonexistent work item."""

    task_id: str
    depends_on: str


@dataclasses.dataclass(frozen=True)
class LoadResult:
    """The outcome of one `load_feature()` invocation (contracts/speckit-task-load.md)."""

    feature_dir: str
    created: tuple[str, ...]
    resynced: tuple[str, ...]
    skipped: tuple[SkippedLine, ...]
    unresolved_dependencies: tuple[UnresolvedDependency, ...]


@dataclasses.dataclass(frozen=True)
class _LineParseOutcome:
    """Internal: the result of parsing one line of `tasks.md`.

    `kind` is one of `"task"` (successfully parsed — `task` is set),
    `"skip"` (looked like an attempted task line but did not fully match —
    `reason` is set), or `"ignore"` (ordinary non-task-line content —
    silently dropped, never reported).
    """

    kind: str
    task: ParsedTaskLine | None = None
    reason: str | None = None


def _first_sentence(text: str) -> str:
    match = _SENTENCE_BOUNDARY_RE.match(text)
    return match.group(1) if match is not None else text


def _parse_line(line: str) -> _LineParseOutcome:
    """Parse one raw line of `tasks.md` (research.md's "Decision:
    tasks.md line parsing strategy")."""
    stripped = line.strip()
    if not _CHECKBOX_PREFIX_RE.match(stripped):
        return _LineParseOutcome(kind="ignore")

    match = _TASK_LINE_RE.match(stripped)
    if match is None:
        return _LineParseOutcome(
            kind="skip",
            reason=(
                "line has a checkbox prefix but does not match the "
                "expected '- [ ] T### ...' task line shape"
            ),
        )

    task_id = match.group("task_id")
    rest = match.group("rest").strip()

    depends_on: tuple[str, ...] = ()
    depends_match = _DEPENDS_ON_RE.search(rest)
    if depends_match is not None:
        depends_on = tuple(
            dep.strip() for dep in depends_match.group("ids").split(",")
        )
        rest = rest[: depends_match.start()].rstrip()

    if not rest:
        return _LineParseOutcome(
            kind="skip",
            reason=f"task {task_id} has no description text",
        )

    title = _first_sentence(rest)
    description = rest if rest != title else None
    return _LineParseOutcome(
        kind="task",
        task=ParsedTaskLine(
            task_id=task_id,
            title=title,
            description=description,
            depends_on=depends_on,
        ),
    )


def _is_duplicate_key_error(exc: sqlite3.IntegrityError) -> bool:
    return exc.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY


def load_feature(
    ledger: WorkLedger,
    feature_dir: str,
    source_promoted_by: str | None = None,
) -> LoadResult:
    """Load one Spec Kit feature directory's `tasks.md` into the ledger.

    `feature_dir` is the feature directory's path relative to the
    repository root (`ledger.repo_root`) — e.g.
    `"specs/003-symphony-task-integration"` — exactly the value stored,
    unmodified, as the `{feature-directory-relative-path}` component of
    each loaded task's `source_locator` (data-model.md's "Source
    Reference"). `tasks.md` is read from
    `os.path.join(ledger.repo_root, feature_dir, "tasks.md")`.

    Raises `TasksFileError` when `tasks.md` does not exist, is empty, or
    contains zero parseable task lines (spec.md's Edge Cases, T004) —
    reported clearly rather than silently producing zero work items.

    Two passes within this one invocation (research.md's "Decision:
    dependency loading order within one feature directory"), so a
    dependency reference resolves correctly regardless of which line
    appears first in the file (FR-009):

    Pass 1 — for each parsed task line, attempt `create_work_item()`. A
    collision on the deterministic, source-derived `id` (a primary-key
    `sqlite3.IntegrityError`) means this task was already loaded by a
    prior invocation; in that case, the loader compares the existing
    row's `title`/`description` against the freshly parsed values and
    calls `resync_declarative_fields()` only when they actually differ —
    never unconditionally — so reloading an unchanged `tasks.md` leaves
    every existing row byte-for-byte unchanged (FR-006, SC-002), while a
    genuinely edited line's declarative text is re-synced on the next
    reload (FR-007). `status`, claims, and evidence are never read or
    written by this loader at all — `resync_declarative_fields()` itself
    has no path to any of them.

    Pass 2 — resolves every `Depends on:` clause against this same file's
    own derived ids and adds any `blocked_by` edge not already recorded,
    never removing one (FR-008). A dependency naming a task id absent
    from this same `tasks.md` is reported via `LoadResult.
    unresolved_dependencies` rather than silently discarded or silently
    recorded against a nonexistent work item (FR-010).

    A single unparseable line is reported via `LoadResult.skipped`, with
    every other well-formed line in the same file still loaded (FR-011) —
    this operation is not required to be all-or-nothing across a whole
    file.
    """
    tasks_path = os.path.join(ledger.repo_root, feature_dir, "tasks.md")
    if not os.path.isfile(tasks_path):
        raise TasksFileError(
            f"{feature_dir}: tasks.md not found at {tasks_path!r}"
        )

    with open(tasks_path, encoding="utf-8") as f:
        lines = f.readlines()

    feature_dir_name = os.path.basename(os.path.normpath(feature_dir))

    parsed: dict[str, ParsedTaskLine] = {}
    skipped: list[SkippedLine] = []
    for line_number, raw_line in enumerate(lines, start=1):
        outcome = _parse_line(raw_line)
        if outcome.kind == "ignore":
            continue
        if outcome.kind == "skip":
            skipped.append(
                SkippedLine(
                    line_number=line_number,
                    text=raw_line.rstrip("\n"),
                    reason=outcome.reason or "unparseable task line",
                )
            )
            continue
        assert outcome.task is not None
        parsed[outcome.task.task_id] = outcome.task

    if not parsed:
        raise TasksFileError(
            f"{feature_dir}: tasks.md at {tasks_path!r} contains no "
            "parseable task lines"
        )

    def _item_id(task_id: str) -> str:
        return f"speckit:{feature_dir_name}:{task_id}"

    # -- Pass 1: create or resync every parsed task's own work item -------
    created: list[str] = []
    resynced: list[str] = []
    for task in parsed.values():
        item_id = _item_id(task.task_id)
        source_locator = f"{feature_dir}/tasks.md#{task.task_id}"
        try:
            ledger.create_work_item(
                id=item_id,
                title=task.title,
                source_kind="speckit_task",
                source_locator=source_locator,
                source_promoted_by=source_promoted_by,
                description=task.description,
            )
            created.append(item_id)
        except sqlite3.IntegrityError as exc:
            if not _is_duplicate_key_error(exc):
                raise
            existing = ledger.get_work_item(item_id)
            if existing is not None and (
                existing.title != task.title
                or existing.description != task.description
            ):
                ledger.resync_declarative_fields(
                    item_id, task.title, task.description
                )
                resynced.append(item_id)

    # -- Pass 2: resolve every "Depends on:" clause, additive only --------
    conn = connect(ledger.repo_root)
    try:
        existing_edges = {
            task.task_id: {
                row[0]
                for row in conn.execute(
                    "SELECT blocked_on_id FROM work_item_blocked_by "
                    "WHERE work_item_id = ?",
                    (_item_id(task.task_id),),
                ).fetchall()
            }
            for task in parsed.values()
        }
    finally:
        conn.close()

    unresolved_dependencies: list[UnresolvedDependency] = []
    for task in parsed.values():
        item_id = _item_id(task.task_id)
        for dep_task_id in task.depends_on:
            if dep_task_id not in parsed:
                unresolved_dependencies.append(
                    UnresolvedDependency(
                        task_id=task.task_id, depends_on=dep_task_id
                    )
                )
                continue
            dep_id = _item_id(dep_task_id)
            if dep_id in existing_edges[task.task_id]:
                continue
            try:
                ledger.add_blocked_by(item_id, dep_id)
            except sqlite3.IntegrityError as exc:
                if not _is_duplicate_key_error(exc):
                    raise

    return LoadResult(
        feature_dir=feature_dir,
        created=tuple(created),
        resynced=tuple(resynced),
        skipped=tuple(skipped),
        unresolved_dependencies=tuple(unresolved_dependencies),
    )
