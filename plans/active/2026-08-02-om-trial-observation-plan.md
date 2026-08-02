# Obsidian Mind trial — observation and measurement plan

Date: 2026-08-02. Companion to `plans/active/2026-08-02-obsidian-mind-interop-audit.md`.
Status: plan only — no Bindle features are implemented by this document.

Purpose: determine, from real work, whether the known gaps (Codex anonymous caller, no VCS state in
records, no lifecycle automation in consuming repos, worktree identity by name only) create enough
recurring friction to justify Bindle code — and to catch frictions the audit did not predict.

Governing principle: measure workflow outcomes and missing signals, never tool activity. No metric
in this plan rewards creating notes, capturing memories, or preserving more. The unit of
observation is a **boundary crossing that should have carried context**, and the only interesting
events are: context survived cheaply, context survived expensively, or context died.

Disposability: the trial log and this measurement system are experimental apparatus. They may be
deleted after synthesis. Built-in simplification rule — if logging is skipped two consecutive
working days, drop per-transition logging entirely and keep only the end-of-day review; if that is
also skipped, the trial continues unlogged and the synthesis relies on retrospective signals only.
A measurement system that gets abandoned is itself a finding (ceremony friction), not a failure of
discipline.

---

## 1. Trial protocol (concise)

**Scope**
- Length: 2 calendar weeks or 10–15 meaningful work sessions, whichever completes first. A
  meaningful session = real engineering work with an objective, not vault gardening or trial
  administration.
- Repositories: `bindle` first. Add one second repository only after audit experiments
  1–3 (Claude write → Codex read; Codex write → Claude read; same-day collision) have been run and
  their outcomes recorded.
- Quotas (minimums, to force the interesting boundaries to occur):
  - 3 Claude sessions, 3 Codex sessions
  - 2 cross-harness handoffs (one in each direction)
  - 1 linked-worktree workflow (create, work, merge or abandon, remove)
  - 1 intentional non-capture (exploration deliberately allowed to disappear)
  - 1 simulated provider outage (om server stopped before session end)
- Setup gate (day 0, ~30 min): deploy per audit deliverable C (vault clone pinned at v8.3.1,
  user-scope MCP registration, `.om-project` committed, `@AGENTS.md` import fix, CLAUDE.md snippet).
  Run audit experiments 1–3 immediately; their outcomes are the first trial-log entries.

