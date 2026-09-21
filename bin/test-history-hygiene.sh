#!/usr/bin/env bash
#
# test-history-hygiene.sh — regression suite for the history guardrails in
# src/bindle/_bin/git-hook-dispatch.sh (docs/DECISIONS.md D048): the
# commit-msg Conventional Commit check (with fixup!/squash!/amend!), the
# pre-push "history hygiene" report, and the `--history` on-demand mode.
#
# Every check runs against throwaway fixture repos under a private HOME
# (AGENTS.md "Runtime isolation"). Nothing is ever pushed: push checks use
# `git push --dry-run` against a local bare repo, which runs the real pre-push
# hook but sends nothing; the suite asserts that remote stays empty.
#
# Usage: bin/test-history-hygiene.sh
#
# shellcheck disable=SC2317,SC2329  # helpers below are invoked indirectly via check() (older shellcheck reports SC2317, newer SC2329)
set -uo pipefail

# Under a git hook, exported GIT_DIR would aim fixture git at the real repo.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$REPO_ROOT/src/bindle/_bin/install-guardrails.sh"
DISPATCH="$REPO_ROOT/src/bindle/_bin/git-hook-dispatch.sh"

pass=0 fail=0
check() { # check "description" command...
  local desc="$1"
  shift
  if "$@"; then
    printf '  ✓ %s\n' "$desc"
    pass=$((pass + 1))
  else
    printf '  ✗ %s\n' "$desc"
    fail=$((fail + 1))
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export BINDLE_GUARD_HOME="$TMP/guard-home"
export BINDLE_CLAUDE_HOME="$TMP/claude-home"
export HOME="$TMP/fake-home"
mkdir -p "$HOME"
git config --global user.email "test@example.com"
git config --global user.name "Test"
git config --global init.defaultBranch main
# A rebase/revert/merge/--fixup=amend: must never wait on an editor.
export GIT_EDITOR=true GIT_SEQUENCE_EDITOR=true

ZEROS=0000000000000000000000000000000000000000
R=""   # the fixture repository (or linked worktree) the helpers operate on
OUT="" # combined stdout+stderr of the last run_* call
RC=0   # its exit status

# new_repo DIR [nocog] — a repo on main with one conventional commit, a
# tracked cog.toml (which is what declares Conventional Commits) unless
# "nocog", and the Bindle Git guardrails installed. Sets R.
new_repo() {
  local dir="$1" mode="${2:-cog}"
  rm -rf "$dir"
  git init -q --initial-branch=main "$dir"
  git -C "$dir" config user.email test@example.com
  git -C "$dir" config user.name Test
  echo readme >"$dir/README.md"
  if [ "$mode" = cog ]; then
    printf '[commit_types]\nchore = { changelog_title = "Maintenance" }\nwibble = { changelog_title = "Custom" }\n' >"$dir/cog.toml"
  fi
  git -C "$dir" add -A
  git -C "$dir" commit -q -m "chore: init"
  "$INSTALLER" --apply --git-only --repo "$dir" >/dev/null 2>&1
  R="$dir"
}

# commit_file MSG FILE LINES [git-commit args...] — append LINES distinct
# lines to FILE and commit with -m MSG. Exit status is git commit's.
commit_file() {
  local msg="$1" file="$2" lines="$3" i
  shift 3
  mkdir -p "$(dirname "$R/$file")"
  for ((i = 0; i < lines; i++)); do echo "$file $RANDOM$RANDOM"; done >>"$R/$file"
  git -C "$R" add "$file"
  git -C "$R" commit -q -m "$msg" "$@" >/dev/null 2>&1
}

# commit_raw FILE git-commit-args... — append one line to FILE, then commit
# with exactly the given arguments (for --fixup=…/--squash=… forms).
commit_raw() {
  local file="$1"
  shift
  echo "$RANDOM$RANDOM" >>"$R/$file"
  git -C "$R" add "$file"
  git -C "$R" commit -q "$@" >/dev/null 2>&1
}

commit_ok() { commit_file "$1" f.txt 12 "${@:2}"; }

# commit_rejected MSG — the commit fails AND HEAD did not move.
commit_rejected() {
  local before
  before="$(git -C "$R" rev-parse HEAD)"
  if commit_file "$1" f.txt 12 "${@:2}"; then return 1; fi
  [ "$before" = "$(git -C "$R" rev-parse HEAD)" ]
}

# discard_pending — throw away whatever a rejected commit left staged.
discard_pending() {
  git -C "$R" reset -q --hard HEAD
  git -C "$R" clean -fdq
}

run_hist() { # run_hist [args...] — the on-demand report for $R
  OUT="$(cd "$R" && bash "$DISPATCH" --history "$@" 2>&1)"
  RC=$?
}

# run_pre_push BRANCH [WORKDIR] — invoke the installed pre-push hook exactly
# as git does (ref list on stdin, remote name + URL as args). Sends nothing.
run_pre_push() {
  local br="$1" wd="${2:-$R}" sha hook
  sha="$(git -C "$wd" rev-parse "refs/heads/$br")"
  hook="$(git -C "$wd" rev-parse --path-format=absolute --git-common-dir)/bindle-hooks/pre-push"
  OUT="$(cd "$wd" && printf 'refs/heads/%s %s refs/heads/%s %s\n' "$br" "$sha" "$br" "$ZEROS" | "$hook" origin file:///nowhere 2>&1)"
  RC=$?
}

has() { grep -qF -- "$1" <<<"$OUT"; }
has_re() { grep -qE -- "$1" <<<"$OUT"; }
lacks() { ! has "$1"; }
lacks_re() { ! has_re "$1"; }
rc_is() { [ "$RC" -eq "$1" ]; }
info_count() { grep -c '^INFO' <<<"$OUT" || true; }
no_shell_errors() { ! grep -qiE 'unbound|syntax error|command not found|: line [0-9]+:' <<<"$OUT"; }
hook_path() { printf '%s/bindle-hooks/%s' "$(git -C "$R" rev-parse --path-format=absolute --git-common-dir)" "$1"; }

echo "commit-msg: Conventional Commit subjects"
new_repo "$TMP/cc"
git -C "$R" switch -q -c feat/msgs

check "valid: type(scope): description" commit_ok "feat(search): add filtering"
check "valid: type: description (no scope)" commit_ok "fix: handle timeout"
check "valid: breaking-change marker" commit_ok "refactor(auth)!: simplify token handling"
check "valid: a type added under cog.toml [commit_types]" commit_ok "wibble: custom type"
check "valid: test type" commit_ok "test(search): add empty-state coverage"

check "invalid: prose subject is rejected and HEAD does not move" commit_rejected "add filtering"
check "invalid: missing colon is rejected" commit_rejected "feat add filtering"
check "invalid: unknown type is rejected" commit_rejected "wip: half done"
check "invalid: capitalised type is rejected" commit_rejected "Feat: add filtering"
check "invalid: empty description is rejected" commit_rejected "feat:"
check "invalid: empty scope is rejected" commit_rejected "feat(): add filtering"
discard_pending
echo z >>"$R/f.txt"
git -C "$R" add f.txt
OUT="$(git -C "$R" commit -q -m "nope" 2>&1)"
check "the rejection message shows the expected format" has "expected: type(optional-scope): description"
check "the rejection message lists the cog.toml-extended types" has "wibble"
check "the rejection message names the fixup convention" has "git commit --fixup=<target>"
discard_pending

echo "commit-msg: fixup!/squash!/amend! control commits"
target="$(git -C "$R" rev-parse HEAD)"
before_count="$(git -C "$R" rev-list --count main..HEAD)"
check "fixup! subject (literal) is allowed" commit_ok "fixup! test(search): add empty-state coverage"
check "squash! subject (literal) is allowed" commit_ok "squash! test(search): add empty-state coverage"
check "amend! subject (literal) is allowed" commit_ok "amend! test(search): add empty-state coverage"
check "git commit --fixup=<sha> is allowed" commit_raw f.txt --fixup="$target"
check "git commit --squash=<sha> is allowed" commit_raw f.txt --squash="$target" -m "more detail"
check "git commit --fixup=amend:<sha> is allowed" commit_raw f.txt --fixup="amend:$target"
check "…and all six really are autosquash subjects" bash -c \
  "git -C '$R' log -6 --format=%s | grep -cE '^(fixup|squash|amend)! ' | grep -qx 6"
check "…on top of the $before_count ordinary commits" bash -c \
  "[ \"\$(git -C '$R' rev-list --count main..HEAD)\" -eq $((before_count + 6)) ]"
check "a stacked prefix (fixup! fixup! …) is allowed" commit_ok "fixup! fixup! test(search): add empty-state coverage"
check "a bare 'fixup!' with no target is still rejected" commit_rejected "fixup!"
discard_pending

echo "commit-msg: other Git-generated subjects"
new_repo "$TMP/gen"
git -C "$R" switch -q -c feat/gen
commit_ok "feat: something to revert" >/dev/null
check "git revert (subject: Revert \"…\") is allowed" git -C "$R" revert --no-edit HEAD
check "reverting that revert (subject: Reapply \"…\") is allowed" git -C "$R" revert --no-edit HEAD
check "…and Git really did generate a Reapply subject" bash -c "git -C '$R' log -1 --format=%s | grep -q '^Reapply \"'"
git -C "$R" switch -q -c side main
commit_file "feat(side): side work" side.txt 12 >/dev/null
git -C "$R" switch -q feat/gen
check "a merge commit (subject: Merge …) is allowed" git -C "$R" merge --no-ff -q -m "Merge branch 'side' into feat/gen" side

check "amending an existing merge commit (subject kept) is allowed" bash -c "
  cd '$R' && git commit --amend --no-edit >/dev/null 2>&1"
check "'Merge …' with no merge in progress is NOT exempt" commit_rejected "Merge quick hack"
check "'Revert \"x\" and more' (not the shape git revert generates) is NOT exempt" commit_rejected 'Revert "wip" and more'

echo "commit-msg: the convention is opt-in per repository"
new_repo "$TMP/nocog" nocog
git -C "$R" switch -q -c feat/plain
check "no cog.toml: a prose message is not policed" commit_ok "just some words"
check "no cog.toml: fixup! is not policed either" commit_ok "fixup! just some words"
printf '[commit_types]\n' >"$R/cog.toml"
check "an UNTRACKED cog.toml does not opt the repository in" commit_ok "still just words"
git -C "$R" add cog.toml
check "once cog.toml is tracked (staged), the convention applies" commit_rejected "more words"
git -C "$R" rm -q --cached cog.toml
rm -f "$R/cog.toml"
git -C "$R" config bindle.conventionalCommits true
check "bindle.conventionalCommits=true turns it on without cog.toml" commit_rejected "just some words"
check "…and a conventional subject still passes" commit_ok "feat: fine"
discard_pending
R="$TMP/cc"
git -C "$R" config bindle.conventionalCommits false
check "bindle.conventionalCommits=false turns it off despite cog.toml" commit_ok "just some words"
git -C "$R" config --unset bindle.conventionalCommits

echo "commit-msg: composition with a repository-native commit-msg hook"
new_repo "$TMP/native"
git -C "$R" switch -q -c feat/native
cat >"$R/.git/hooks/commit-msg" <<'HOOK'
#!/bin/sh
# fixture-native hook: demands a marker in the message
grep -q NATIVE-OK "$1"
HOOK
chmod +x "$R/.git/hooks/commit-msg"
check "a conventional subject the native hook dislikes is still rejected" commit_rejected "feat: no marker"
check "a conventional subject with the marker passes both" commit_ok "feat: with marker NATIVE-OK"
check "fixup! skips the native hook (cog verify cannot parse it)" commit_ok "fixup! feat: no marker here"
check "an invalid subject is rejected before the native hook is consulted" commit_rejected "prose NATIVE-OK"

if command -v cog >/dev/null 2>&1; then
  new_repo "$TMP/realcog"
  git -C "$R" switch -q -c feat/cog
  # shellcheck disable=SC2016  # "$1" is meant literally: it is the hook's own argument
  printf '#!/bin/sh\ncog verify --file "$1"\n' >"$R/.git/hooks/commit-msg"
  chmod +x "$R/.git/hooks/commit-msg"
  check "with the real cog hook: a conventional commit passes" commit_ok "feat: real cog"
  check "with the real cog hook: fixup! passes (dispatcher skips cog)" commit_ok "fixup! feat: real cog"
  check "with the real cog hook: an invalid subject is rejected" commit_rejected "prose"
else
  printf '  - cog not installed: real-cog composition checks skipped\n'
fi

echo "protected main, linked worktrees, detached HEAD"
new_repo "$TMP/main1"
echo x >"$R/f2.txt"
git -C "$R" add f2.txt
OUT="$(git -C "$R" commit -q -m "feat: valid message, wrong branch" 2>&1)"
RC=$?
check "commit directly on main is rejected even with a valid message" rc_is 1
check "…by the protected-main guard" has "'main' is protected"
discard_pending

W="$TMP/main1-wt"
git -C "$R" worktree add -q -b feat/wt "$W" main
check "the guardrails apply from a linked worktree (shared common dir)" bash -c \
  "[ \"\$(git -C '$W' config --get core.hooksPath)\" = \"\$(git -C '$R' rev-parse --path-format=absolute --git-common-dir)/bindle-hooks\" ]"
PRIMARY="$R"
R="$W"
check "linked worktree: valid commit allowed" commit_ok "feat(wt): from a worktree"
check "linked worktree: invalid commit rejected" commit_rejected "prose from worktree"
discard_pending
check "linked worktree: fixup! allowed" commit_ok "fixup! feat(wt): from a worktree"
git -C "$PRIMARY" config bindle.hygiene.tinyLines 1000
run_hist
check "linked worktree: --history BLOCKs the pending fixup" has "BLOCK  1 pending fixup"
check "linked worktree: --history names the worktree's branch" has "feat/wt vs main"
check "linked worktree: config set from the primary checkout applies" has "2/2 commits change fewer than 1000 lines"
check "linked worktree: --history exits 1 on BLOCK" rc_is 1
run_pre_push feat/wt "$W"
check "linked worktree: pre-push BLOCKs the pending fixup" rc_is 1
git -C "$PRIMARY" config --unset bindle.hygiene.tinyLines
R="$PRIMARY"
echo y >"$R/f3.txt"
git -C "$R" add f3.txt
check "the primary checkout on main is still protected afterwards" bash -c \
  "! git -C '$R' commit -q -m 'feat: on main again' >/dev/null 2>&1"
discard_pending

new_repo "$TMP/detached"
git -C "$R" switch -q --detach main
check "detached HEAD at main's tip: a conventional commit is allowed" commit_ok "feat: detached work"
check "detached HEAD: an invalid message is still rejected" commit_rejected "prose"
discard_pending
run_hist
check "detached HEAD: --history exits 0" rc_is 0
check "detached HEAD: the header says so" has "detached HEAD ("
check "detached HEAD: no shell error leaked" no_shell_errors
OUT="$(cd "$R" && bash "$DISPATCH" --history no-such-ref 2>&1)"
RC=$?
check "an unresolvable ref is a usage error (exit 2), not a crash" rc_is 2
check "…with a message" has "cannot resolve 'no-such-ref'"

echo "pre-push: pending autosquash commits are a hard failure"
new_repo "$TMP/push"
git -C "$R" switch -q -c feat/p
commit_file "feat(p): first" a.txt 12 >/dev/null
first_sha="$(git -C "$R" rev-parse HEAD)"
commit_file "feat(p): second" b.txt 12 >/dev/null
second_sha="$(git -C "$R" rev-parse HEAD)"
# Distinct files per target, so reordering under autosquash cannot conflict.
commit_raw a.txt -m "detail" --fixup="$first_sha" >/dev/null
commit_raw b.txt --squash="$second_sha" -m "squash detail" >/dev/null
commit_raw b.txt --fixup="amend:$second_sha" >/dev/null
run_pre_push feat/p
check "3 pending fixup!/squash!/amend! commits: push rejected" rc_is 1
check "the report counts them" has "BLOCK  3 pending fixup!/squash!/amend! commits"
check "the report lists them" has "fixup! feat(p): first"
check "the report says how to fold them" has "GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash"
check "the hook did not rewrite anything: all 5 commits still there" bash -c \
  "[ \"\$(git -C '$R' rev-list --count main..feat/p)\" -eq 5 ]"

fold_cmd="$(sed -n 's/.*fold them: //p' <<<"$OUT")"
check "the printed fold command succeeds (autosquash rebase works under the hooks)" bash -c \
  "cd '$R' && $fold_cmd >/dev/null 2>&1"
check "after autosquash: 2 commits remain, none an autosquash commit" bash -c \
  "[ \"\$(git -C '$R' rev-list --count main..feat/p)\" -eq 2 ] && ! git -C '$R' log --format=%s main..feat/p | grep -qE '^(fixup|squash|amend)! '"
run_pre_push feat/p
check "after autosquash: push is allowed" rc_is 0
check "after autosquash: PASS for pending autosquash commits" has "PASS   no pending fixup!/squash!/amend! commits"
check "after autosquash: PASS for Conventional Commit syntax" has "PASS   Conventional Commit syntax"

echo "pre-push: the fold hint keeps merge commits"
new_repo "$TMP/foldm"
git -C "$R" switch -q -c feat/fm
commit_file "feat(fm): a" a.txt 12 >/dev/null
fm_a="$(git -C "$R" rev-parse HEAD)"
git -C "$R" switch -q main
check "(fixture) main moves on" bash -c \
  "cd '$R' && echo m >m.txt && git add m.txt && ALLOW_MAIN_WRITE=1 git commit -q -m 'chore: main moved'"
git -C "$R" switch -q feat/fm
git -C "$R" merge --no-ff -q -m "Merge branch 'main' into feat/fm" main
commit_raw a.txt --fixup="$fm_a" >/dev/null
run_pre_push feat/fm
check "the hint for a branch with a merge commit says --rebase-merges" has "rebase -i --autosquash --rebase-merges"
fold_cmd="$(sed -n 's/.*fold them: //p' <<<"$OUT")"
check "…and running it succeeds" bash -c "cd '$R' && $fold_cmd >/dev/null 2>&1"
check "…keeps the merge commit" bash -c "[ \"\$(git -C '$R' rev-list --merges --count main..feat/fm)\" -eq 1 ]"
check "…does not replay main's commit a second time" bash -c \
  "[ \"\$(git -C '$R' log --format=%s feat/fm | grep -c 'chore: main moved')\" -eq 1 ]"
check "…and leaves no autosquash commit" bash -c \
  "! git -C '$R' log --format=%s main..feat/fm | grep -qE '^(fixup|squash|amend)! '"

echo "pre-push: clean history"
new_repo "$TMP/clean"
git -C "$R" switch -q -c feat/clean
commit_file "feat(a): add a" src/a.py 30 >/dev/null
commit_file "fix(a): handle empty input" src/b.py 25 >/dev/null
run_pre_push feat/clean
check "clean Conventional history: push allowed" rc_is 0
check "clean history: no BLOCK line" lacks "BLOCK"

echo "pre-push: non-conforming subjects that bypassed commit-msg"
new_repo "$TMP/bypass"
git -C "$R" switch -q -c feat/b
commit_ok "feat: good" >/dev/null
check "--no-verify lets a prose commit through commit-msg" commit_ok "sneaky prose" --no-verify
run_pre_push feat/b
check "…but pre-push BLOCKs it" rc_is 1
check "…and counts it" has "BLOCK  1 commit without a Conventional Commit subject"
commit_ok "Merge stuff" --no-verify >/dev/null
run_pre_push feat/b
check "a NON-merge commit that merely says 'Merge …' is counted at push time" has "BLOCK  2 commits without a Conventional Commit subject"
git -C "$R" reset -q --hard HEAD~1
run_pre_push feat/b
git -C "$R" config bindle.conventionalCommits false
run_pre_push feat/b
check "a repo that opted out of the convention is not blocked for prose" rc_is 0
check "…and no syntax line is printed for it" lacks "Conventional Commit syntax"
check "…but a pending fixup! is a BLOCK everywhere, opted out or not" bash -c "
  cd '$R' && echo q >>f.txt && git add f.txt && git commit -q -m 'fixup! whatever' &&
  hook='$(hook_path pre-push)' &&
  ! (printf 'refs/heads/feat/b %s refs/heads/feat/b $ZEROS\n' \"\$(git rev-parse HEAD)\" | \"\$hook\" origin url) >/dev/null 2>&1"

echo "pre-push: what is (not) inspected, and base resolution"
new_repo "$TMP/refs"
git -C "$R" switch -q -c feat/r
commit_ok "fixup! feat: dangling" >/dev/null
hook="$(hook_path pre-push)"
sha="$(git -C "$R" rev-parse HEAD)"
check "a branch deletion (all-zero local sha) is never inspected" bash -c \
  "cd '$R' && printf 'refs/heads/feat/r $ZEROS refs/heads/feat/r $sha\n' | '$hook' origin url"
check "a tag push is never inspected" bash -c \
  "cd '$R' && printf 'refs/tags/v1 $sha refs/tags/v1 $ZEROS\n' | '$hook' origin url"
check "an empty push (no ref lines) is allowed" bash -c "cd '$R' && '$hook' origin url </dev/null"
git -C "$R" switch -q main
OUT="$(cd "$R" && printf 'refs/heads/feat/r %s refs/heads/feat/r %s\n' "$sha" "$ZEROS" | "$hook" origin url 2>&1)"
RC=$?
check "pushing a branch that is not checked out is judged by the pushed ref, not HEAD" rc_is 1
check "…and the fold hint names that branch" has_re 'rebase -i --autosquash [0-9a-f]+ feat/r$'
git -C "$R" branch -q other main
OUT="$(cd "$R" && printf 'HEAD %s refs/heads/other %s\n' "$sha" "$ZEROS" | "$hook" origin url 2>&1)"
RC=$?
check "pushing HEAD:refs/heads/other is still refused" rc_is 1
check "…and the hint does NOT name the unrelated local branch 'other'" lacks_re 'autosquash [0-9a-f]+ other$'
check "…but does name the checked-out branch's history (no branch argument)" has_re 'autosquash [0-9a-f]+$'
git -C "$R" switch -q feat/r
git -C "$R" branch -q -m main trunk
run_hist
check "no resolvable base ref: says 'skipped' instead of guessing" has "skipped: no base ref"
check "…and exits 0" rc_is 0
git -C "$R" config bindle.historyBase trunk
run_hist
check "bindle.historyBase points the report at a differently-named base" has "vs trunk"
git -C "$R" config --unset bindle.historyBase
run_hist --base trunk
check "--base REF overrides for one run" has "vs trunk"

echo "pre-push: fails CLOSED when the history cannot be read"
new_repo "$TMP/closed"
git -C "$R" switch -q -c feat/closed
commit_ok "feat: ok" >/dev/null
hook="$(hook_path pre-push)"
OUT="$(cd "$R" && printf 'refs/heads/feat/closed %s refs/heads/feat/closed %s\n' 1111111111111111111111111111111111111111 "$ZEROS" | "$hook" origin url 2>&1)"
RC=$?
check "a pushed sha git cannot resolve is a BLOCK, not a silent pass" rc_is 1
check "…says why" has "cannot read the history"
check "…and prints no PASS line for a history it could not read" lacks "PASS  "

echo "pre-push: composition with a repository-native pre-push hook"
new_repo "$TMP/nativepush"
git -C "$R" switch -q -c feat/np
commit_ok "feat: ok" >/dev/null
cat >"$R/.git/hooks/pre-push" <<HOOK
#!/bin/sh
{ echo "args:\$*"; cat; } >"$TMP/native-pre-push.out"
HOOK
chmod +x "$R/.git/hooks/pre-push"
run_pre_push feat/np
check "the native pre-push hook still runs on a clean push" rc_is 0
check "…receives the remote name and URL" grep -q 'args:origin file:///nowhere' "$TMP/native-pre-push.out"
check "…and still receives the ref list on stdin (the dispatcher replays it)" \
  grep -q "^refs/heads/feat/np $(git -C "$R" rev-parse feat/np) refs/heads/feat/np $ZEROS\$" "$TMP/native-pre-push.out"
rm -f "$TMP/native-pre-push.out"
commit_ok "fixup! feat: ok" >/dev/null
run_pre_push feat/np
check "a BLOCKed push never reaches the native hook" bash -c "[ ! -e '$TMP/native-pre-push.out' ]"
git -C "$R" reset -q --hard HEAD~1
hook="$(hook_path pre-push)"
: >"$TMP/empty.in"
rm -f "$TMP/native-pre-push.out"
(cd "$R" && "$hook" origin url <"$TMP/empty.in") >/dev/null 2>&1
check "an EMPTY ref list reaches the native hook as zero bytes (not a blank line)" bash -c \
  "[ \"\$(tail -n +2 '$TMP/native-pre-push.out' | wc -c | tr -d ' ')\" -eq 0 ]"
printf 'refs/tags/a %s refs/tags/a %s\nrefs/tags/b %s refs/tags/b %s\n' "$ZEROS" "$ZEROS" "$ZEROS" "$ZEROS" >"$TMP/tags.in"
(cd "$R" && "$hook" origin url <"$TMP/tags.in") >/dev/null 2>&1
tail -n +2 "$TMP/native-pre-push.out" >"$TMP/tags.out"
check "a multi-line ref list is replayed byte-for-byte" cmp -s "$TMP/tags.in" "$TMP/tags.out"

echo "pre-push: end-to-end through git push --dry-run (nothing is sent)"
new_repo "$TMP/e2e"
git init -q --bare "$TMP/e2e-remote.git"
git -C "$R" remote add origin "$TMP/e2e-remote.git"
git -C "$R" switch -q -c feat/e2e
commit_ok "feat: one" >/dev/null
commit_ok "fixup! feat: one" >/dev/null
check "git push --dry-run is refused while a fixup! is pending" bash -c \
  "cd '$R' && ! git push --dry-run origin feat/e2e >/dev/null 2>&1"
check "…with the report on stderr" bash -c \
  "cd '$R' && git push --dry-run origin feat/e2e 2>&1 | grep -q 'BLOCK  1 pending fixup'"
e2e_sha="$(git -C "$R" rev-parse HEAD)"
check "git push --dry-run origin HEAD is refused (local ref arrives as the literal 'HEAD')" bash -c \
  "cd '$R' && ! git push --dry-run origin HEAD >/dev/null 2>&1"
check "git push --dry-run origin HEAD:refs/heads/other is refused" bash -c \
  "cd '$R' && ! git push --dry-run origin HEAD:refs/heads/other >/dev/null 2>&1"
check "git push --dry-run origin <sha>:refs/heads/other is refused" bash -c \
  "cd '$R' && ! git push --dry-run origin $e2e_sha:refs/heads/other >/dev/null 2>&1"
check "detached HEAD: pushing HEAD:refs/heads/other is refused too" bash -c \
  "cd '$R' && git switch -q --detach && ! git push --dry-run origin HEAD:refs/heads/other >/dev/null 2>&1; git switch -q feat/e2e"
check "a tag push is not inspected even with a pending fixup on the branch" bash -c \
  "cd '$R' && git tag v0 && git push --dry-run origin v0 >/dev/null 2>&1"
git -C "$R" tag -d v0 >/dev/null
git -C "$R" reset -q --hard HEAD~1
check "…and the same HEAD forms go through once the history is clean" bash -c \
  "cd '$R' && git push --dry-run origin HEAD >/dev/null 2>&1 && git push --dry-run origin HEAD:refs/heads/other >/dev/null 2>&1"
check "git push --dry-run goes through once the history is clean" bash -c \
  "cd '$R' && git push --dry-run origin feat/e2e >/dev/null 2>&1"
check "…and the throwaway remote never received anything" bash -c \
  "[ \"\$(git -C '$TMP/e2e-remote.git' for-each-ref | wc -l | tr -d ' ')\" -eq 0 ]"

echo "advisory signals are warnings only (never blockers)"
new_repo "$TMP/sig"
git -C "$R" switch -q -c feat/sig
commit_file "feat(core): add engine" src/engine.py 30 >/dev/null          # not tiny
commit_file "fix(core): fix typo in engine" src/engine.py 1 >/dev/null    # tiny + rework-shaped
commit_file "test(core): add engine tests" tests/test_engine.py 20 >/dev/null # test-only
commit_file "chore: cleanup imports" src/engine.py 12 >/dev/null         # rework-shaped
commit_file "chore: bump lock" uv.lock 12 >/dev/null                      # generated
commit_file "chore: bump lock again" uv.lock 12 >/dev/null                # generated, again
# Touches a test AND a source file: must NOT count as test-only.
mkdir -p "$R/tests"
for ((i = 0; i < 15; i++)); do echo "t $i"; done >>"$R/tests/test_engine.py"
for ((i = 0; i < 15; i++)); do echo "s $i"; done >>"$R/src/engine.py"
git -C "$R" add -A
git -C "$R" commit -q -m "feat(core): add flag" >/dev/null 2>&1
git -C "$R" config bindle.hygiene.repeatCommits 3
run_pre_push feat/sig
check "pre-push: warnings only → push allowed" rc_is 0
check "pre-push: no BLOCK line" lacks "BLOCK"
check "header counts commits" has "History hygiene: feat/sig vs main (7 commits, 0 merge)"
check "tiny commits: exactly 1 of 7 (fewer than 10 lines)" has "WARN   1/7 commits change fewer than 10 lines"
check "rework-shaped subjects: 'fix typo…' and 'cleanup imports' → 2" has "WARN   2 commits with corrective/rework-shaped subjects"
check "test-only commits: exactly the one touching only tests/" has "WARN   1/7 test-only commits"
check "generated-file churn: uv.lock changed in 2 commits" has "WARN   generated/lockfile uv.lock changed in 2 commits"
check "repeatedly touched file: src/engine.py in 4 commits" has "INFO   src/engine.py changed in 4 commits"
check "the lockfile is not double-reported as a repeatedly-touched file" lacks "INFO   uv.lock"
check "Conventional Commit syntax still PASSes" has "PASS   Conventional Commit syntax"

git -C "$R" config bindle.hygiene.tinyLines 1
run_hist
check "tinyLines=1: a 1-line commit is not 'fewer than 1 line'" lacks "commits change fewer than"
check "--history exits 0 with warnings only" rc_is 0
git -C "$R" config bindle.hygiene.tinyLines 10
git -C "$R" config bindle.hygiene.repeatCommits 5
run_hist
check "repeatCommits=5: the 4-commit file drops out of the INFO list" lacks "INFO   src/engine.py"
git -C "$R" config bindle.hygiene.testPattern '^nomatch/'
run_hist
check "testPattern override: nothing matches → no test-only warning" lacks "test-only"
git -C "$R" config --unset bindle.hygiene.testPattern
git -C "$R" config bindle.hygiene.generatedPattern '^nomatch$'
run_hist
check "generatedPattern override: uv.lock no longer reported as generated" lacks "generated/lockfile"

echo "advisory signals: merge commits"
new_repo "$TMP/merge"
git -C "$R" switch -q -c feat/m
commit_ok "feat: on the branch" >/dev/null
git -C "$R" switch -q main
check "(fixture) a commit lands on main under the explicit override" bash -c \
  "cd '$R' && echo m >m.txt && git add m.txt && ALLOW_MAIN_WRITE=1 git commit -q -m 'chore: main moved'"
git -C "$R" switch -q feat/m
check "(fixture) merge main into the feature branch" git -C "$R" merge --no-ff -q -m "Merge branch 'main' into feat/m" main
run_pre_push feat/m
check "a merge commit on the branch: push still allowed (this repo lands PRs as merge commits)" rc_is 0
check "…reported as a warning" has "WARN   1 merge commit present on feature branch"
check "…and not as a BLOCK" lacks "BLOCK"
check "the merge commit itself is not counted among the tiny/test-only commits" lacks "commits change fewer than"

echo "advisory signals: reverts and exact patch repeats"
new_repo "$TMP/rev"
git -C "$R" switch -q -c feat/rev
commit_file "feat: add widget" widget.txt 12 >/dev/null
git -C "$R" revert --no-edit HEAD >/dev/null 2>&1
git -C "$R" checkout -q HEAD~1 -- widget.txt # the reverted commit's exact content
git -C "$R" commit -q -m "feat: add widget again" >/dev/null 2>&1
run_hist
check "an explicit revert commit is counted" has "WARN   1 explicit revert commit"
check "exact re-application of the reverted patch is found via patch-id" has "exact patch repeats (same git patch-id as an earlier commit): 1"
check "reverts and repeats are warnings only" rc_is 0

echo "advisory signals: an empty commit is not 'test-only'"
new_repo "$TMP/empty"
git -C "$R" switch -q -c feat/empty
git -C "$R" commit -q --allow-empty -m "chore: empty" >/dev/null 2>&1
run_hist
check "a commit that changes no files is not counted as test-only (all-of-zero-files is vacuous)" lacks "test-only"
check "…but it is factually a commit that changes fewer than 10 lines" has "WARN   1/1 commits change fewer than 10 lines"

echo "advisory signals: binary changes are never 'tiny'; INFO lists at most 3 files"
new_repo "$TMP/bin"
git -C "$R" switch -q -c feat/bin
printf '\000\001\002' >"$R/blob.bin"
git -C "$R" add blob.bin
git -C "$R" commit -q -m "feat: add blob" >/dev/null 2>&1
run_hist
check "a binary-only commit has no countable lines but is not called tiny" lacks "commits change fewer than"
new_repo "$TMP/many"
git -C "$R" switch -q -c feat/many
for n in 1 2; do
  for f in a b c d; do echo "$n" >>"$R/$f.txt"; done
  git -C "$R" add -A
  git -C "$R" commit -q -m "feat: round $n" >/dev/null 2>&1
done
git -C "$R" config bindle.hygiene.repeatCommits 2
run_hist
check "four files each changed in 2 commits: exactly 3 INFO lines (a cap, not a verdict)" test "$(info_count)" -eq 3

echo "advisory signals: quiet when there is nothing to say"
new_repo "$TMP/quiet"
git -C "$R" switch -q -c feat/q
commit_file "feat(a): add a" src/a.py 40 >/dev/null
commit_file "feat(b): add b" src/b.py 40 >/dev/null
run_hist
check "no WARN/INFO lines for an unremarkable branch" lacks_re '^(WARN|INFO)'
check "PASS lines are shown" has "PASS   no pending fixup!/squash!/amend! commits"
new_repo "$TMP/ahead0"
git -C "$R" switch -q -c feat/none
run_hist
check "a branch with no commits ahead of its base says so" has "no commits ahead of main"

echo "reporting is read-only"
new_repo "$TMP/ro"
git -C "$R" switch -q -c feat/ro
commit_ok "feat: one" >/dev/null
commit_ok "fixup! feat: one" >/dev/null
commit_file "fix: tiny" f2.txt 1 >/dev/null
echo "staged edit" >>"$R/f2.txt"
git -C "$R" add f2.txt
echo "unstaged edit" >>"$R/f.txt"
echo "untracked" >"$R/untracked.txt"
snapshot() {
  {
    git -C "$R" for-each-ref
    git -C "$R" rev-parse HEAD
    git -C "$R" status --porcelain=v2 --branch --untracked-files=all
    git -C "$R" reflog --format='%H %gs'
    git -C "$R" ls-files -s
    git -C "$R" diff
    git -C "$R" diff --cached
    cat "$R/f.txt" "$R/f2.txt" "$R/untracked.txt"
  } | cksum
}
before="$(snapshot)"
run_hist >/dev/null
run_pre_push feat/ro
run_hist --base main >/dev/null
after="$(snapshot)"
check "refs, HEAD, reflog, index, and staged/unstaged/untracked files are unchanged by reporting" \
  test "$before" = "$after"
check "(sanity) the report did have a BLOCK to act on" has "BLOCK"

printf '\n  history-hygiene: %d/%d checks passed\n' "$pass" "$((pass + fail))"
exit "$fail"
