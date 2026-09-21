"""Spec Kit `tasks.md` loader: idempotently loads one settled Spec Kit feature
directory's task decomposition into the durable work ledger.

Design and rationale: specs/003-symphony-task-integration/
(contracts/speckit-task-load.md). `load_feature()` is explicitly invoked (no
watcher, no Git hook), reads one `specs/NNN-slug/tasks.md` in the fixed line
shape specs/001 and specs/002 already use, and turns each parseable task line
into a `type='task'` `WorkLedger` work item. Reloads never duplicate a work
item, never disturb runtime-owned state (status, claim, evidence), and only add
`blocked_by` edges, never remove them.

Not a general Markdown parser: one fixed line shape, no extension point. It
never creates, moves, deletes, or archives a milestone or any other work item.
"""

from __future__ import annotations

import dataclasses
import os
import re
import sqlite3

from .work_ledger import WorkLedger, connect

# Line shape: ids may carry one lowercase suffix (`T016a`, seen in specs/002).
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

# Trailing "Depends on: T00X, T00Y." clause, split off from the description.
_DEPENDS_ON_RE = re.compile(
    r"""
    \s*Depends\ on:\s*
    (?P<ids>T\d{3}[a-z]?(?:\s*,\s*T\d{3}[a-z]?)*)
    \.\s*$
    """,
    re.VERBOSE,
)

# Title ends at `.!?` before whitespace/end, so `work_ledger.py` stays whole.
_SENTENCE_BOUNDARY_RE = re.compile(r"(.+?[.!?])(?:\s|$)")


class TasksFileError(RuntimeError):
    """Raised when `tasks.md` is missing, empty, taskless, or repeats an id.

    "Taskless" means no parseable task lines (T004). A duplicate id is reported
    before any work item is created or resynced, so nothing partially loads and
    no line silently overwrites another.
    """


class SourceIdentityConflictError(RuntimeError):
    """Raised when a task's deterministic id collides with foreign provenance.

    Own provenance means `source_kind = 'speckit_task'` and `source_locator`
    equal to `{feature_dir}/tasks.md#{task_id}`. Anything else (an
    `adhoc`/`plan` item, or another locator) is not an idempotent reload and is
    left byte-for-byte unchanged.
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
    """A skipped line (FR-011): checkbox-prefixed but not a valid task line.

    Headers, blank lines, and prose are ignored silently instead.
    """

    line_number: int
    text: str
    reason: str


@dataclasses.dataclass(frozen=True)
class UnresolvedDependency:
    """A `Depends on:` naming a task id absent from this `tasks.md` (FR-010)."""

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
    """`kind`: "task" (`task` set), "skip" (`reason` set), or "ignore"."""

    kind: str
    task: ParsedTaskLine | None = None
    reason: str | None = None


def _first_sentence(text: str) -> str:
    match = _SENTENCE_BOUNDARY_RE.match(text)
    return match.group(1) if match is not None else text


def _parse_line(line: str) -> _LineParseOutcome:
    """Parse one raw line of `tasks.md`."""
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

    `feature_dir` is relative to `ledger.repo_root` (e.g.
    `"specs/003-symphony-task-integration"`) and is stored unmodified in each
    task's `source_locator`.

    Raises `TasksFileError` when `tasks.md` is missing, empty, has no parseable
    task lines, or repeats a task id. Raises `SourceIdentityConflictError` when
    a deterministic id collides with a row of different provenance; that row is
    never mutated.

    Pass 1 creates each task's work item. On an id collision with matching
    provenance it calls `resync_declarative_fields()` only if
    `title`/`description` differ, so an unchanged reload leaves every row
    byte-for-byte unchanged (FR-006, SC-002) and an edited line re-syncs
    (FR-007). Status, claims, and evidence are never read or written.

    Pass 2 resolves `Depends on:` clauses against this file's ids and adds
    missing `blocked_by` edges, never removing any (FR-008); unknown ids land in
    `LoadResult.unresolved_dependencies` (FR-010). Two passes let a dependency
    resolve regardless of line order (FR-009).

    An unparseable line goes to `LoadResult.skipped` while the other lines still
    load (FR-011).
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
    first_seen_at: dict[str, int] = {}
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
        task_id = outcome.task.task_id
        if task_id in parsed:
            raise TasksFileError(
                f"{feature_dir}: tasks.md at {tasks_path!r} declares task "
                f"{task_id} more than once (line {first_seen_at[task_id]} "
                f"and line {line_number}); duplicate task ids are not "
                "loadable"
            )
        parsed[task_id] = outcome.task
        first_seen_at[task_id] = line_number

    if not parsed:
        raise TasksFileError(
            f"{feature_dir}: tasks.md at {tasks_path!r} contains no "
            "parseable task lines"
        )

    def _item_id(task_id: str) -> str:
        return f"speckit:{feature_dir_name}:{task_id}"

    # Pass 1: create or resync every task before resolving any dependency.
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
            if existing is None:
                continue
            if (
                existing.source_kind != "speckit_task"
                or existing.source_locator != source_locator
            ):
                raise SourceIdentityConflictError(
                    f"{item_id!r} already exists with source_kind="
                    f"{existing.source_kind!r}, source_locator="
                    f"{existing.source_locator!r}; this load's own task "
                    f"{task.task_id!r} from {feature_dir!r} expects "
                    f"source_kind='speckit_task', source_locator="
                    f"{source_locator!r} — refusing to treat this as a "
                    "reload of the same source"
                )
            if (
                existing.title != task.title
                or existing.description != task.description
            ):
                ledger.resync_declarative_fields(
                    item_id, task.title, task.description
                )
                resynced.append(item_id)

    # Pass 2: resolve "Depends on:" clauses, additive only.
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
