#!/usr/bin/env bash
# Claude Code statusline (vaporwave boxed panel). Fixed 4-row footprint (top
# border, work/orientation row, agent/session-pressure row, bottom border):
# width changes density within a row, never height, and never wraps a row.
input=$(cat)

j() { printf '%s' "$input" | jq -r "$1" 2>/dev/null; }

cwd=$(j '.cwd // .workspace.current_dir // empty')
project_dir=$(j '.workspace.project_dir // empty')
worktree_name=$(j '.workspace.git_worktree // empty')
model=$(j '.model.display_name // empty')
tpath=$(j '.transcript_path // empty')

# Round at the source: upstream JSON may give float noise (2.0000000000000004).
fmt_pct() {
  local n="$1"
  [ -z "$n" ] && { printf '0'; return; }
  awk -v n="$n" 'BEGIN{printf "%.0f", n}' 2>/dev/null || printf '0'
}

ctx_pct=$(fmt_pct "$(j '.context_window.used_percentage // empty')")

rl5_present=$(j 'if .rate_limits.five_hour then "1" else empty end')
rl_5h=$(fmt_pct "$(j '.rate_limits.five_hour.used_percentage // empty')")
rl_5h_reset=$(j '.rate_limits.five_hour.resets_at // empty')
rl7_present=$(j 'if .rate_limits.seven_day then "1" else empty end')
rl_7d=$(fmt_pct "$(j '.rate_limits.seven_day.used_percentage // empty')")
rl_7d_reset=$(j '.rate_limits.seven_day.resets_at // empty')

dur_ms=$(j '.cost.total_duration_ms // empty')

[ -z "$cwd" ] && cwd="$PWD"
[ -z "$project_dir" ] && project_dir="$cwd"
project_name=$(basename "$project_dir")

fmt_num() {
  local n="$1"
  [ -z "$n" ] && { printf '0'; return; }
  if [ "$n" -ge 1000000 ] 2>/dev/null; then
    awk -v n="$n" 'BEGIN{printf "%.1fM", n/1000000}'
  elif [ "$n" -ge 1000 ] 2>/dev/null; then
    awk -v n="$n" 'BEGIN{printf "%.1fk", n/1000}'
  else
    printf '%s' "$n"
  fi
}

# H:MM at every tier; seconds are not decision-relevant for session length.
fmt_dur() {
  local ms="$1"
  [ -z "$ms" ] && { printf '0:00'; return; }
  local s=$((ms/1000))
  printf '%d:%02d' "$((s/3600))" "$(((s%3600)/60))"
}

# compact countdown to a rate-limit reset (e.g. "3d8h", "2h14", "42m")
fmt_reset() {
  local epoch="$1"
  [ -z "$epoch" ] && { printf 'n/a'; return; }
  local now diff
  now=$(date +%s)
  diff=$((epoch-now))
  [ "$diff" -lt 0 ] && diff=0
  local d=$((diff/86400)) h=$(((diff%86400)/3600)) m=$(((diff%3600)/60))
  if [ "$d" -gt 0 ]; then printf '%dd%dh' "$d" "$h"
  elif [ "$h" -gt 0 ]; then printf '%dh%02d' "$h" "$m"
  else printf '%dm' "$m"
  fi
}

make_bar() {
  local pct="$1" width="$2" filled empty
  [ -z "$pct" ] && pct=0
  pct=${pct%%.*}
  filled=$(( (pct * width + 50) / 100 ))
  [ "$filled" -gt "$width" ] && filled="$width"
  empty=$((width - filled))
  printf '%*s' "$filled" '' | tr ' ' '▓'
  printf '%*s' "$empty" '' | tr ' ' '░'
}

repeat() { printf '%*s' "$2" '' | tr ' ' "$1"; }

