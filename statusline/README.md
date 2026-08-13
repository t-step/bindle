# Vaporwave statusline

A Claude Code statusline: a fixed 4-row vaporwave-styled panel (top border,
work/orientation row, agent/session-pressure row, bottom border) that never
grows taller under width pressure — only denser or sparser within each row.

This lives here as a deliberate scope exception (docs/DECISIONS.md, D026),
not as a Bindle product feature. It is a personal Claude Code configuration
artifact tracked here for portability and backup, and Bindle does not run,
install, or depend on it.

## What it shows

Row 1 (work/orientation): git branch, dirty/ahead/behind state, Δ (cumulative
body-of-work scope vs. the repo's default branch, including uncommitted
work), elapsed session time.

Row 2 (agent/session pressure): model, TURN (assistant-turn count since the
last `/clear`, or since session start if none — see "Optional: TURN reset on
/clear" below), CMP (compaction count, only shown when nonzero, never reset
by `/clear` since a past compaction is evidence about context quality
independent of what's currently visible), context-window usage, and
5-hour/7-day rate-limit usage with reset countdowns.

Width shrinks information density (bars drop first, then routine detail,
then optional segments) rather than wrapping or adding rows — see the
comments in `vaporwave.sh` for the exact per-tier rules.

## Requirements

- `bash` (developed against bash 3.2 semantics — macOS's default `/bin/bash`
  — deliberately avoids newer bash-only syntax for portability)
- `git`
- `jq`
- A terminal with 24-bit ("truecolor") ANSI support and UTF-8 rendering

On Windows, Claude Code runs statusline scripts via Git Bash; `jq` is not
bundled with Git Bash and must be installed separately.

## Install

1. Copy or symlink `vaporwave.sh` into `~/.claude/statuslines/vaporwave.sh`:

   ```sh
   mkdir -p ~/.claude/statuslines
   ln -sf /path/to/this/repo/statusline/vaporwave.sh ~/.claude/statuslines/vaporwave.sh
   ```

2. Point `~/.claude/statusline.sh` at it (a symlink, so it's easy to swap
   between multiple statuslines later):

   ```sh
   ln -sf statuslines/vaporwave.sh ~/.claude/statusline.sh
   ```

3. In `~/.claude/settings.json`, set:

   ```json
   "statusLine": {
     "type": "command",
     "command": "~/.claude/statusline.sh",
     "padding": 0,
     "refreshInterval": 30
   }
   ```

A `refreshInterval` of 30s or higher is recommended — the script shells out
to `git` several times and does one `jq` pass over the session transcript
per render.

## Optional: TURN reset on /clear

Without this step, TURN counts every assistant turn logged to the session's
transcript file for the life of the terminal session, including turns from
before a `/clear` — the transcript itself has no structural boundary marker
for `/clear` to filter on (unlike compaction, which does: `compact_boundary`).

`/clear` does fire a real `SessionEnd` hook with `reason:"clear"`, though, so
`hooks/session-end-clear-marker` catches that event and records a timestamp
per session under `~/.claude/hooks/state/turn-reset-<session_id>.txt`. The
statusline reads that marker, when present, and only counts turns at or
after it.

To enable it:

1. Copy or symlink `hooks/session-end-clear-marker` into
   `~/.claude/hooks/session-end-clear-marker` and make it executable.
2. Add a `SessionEnd` entry to `~/.claude/settings.json`'s `hooks` object:

   ```json
   "SessionEnd": [
     {
       "matcher": "",
       "hooks": [
         {
           "type": "command",
           "command": "~/.claude/hooks/session-end-clear-marker",
           "timeout": 5
         }
       ]
     }
   ]
   ```

Without this, TURN still works — it just counts from session start rather
than from the last clear.