**Trial log location**: one append-only file in the private vault, suggested
`thinking/trial/om-trial-log.md`. Two requirements: (a) never in the Bindle repo or any public
repository; (b) excluded from the qmd index (add the path to the vault's ignore filters) so the
measurement instrument cannot contaminate the retrieval it is measuring.

**Cadence**: per-transition one-liner (only when warranted — see §2), end-of-day two-minute review
(§7), a **five-session checkpoint** (after 5 meaningful sessions — template in the trial runbook;
answers only: worth continuing? Codex anonymity actually obstructing? observation tolerable? any
authority/privacy/incorrect-context problem? continue / simplify / stop), and one end-of-trial
synthesis of 60–90 minutes (§8). No feature decisions at the checkpoint unless a serious privacy,
correctness, or data-loss failure forces stopping.

**Honest-trial rules**
- Work normally. Do not create transitions to feed the log; the quotas above are the only forced
  events.
- When friction occurs, fix the work first, log second. The log entry is allowed to be terse to
  the point of rudeness.
- Codex's degraded state is observed, not pre-worked-around: let the anonymous-caller behavior
  actually cost something before compensating for it, otherwise question 3 cannot be answered.

---

## 2. Observation record — smallest format

The suggested 17-field record is too heavy for <1 minute. Refined design: **two tiers**.

**Tier 1 — the per-transition line.** Logged only for: (a) any non-smooth transition, (b) the
quota'd probe events (handoffs, worktree workflow, outage, intentional non-capture) even when
smooth. Smooth ordinary transitions are NOT logged individually — they are tallied from memory at
end of day. One pipe-delimited line:

```
YYYY-MM-DD HH:MM | repo | claude|codex | worktree-or-main | TRANSITION | smooth|friction|failure | TAXCODE | Nm | free-text: expected vs observed, workaround, who should own it
```

Example:

```
2026-08-04 14:32 | bindle | codex | main | CX | friction | ret-miss | 6m | expected recall to surface yesterday's record; anonymous caller, found via search after 3 queries; owner om-identity; bindle possible
```

Rules: `Nm` = manual minutes spent on the friction (0 if none). Everything after the minutes field
is free text — `context_repeated`, `workaround`, `candidate_owner`, `bindle_candidate` from the
original shape live there as prose when relevant, not as fields. A line should take ~30 seconds.

**Tier 2 — failure detail.** Only when outcome = `failure` (work was blocked or wrong): add an
indented paragraph — what was lost, what it cost, how it was recovered, and which cheaper remedy
(convention / config / provider fix) would have prevented it. Two minutes, at most a few times per
trial.

Transition codes (§4 defines each): `CC` `CX` `XC` `WT+` (main→feature) `WT-` (feature→main)
`S>R` (session→work record) `R>S` (record→resumed work) `E>PM` (event→projectmem) `D>DOC`
(decision→repo docs) `TMP>0` (exploration→intentional non-preservation) `L>GH` (local→GitHub)
`OUT` (provider unavailable→fallback).

---

## 3. Friction taxonomy (fixed, 12 codes)

| Code | Meaning | Typical example in this trial |
| --- | --- | --- |
| `cfg` | configuration — a setting/install was wrong or missing | om not registered in Codex config; missing `@AGENTS.md` import |
| `prov` | provider limitation — the tool cannot do it | Codex sends no MCP roots; no dirty-state field anywhere |
| `ident` | missing identity — actor/project/repo attribution wrong or absent | record attributed to wrong project; anonymous caller |
| `life` | missing lifecycle event — nothing fired when something should have | session ended, no capture opportunity surfaced |
| `ret-miss` | retrieval miss — relevant record existed, was not surfaced | recall hides project-scoped memory from Codex |
| `ret-wrong` | incorrect retrieval — surfaced but stale, superseded, or misleading | note described an abandoned branch as current truth |
| `route` | routing ambiguity — unclear where information should go | decision written to vault instead of docs/DECISIONS.md |
| `wtree` | worktree ambiguity — which checkout/branch unclear | two worktrees indistinguishable in a record |
| `auth` | duplicate authority — two places claim the same truth | vault copy of a decision drifts from DECISIONS.md |
| `priv` | privacy concern — private topology nearly (or actually) exposed | vault path pasted toward a public repo |
| `cerem` | manual ceremony — the workflow itself demanded busywork | evidence line felt like paperwork; logging burden |
| `seam` | genuine unowned seam — no tool owns this and none reasonably could | the residual category; candidate Bindle territory |

Rule: pick exactly one code per line — the *proximate* cause. If torn between two, prefer the more
specific (anything beats `seam`; `seam` is earned only after ruling the others out). The
`cfg`/`prov`/`route`/`seam` distinction is what question 10 is answered from.

---

## 4. Transition matrix — what should survive each crossing

| # | Transition | What should survive | Owner | Success observed as | Failure looks like | Currently missing signal |
| --- | --- | --- | --- | --- | --- | --- |
| CC | Claude → Claude, same repo | objective, done/not-done, decisions, next step | om work record (+ auto-memory as soft recall) | resume without re-reading code or transcript | re-investigation of settled ground | whether resume used the record or re-derived it (om audit log shows reads — see §9) |
| CX | Claude → Codex, same repo | same, retrievable by Codex without re-explanation | om vault | Codex surfaces the record via search/recall unprompted or on one query | user pastes/re-types context | om identity as seen by Codex (`om health`); withheld-result counts in om audit log |
| XC | Codex → Claude, same repo | Codex's work captured somewhere Claude finds | om vault (inbox risk per G1) | Claude finds the record; routing footer shows where it landed | inbox orphan never seen again | routing destination is stated in record footer at write time — read it |
| WT+ | main → feature worktree | routing label constant; branch/checkout explicit | `.om-project` (routing label) + evidence line (state; conditional) | `om health` reports same project; records name the worktree | identity fork; work attributed to main | worktree/branch in any record (evidence line is the only carrier) |
| WT- | feature → main worktree | merge status; what landed vs died with the branch | git/GitHub (PR) | post-merge record cites merge SHA or PR # | stale claims from unmerged work treated as done | projectmem branch-blindness (documented; observe, don't fix) |
| S>R | live session → work record | D016-worthy narrative (+ evidence line only when its conditions apply) | om `record_work` | record exists iff warranted | warranted work unrecorded — silently | no lifecycle event in consuming repos (G2); only end-of-day review catches it |
| R>S | work record → resumed implementation | exact code state the record describes | evidence line, when present (conditional — worktree involved, dirty state matters, history rewrite likely, or recovery anticipated) | checkout/diff reconstructable from the line | SHA unrecoverable; dirty state unknown | dirty-state capture (G8); nothing records it but the conditional line |
| E>PM | repository event → projectmem | issue/attempt/fix/decision with location | projectmem | event logged at the time, with file:line | speculation logged as truth; or nothing logged | branch/worktree on events (documented gap — observe misleadingness, not presence) |
| D>DOC | accepted decision → repo docs | the decision, numbered, in the authoritative file | `docs/DECISIONS.md` | decision findable there; vault holds at most a pointer | decision lives only in vault/projectmem (`auth`) | none — end-of-day question 3 covers it |
| TMP>0 | temporary exploration → non-preservation | nothing — deliberately | transcripts (allowed to die) | nothing durable written; no later regret | either hoarding (ceremony capture) or regretted loss | regret is retrospective-only by nature |
| L>GH | local work → GitHub PR/issue | PR/issue number as pointer in the record | GitHub (record holds pointer) | record cites PR #; **one-directional** — the PR never references the private vault | record with no durable public pointer after squash/rebase | none |
| OUT | provider available → unavailable | continuity of work + a fallback handoff | `plans/` dated handoff file | work continues; backfill happens within a day | capture silently skipped; loss discovered later | MCP-down is visible on tool call, invisible if never called |

---

## 5. Weekly measurement rubric

Counted once per week from the trial log + memory. Raw counts with a one-line judgment each —
never collapsed into a score. Denominators are approximate by design; at n≈10–15 sessions,
precision is fake anyway.

**Continuity**
- resumptions with no material context repeated: ___
- resumptions where prior investigation was repeated: ___ (each is a `CC`/`R>S` friction line)
- times "completed, do not redo" guidance actually prevented duplicate work: ___

**Cross-harness interoperability**
- Claude-authored records successfully used by Codex: ___ / attempted ___
- Codex-authored records successfully used by Claude: ___ / attempted ___
- retrieval or routing failures specifically attributable to missing MCP roots (`prov` + G1): ___
- records landing in inbox instead of the project folder: ___ ; minutes correcting routing: ___

**Code-state recoverability**
- records where repo + project were identifiable: ___ / total records
- incidents where exact SHA/branch/dirty/worktree was needed later: ___
- of those, times it could NOT be recovered: ___
- evidence lines consulted (actually read to answer a question) vs merely present: ___ / ___

**Worktree correctness**
- transitions where the intended worktree was unambiguous: all except ___
- identity fragmentation events (om, memory, or records splitting one project): ___
- records attributed to wrong project or branch: ___
- instruction divergence between checkouts that materially changed behavior: ___

**Preservation quality**
- captured records later consulted: ___ / captured
- captured records judged unnecessary at week's end (ceremony capture): ___
- missing records that caused actual loss (§7 question 2 answered "yes, it cost"): ___
- temporary explorations correctly allowed to disappear (no regret): ___
- projectmem events later found misleading because they described unmerged/abandoned work: ___
- **trusted-wrong context**: records or memories retrieved, *trusted*, and later found to describe
  another branch, abandoned work, superseded architecture, or the wrong project: ___
  (each is a `ret-wrong` line with outcome `failure` — the most serious signal in this rubric;
  silent wrong context is worse than missing context)

**Resilience**
- provider outage/degradation events: ___ ; successful manual fallbacks: ___ ;
  unrecoverable losses: ___ ; recovery minutes: ___

---

## 6. Build / no-build thresholds

Common rule: an incident counts toward a threshold only if its log line carries real manual minutes
(> 0) or a `failure` outcome — pure annoyance without cost never justifies code. "Distinct" means
on different days or in different repos, ruling out one bad afternoon.

**MCP roots adapter (G1)**
- Build if: ≥ 3 distinct Codex-session incidents where project-scoped retrieval or routing failed
  (`prov`/`ident` + G1 attribution) AND cumulative manual cost ≥ 15 minutes or ≥ 1 `failure`
  (wrong decision / redone work traced to the missing context).
- Rule out first: `search` (folder-filtered, not caller-scoped) proves an adequate substitute for
  `recall` (audit experiment 8); Codex usage is too rare to matter (< ~20 % of sessions ⇒ defer,
  don't build); the failure was actually `cfg` (om misregistered).
- Cheaper remedies first: AGENTS.md instructs Codex sessions to prefer `search` and to check
  `inbox/` at session start; file the upstream issue/PR against om (single active maintainer,
  fast release cadence — a patch may land within the trial window).
- Stop condition: om gains a non-roots identity mechanism, or Codex ships roots support, or the
  trial ends with < 3 qualifying incidents. Then the adapter stays unbuilt and the degradation is
  documented as a routing rule.

**Git evidence block (G3/G7/G8)**
- Build if: ≥ 3 distinct incidents where exact code state was needed later AND the evidence
  line failed to serve — absent *despite one of its triggering conditions applying* (worktree
  involved, dirty state material, history rewrite likely, recovery anticipated), wrong, or costing
  > 2 minutes each time — across ≥ 2 different situations (not one recurring identical case a
  template note could fix). Evidence lines are conditional (reconciled 2026-08-02): a record that
  legitimately needed no line never counts as an omission.
- Rule out first: the need was really "which project" (solved by `.om-project`); omission was a
  first-week habit artifact that disappeared by week two.
- Cheaper remedies first: the `omev` shell helper defined in the trial runbook, which prints the
  evidence line for pasting — this is disposable trial apparatus, not a Bindle feature, and it
  directly tests whether the friction is "assembling the line" or "remembering the line". If the
  alias exists and lines are still omitted, that is evidence *for* automated stamping; if the alias
  makes it free, no feature is needed.
- Stop condition: exact code state needed ≤ 1 time in the whole trial, or evidence lines present
  but never consulted (would mean the field is ceremony — the audit's assumption was wrong).

**Capture nudge hooks (G2)**
- Build if: ≥ 3 warranted-but-missed records (end-of-day review question 2 = "yes, it cost") AND
  cumulative rework/reconstruction ≥ 15 minutes.
- Rule out first: the missed records were not actually warranted (D016 — absence was correct);
  misses cluster in week one and vanish with habit.
- Cheaper remedies first: the end-of-day review itself is the nudge (it asks the question daily);
  a closing line in AGENTS.md ("before ending substantive sessions, consider record_work").
- Stop condition: capture misses stop recurring, or nudges would push toward ceremony capture
  (records created to satisfy the nudge — visible as "captured, never consulted, judged
  unnecessary" rising in the rubric). Never build to maximize capture.

**Worktree diagnostics**
- Build if: ≥ 2 actual identity mistakes (wrong project attribution, fragmented identity,
  contradictory instructions acted upon) occurring *despite* committed `.om-project`, launch
  discipline, and evidence lines.
- Rule out first: mistake caused by launching a provider from the wrong directory (`cfg`/habit);
  by a missing marker in a new repo (checklist item, not code).
- Cheaper remedies first: `om health` at the start of any worktree session (a convention);
  the doctor-script file-presence check gains a `.om-project` line (one line in an existing
  script — extension, not a new feature).
- Stop condition: the trial's worktree workflow completes with zero identity mistakes.

**Privacy guard restoration/extraction**
- Proceeds independently — prior evidence (three real pre-`git add` leaks in the archived system)
  already meets any reasonable threshold, per PRIVACY.md's restore-don't-rewrite disposition.
  Restore when the first vault-adjacent example/config is about to be committed to the public repo.
- Observing value without counting harmless scans: success is measured only by (a) true positives
  on staged content — a real path/name/denylist hit caught before commit, each one logged as a
  `priv` line; (b) verdict-disclosure honesty observed working (a run that admits no denylist was
  loaded); (c) zero personal-topology leaks in anything published during the trial. Clean scans
  are silence, not success. A single true positive justifies the guard permanently; zero true
  positives during the trial is *also* fine — the guard is insurance priced by severity, and it is
  explicitly exempt from the incident-count logic above.

---

## 7. End-of-day review template (two minutes, in the trial log)

```
## EOD YYYY-MM-DD  (sessions: N claude / N codex; repos: ...)
tallies: resumptions ok N / repeated-context N ; handoffs N ; records written N / warranted-but-missed N ; worktree sessions N
1. Where did context fail to cross a boundary today?          (or "nowhere")
2. Did that failure cost anything?                            (minutes / wrong turn / nothing)
3. Who should have owned the missing information?             (git / om / projectmem / docs / harness / nobody)
4. Remedy class?                                              (config / convention / provider fix / bindle / none)
```

Four questions, one tally line. If nothing happened, the entry is two lines and that is a good day.

## 8. End-of-trial synthesis template

One pass, 60–90 minutes, producing a short document in the vault (promotable to the Bindle repo
after privacy review):

```
# OM trial synthesis — YYYY-MM-DD
Sessions: __ claude / __ codex / __ repos / quotas met? __

## Classification of every friction line
- Isolated incidents (happened once, no pattern):
- Recurring seams (same taxonomy code ≥ 3 lines, ≥ 2 days):
- Provider defects (file upstream, don't build around yet):
- User habit problems (fix the habit, not the toolchain):
- Configuration errors (fixed during trial? residual?):

## Feature verdicts (against §6 thresholds — cite line counts and minutes)
- roots adapter:        build / defer / unbuilt-by-evidence
- evidence block:       build / defer / unbuilt-by-evidence
- capture nudges:       build / defer / unbuilt-by-evidence
- worktree diagnostics: build / defer / unbuilt-by-evidence
- privacy guard:        restored? true positives?

## Questions 1–10 (from the trial charter), answered in one sentence each

## Retrospective checks (§9 procedures — run now)
- re-query audit result:
- never-consulted records, classified three ways (not consulted during trial ≠ useless):
  - not consulted during the trial window:
  - judged unnecessary (ceremony capture — would not be written again):
  - plausibly useful over a longer horizon (keep; recheck at a later synthesis):
- projectmem speculation review:
- memory-reach review:

## Disposition
- adopt om as the shared layer? (full / claude-first / retrieval-only / no)
- trial log: delete / archive
- next trial (if any), smaller:
```

---

## 9. Signals that remain invisible under this plan

1. **Silent retrieval misses** — a relevant record existed and was never surfaced, and you never
   knew to miss it. The log only captures *felt* misses.
2. **Records never consulted** — prospectively invisible; you don't notice not-reading something.
3. **Whether AGENTS.md content actually loaded** in a given Claude session (prose vs `@import`
   inclusion is invisible in-session).
4. **Codex sessions that produced no native memory** because `disable_on_external_context`
   suppressed generation (harness-internal).
5. **Compaction losses** — whether post-compaction context was subtly degraded; PreCompact
   preservation runs only in the vault repo.
6. **Wrong-reach memories** — a memory declared `general` that is actually project-specific (or
   vice versa) is only visible when it later misleads (`ret-wrong`), which may be after the trial.
7. **Time-to-context at session start** — deliberately unmeasured (stopwatching yourself is
   telemetry ceremony); `context_repeated` is the proxy.
8. **Cross-worktree confusion that self-corrected** — near-misses caught silently by the user
   leave no trace.

## 10. Exposing invisible signals with the least machinery

Ordered by the required escalation ladder — convention, query, manual review, temporary log,
health command — before any feature:

- (1, 2) **om's own audit log already records every read** (`om-mcp-audit.jsonl`: action, caller,
  query, withheld counts — gitignored in the vault). At synthesis, two greps answer both: which
  trial-period records' filenames never appear in any read (never consulted), and a **re-query
  audit**: pick ~5 completed tasks, form the query you *would* have asked, run `search`/`recall`,
  and check whether the right record surfaces. Withheld-result counts on Codex-session reads also
  quantify scope-based hiding (G1) without any new logging. Cost: one synthesis hour, zero code.
- (3) **Canary probe, once**: put a distinctive token in AGENTS.md; in one fresh Claude session
  ask what the canary is, before and after the `@AGENTS.md` import fix. Two sessions, settles it
  permanently. Convention, not code.
- (4) One read-only sqlite query against Codex's local state at synthesis (memory_mode / phase-1
  rows for trial threads), or simply accept invisibility — memories are soft recall; nothing
  durable is at stake by design.
- (5) Accept for the trial. If a compaction-adjacent friction line ever appears, note `life` +
  "post-compact" in free text; only a pattern would justify wiring PreCompact hooks in consuming
  repos (config, still not Bindle code).
- (6) **Memory-reach review at synthesis**: read every memory written during the trial (there will
  be few) and judge declared reach against content. Ten minutes, manual.
- (7) Leave unmeasured, by principle.
- (8) Add "near-misses you remember" as a free-recall prompt in the synthesis, and accept the
  undercount. A near-miss that left no memory cost nothing.

---

## Charter questions → where each gets answered

| Q | Answered by |
| --- | --- |
| 1. Continuity improved? | rubric Continuity + synthesis re-query audit |
| 2. Cross-harness comprehension? | rubric Cross-harness (used-by counts), audit experiments 1–2 |
| 3. Anonymous-caller real failures? | `prov`+G1 lines, withheld counts, roots-adapter threshold |
| 4. Exact code state needed how often? | Code-state rubric ("needed later" count) |
| 5. Evidence line adequate? | "consulted vs present" + evidence-block threshold logic |
| 6. Warranted records missed? | EOD question 1–2, capture-nudge threshold |
| 7. Was non-capture harmful or correct? | TMP>0 lines + "missing records that caused loss" vs "correctly disappeared" |
| 8. projectmem quality? | "misleading unmerged events" count + synthesis speculation review |
| 9. Worktree fragmentation? | Worktree rubric + WT+/WT- lines |
| 10. cfg vs provider vs routing vs seam? | taxonomy distribution in the synthesis classification |