# Character-aware, not byte-aware: never cut multi-byte UTF-8 mid-codepoint.
clip_tail() { # text maxlen -- keeps the suffix (branch leaf names matter more)
  local text="$1" max="$2" len=${#1}
  [ "$len" -le "$max" ] && { printf '%s' "$text"; return; }
  [ "$max" -ge 2 ] && printf '%s' "…${text: -$((max-1))}" || printf '%s' "${text:0:$max}"
}
clip_head() { # text maxlen -- keeps the prefix (titles read left-to-right)
  local text="$1" max="$2" len=${#1}
  [ "$len" -le "$max" ] && { printf '%s' "$text"; return; }
  [ "$max" -ge 2 ] && printf '%s' "${text:0:$((max-1))}…" || printf '%s' "${text:0:$max}"
}

fg() { printf '\033[38;2;%s;%s;%sm' "$1" "$2" "$3"; }
reset=$'\033[0m'
C_BORDER="$(fg 189 55 255)"
C_TITLE="$(fg 0 224 255)"
C_VALUE="$(fg 255 102 214)"
C_GOOD="$(fg 0 255 170)"
C_MID="$(fg 255 231 87)"
C_HIGH="$(fg 255 68 128)"
C_DIM="$(fg 138 111 191)"

# ascending pct = ascending pressure everywhere this is used (CTX, 5H, 7D)
level_color() {
  local pct="$1"
  [ -z "$pct" ] && { printf '%s' "$C_DIM"; return; }
  if [ "$pct" -ge 80 ] 2>/dev/null; then printf '%s' "$C_HIGH"
  elif [ "$pct" -ge 50 ] 2>/dev/null; then printf '%s' "$C_MID"
  else printf '%s' "$C_GOOD"
  fi
}

# Git segment: repo state right now, independent of Delta (cumulative scope).
branch=""
branch_suffix=""
git_color="$C_VALUE"
if b=$(git -C "$cwd" symbolic-ref --short HEAD 2>/dev/null || git -C "$cwd" rev-parse --short HEAD 2>/dev/null); then
  branch="$b"
  if [ -n "$(git -C "$cwd" status --porcelain 2>/dev/null)" ]; then
    n=$(git -C "$cwd" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    branch_suffix="${branch_suffix} ✱${n}"
    git_color="$C_HIGH"
  fi
  ab=$(git -C "$cwd" rev-list --left-right --count "@{u}...HEAD" 2>/dev/null)
  if [ -n "$ab" ]; then
    behind=$(printf '%s' "$ab" | awk '{print $1}')
    ahead=$(printf '%s' "$ab" | awk '{print $2}')
    [ "$ahead" -gt 0 ] 2>/dev/null && branch_suffix="${branch_suffix} ↑${ahead}"
    [ "$behind" -gt 0 ] 2>/dev/null && branch_suffix="${branch_suffix} ↓${behind}"
  fi
fi

# Delta: cumulative divergence of the local branch from ITS OWN upstream (@{u}),
# INCLUDING uncommitted work, so `git commit` never changes it. Answers "how far
# has local drifted from origin", not "how big will the PR diff be" (that needs
# the PR base).
#
# base = @{u}; refs/remotes/origin/HEAD only when no upstream exists (offline,
#   no gh, no hardcoded branch names).
# mb   = merge-base(base, HEAD): isolates this branch's divergence from commits
#   landed on base since the fork.
# tracked = one `git diff --numstat <mb>` against the worktree (covers committed
#   + staged + unstaged, so nothing is summed twice).
# untracked = each file diffed against /dev/null, mirroring what git reports if
#   added (binary, no-trailing-newline handling).
# The two sets are disjoint by construction, so summing cannot double-count.
#
# Known limitation: the origin/HEAD fallback is the repo's default branch, not
# necessarily this branch's base, so a branch forked from `development` when the
# default is `main` overstates scope by however far `development` is ahead. A gh
# PR-base lookup would be more precise but needs a network call, kept out of
# this synchronous path.
delta_base=$(git -C "$cwd" rev-parse --symbolic-full-name "@{u}" 2>/dev/null)
[ -z "$delta_base" ] && delta_base=$(git -C "$cwd" symbolic-ref --quiet refs/remotes/origin/HEAD 2>/dev/null)
delta_mb=""
[ -n "$delta_base" ] && delta_mb=$(git -C "$cwd" merge-base "$delta_base" HEAD 2>/dev/null)
delta_files=0 delta_add=0 delta_del=0
if [ -n "$delta_mb" ]; then
  delta_stats=$(
    { git -C "$cwd" diff --numstat "$delta_mb" -- 2>/dev/null
      git -C "$cwd" ls-files --others --exclude-standard -z 2>/dev/null | \
        while IFS= read -r -d '' f; do
          git -C "$cwd" diff --no-index --numstat -- /dev/null "$f" 2>/dev/null
        done
    } | awk '{ n++; if ($1 != "-") a+=$1; if ($2 != "-") d+=$2 } END { printf "%d %d %d", n+0, a+0, d+0 }'
  )
  read -r delta_files delta_add delta_del <<< "$delta_stats"
fi

# TURN/CMP: one jq pass over the transcript.
# turn = distinct assistant message.id count (one turn spans several JSONL rows,
#   one per content block, sharing an id; dedupe or it overcounts).
# cmp  = count of {type:"system", subtype:"compact_boundary"} entries, the
#   marker Claude Code's own compaction emits (confirmed in the shipped binary).
#
# TURN is uncorrected for /clear on purpose: /clear starts a fresh transcript
# file with a fresh session_id (checked across 37 local transcripts), so no
# boundary marker is needed (D027). If a Claude Code version stops rotating the
# transcript on /clear, TURN would count pre-clear turns again: look here first.
#
# Measured ~17ms on a ~2.5MB/632-line transcript, so no caching.
turn_count="" cmp_count=0
if [ -n "$tpath" ] && [ -f "$tpath" ]; then
  read -r turn_count cmp_count <<< "$(jq -s -r '
    (([.[] | select(.type=="assistant")] | group_by(.message.id) | length)) as $t |
    (([.[] | select(.type=="system" and .subtype=="compact_boundary")] | length)) as $c |
    "\($t) \($c)"
  ' "$tpath" 2>/dev/null)"
fi
[ -z "$cmp_count" ] && cmp_count=0

# $COLUMNS comes from Claude Code's own process.stdout.columns (confirmed in
# 2.1.231); this child has no controlling tty, so `tput cols` would only guess.
cols=${COLUMNS:-80}
[ "$cols" -gt 0 ] 2>/dev/null || cols=80
BOX_MIN=30
BOX_MAX=100
BOX_W=$((cols-1))
[ "$BOX_W" -gt "$BOX_MAX" ] && BOX_W=$BOX_MAX
[ "$BOX_W" -lt "$BOX_MIN" ] && BOX_W=$BOX_MIN
INNER=$((BOX_W-4))

if [ "$cols" -ge 100 ]; then TIER=wide
elif [ "$cols" -ge 72 ]; then TIER=normal
elif [ "$cols" -ge 52 ]; then TIER=narrow
else TIER=tiny
fi

box_border_top() { # title
  local text="$1" max=$((BOX_W-6))
  text=$(clip_head "$text" "$max")
  local llen=$((${#text}+2)) rest
  rest=$((BOX_W-3-llen))
  [ "$rest" -lt 0 ] && rest=0
  printf '%s╔═ %s%s%s%s %s%s'  "$C_BORDER" "$reset" "$C_TITLE" "$text" "$reset" "$C_BORDER" "$(repeat '═' "$rest")"
  printf '╗%s' "$reset"
}
box_border_bot() { printf '%s╚%s╝%s' "$C_BORDER" "$(repeat '═' $((BOX_W-2)))" "$reset"; }

title="$(printf '%s' "$project_name" | tr '[:lower:]' '[:upper:]')"
if [ "$TIER" = "wide" ] && [ -n "$worktree_name" ] && [ "$worktree_name" != "$project_name" ]; then
  title="${title} ▸ $(printf '%s' "$worktree_name" | tr '[:lower:]' '[:upper:]')"
fi

seg_git() {
  [ -z "$branch" ] && return
  case "$TIER" in
    wide|normal) printf '%s' "${branch}${branch_suffix}" ;;
    narrow)      printf '%s' "$(clip_tail "$branch" 12)${branch_suffix}" ;;
    tiny)        [ -n "$branch_suffix" ] && printf '%s' "${branch_suffix# }" ;;
  esac
}

# Always present: with CTX, keeps either content row from rendering blank.
seg_elapsed() { printf '⏱ %s' "$(fmt_dur "$dur_ms")"; }

# The bar drops first (wide only); the percentage never disappears.
seg_ctx() {
  if [ "$TIER" = "wide" ]; then
    printf 'CTX %s%% %s' "$ctx_pct" "$(make_bar "$ctx_pct" 5)"
  else
    printf 'CTX %s%%' "$ctx_pct"
  fi
}

# Routine at wide/normal; at narrow/tiny only once usage is actionable, with the
# reset countdown only at higher usage. Bar: wide only.
seg_rl() { # label pct reset present
  local label="$1" pct="$2" resetat="$3" present="$4"
  [ -z "$present" ] && return
  local show=0
  case "$TIER" in
    wide|normal) show=1 ;;
    narrow)      [ "$pct" -ge 50 ] 2>/dev/null && show=1 ;;
    tiny)        [ "$pct" -ge 80 ] 2>/dev/null && show=1 ;;
  esac
  [ "$show" -eq 0 ] && return
  local suffix=""
  case "$TIER" in
    wide|normal) suffix=" ↻$(fmt_reset "$resetat")" ;;
    *)           [ "$pct" -ge 80 ] 2>/dev/null && suffix=" ↻$(fmt_reset "$resetat")" ;;
  esac
  if [ "$TIER" = "wide" ]; then
    printf '%s %s%% %s%s' "$label" "$pct" "$(make_bar "$pct" 5)" "$suffix"
  else
    printf '%s %s%%%s' "$label" "$pct" "$suffix"
  fi
}

