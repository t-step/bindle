"""Repository identity helper.

Implements the identity model described in docs/WORKTREES.md: repository
identity (the Git common directory), execution identity (the current
worktree root), and code-state identity (HEAD SHA plus branch/detached
state). Values come from `git rev-parse` rather than reimplementing Git's
own worktree resolution.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess


class NotAGitRepositoryError(RuntimeError):
    """Raised when the target directory is not inside a Git working tree."""


@dataclasses.dataclass(frozen=True)
class RepoInfo:
    repo_root: str
    worktree_root: str
    git_dir: str
    git_common_dir: str
    branch: str | None
    head_sha: str
    detached: bool


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _git(args: list[str], cwd: str) -> str:
    result = _run_git(args, cwd)
    if result.returncode != 0:
        raise NotAGitRepositoryError(f"not a Git repository: {cwd}")
    return result.stdout.strip()


def get_repo_info(cwd: str | None = None) -> RepoInfo:
    """Resolve repository/execution/code-state identity as seen from `cwd`."""
    cwd = os.path.realpath(cwd) if cwd else os.path.realpath(os.getcwd())

    worktree_root = os.path.realpath(_git(["rev-parse", "--show-toplevel"], cwd))
    git_dir = os.path.realpath(os.path.join(cwd, _git(["rev-parse", "--git-dir"], cwd)))
    git_common_dir = os.path.realpath(
        os.path.join(cwd, _git(["rev-parse", "--git-common-dir"], cwd))
    )
    head_sha = _git(["rev-parse", "HEAD"], cwd)

    # git-common-dir normally points at "<repo root>/.git", shared by every
    # linked worktree — that shared parent is the repository identity,
    # distinct from the worktree root of the checkout we were invoked from.
    if os.path.basename(git_common_dir) == ".git":
        repo_root = os.path.dirname(git_common_dir)
    else:
        repo_root = git_common_dir

    branch_result = _run_git(["symbolic-ref", "-q", "--short", "HEAD"], cwd)
    branch = branch_result.stdout.strip() or None

    return RepoInfo(
        repo_root=repo_root,
        worktree_root=worktree_root,
        git_dir=git_dir,
        git_common_dir=git_common_dir,
        branch=branch,
        head_sha=head_sha,
        detached=branch is None,
    )