seg_delta() {
  [ "$TIER" = "tiny" ] && return
  [ "$delta_files" -eq 0 ] 2>/dev/null && return
  case "$TIER" in
    wide|normal) printf 'Δ %sf +%s/-%s' "$delta_files" "$(fmt_num "$delta_add")" "$(fmt_num "$delta_del")" ;;
    narrow)      printf 'Δ%sf+%s-%s' "$delta_files" "$(fmt_num "$delta_add")" "$(fmt_num "$delta_del")" ;;
  esac
}

seg_model() {
  case "$TIER" in
    wide|normal) [ -n "$model" ] && printf '%s' "$model" ;;
  esac
}

seg_turn() {
  case "$TIER" in
    wide|normal) [ -n "$turn_count" ] && printf 'TURN %s' "$(fmt_num "$turn_count")" ;;
  esac
}

# Zero is invisible; nonzero outranks model/turn but not the rate limits (an
# exhausted limit blocks work, a past compaction is informational).
seg_cmp() {
  [ "$cmp_count" -gt 0 ] 2>/dev/null && printf 'CMP %s' "$cmp_count"
}

git_seg=$(seg_git)
elapsed_seg=$(seg_elapsed)
ctx_seg=$(seg_ctx)
ctx_color=$(level_color "$ctx_pct")
rl5_seg=$(seg_rl "5H" "$rl_5h" "$rl_5h_reset" "$rl5_present")
rl5_color=$(level_color "$rl_5h")
rl7_seg=$(seg_rl "7D" "$rl_7d" "$rl_7d_reset" "$rl7_present")
rl7_color=$(level_color "$rl_7d")
delta_seg=$(seg_delta)
model_seg=$(seg_model)
turn_seg=$(seg_turn)
cmp_seg=$(seg_cmp)

# Reads globals RP_TEXT[]/RP_COLOR[] (candidates, most important first) and
# RD_ORDER[] (indices into them, display order). One forward greedy-fit pass in
# priority order: a skipped big segment must not cost a smaller lower-priority
# one its chance.
row_render() {
  local n=${#RP_TEXT[@]} i p add_len running=0 first=1
  SURVIVED=()
  for ((i=0; i<n; i++)); do SURVIVED[i]=0; done
  for ((i=0; i<n; i++)); do
    p="${RP_TEXT[$i]}"
    [ -z "$p" ] && continue
    add_len=${#p}
    [ "$first" -eq 0 ] && add_len=$((add_len+2))
    if [ "$((running+add_len))" -le "$INNER" ]; then
      SURVIVED[i]=1
      running=$((running+add_len))
      first=0
    fi
  done
  local line="" started=0 idx plain=0 cnt=0
  for idx in "${RD_ORDER[@]}"; do
    [ "${SURVIVED[$idx]}" -eq 1 ] || continue
    [ "$started" -eq 1 ] && line+="  "
    line+="${RP_COLOR[$idx]}${RP_TEXT[$idx]}${reset}"
    started=1
    plain=$((plain+${#RP_TEXT[$idx]}))
    cnt=$((cnt+1))
  done
  [ "$cnt" -gt 1 ] && plain=$((plain+(cnt-1)*2))
  local pad=$((INNER-plain))
  [ "$pad" -lt 0 ] && pad=0
  printf '%s║%s %s%s %s║%s' "$C_BORDER" "$reset" "$line" "$(printf '%*s' "$pad" '')" "$C_BORDER" "$reset"
}

# row 1 (work/orientation): git highest priority, elapsed sticky (with CTX, so
# no row is blank), Delta most expendable.
RP_TEXT=("$git_seg" "$elapsed_seg" "$delta_seg")
RP_COLOR=("$git_color" "$C_VALUE" "$C_VALUE")
RD_ORDER=(0 2 1)
row1=$(row_render)

# row 2 (agent/session pressure): priority CTX, then 5H/7D, a real CMP (>0),
# model, turns; displayed model -> TURN -> CMP -> CTX -> 5H -> 7D.
RP_TEXT=("$ctx_seg" "$rl5_seg" "$rl7_seg" "$cmp_seg" "$model_seg" "$turn_seg")
RP_COLOR=("$ctx_color" "$rl5_color" "$rl7_color" "$C_MID" "$C_DIM" "$C_DIM")
RD_ORDER=(4 5 3 0 1 2)
row2=$(row_render)

printf '%s\n%s\n%s\n%s' "$(box_border_top "$title")" "$row1" "$row2" "$(box_border_bot)"
