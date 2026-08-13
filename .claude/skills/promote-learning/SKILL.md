---
name: promote-learning
description: >-
  Evaluates one concrete projectmem finding (an issue, decision, note, or
  attempt) and recommends whether its lesson should stay local to the
  repository it came from or be promoted beyond it, using provenance +
  cross-project recurrence + agent judgment. Never uses semantic/vector
  search, never invokes Obsidian Mind, never adds a new memory store. Use
  when someone asks whether a specific projectmem lesson, gotcha, or
  decision deserves broader reach, whether something should be "promoted"
  beyond its repository, or wants a precision-biased read on cross-project
  generality for one named finding. Not for surveying a whole project's
  memory, not for deciding permanent storage architecture, and not for
  writing anything — it recommends only. Refuses to generalize from a
  single interesting incident without independent recurrence evidence,
  refuses to count deliberate copying of the same lesson into other
  repositories as recurrence, and defaults to insufficient evidence over a
  confident-sounding guess.
---

# Promote Learning

This is an experiment in promotion *judgment*, not a memory system. It answers
one question about one finding: does the available evidence justify giving
this lesson reach beyond the repository where it originated? It never writes,
mutates, supersedes, or deletes anything in projectmem, Obsidian Mind, or
anywhere else — every output is a recommendation for a human or another
process to act on.

The hypothesis under test: provenance + cross-project recurrence + agent
judgment can make high-precision promotion calls without semantic
infrastructure (embeddings, vector search) or a second memory system. Treat
that as a hypothesis to keep testing, not a conclusion to defend — an honest
"insufficient evidence" or "already global" result is as much a success as a
clean promotion call.

## What this skill needs

- A concrete finding to evaluate: a projectmem event id, issue id, decision
  text, or a close paraphrase the user points at. If given only a vague topic
  ("something about latest tags"), find the concrete event first — do not
  invent or synthesize a finding from memory.
- Read access to projectmem's supported CLI (`pjm`) and MCP tools in the
  finding's home project, and read access to `pjm search` in whatever other
  projectmem-initialized projects are reachable on the machine (enumerate via
  `pjm global status` or `~/.projectmem/projects.json`).
- Nothing else. No embeddings, no vector store, no OM call, no new file
  format.

## The six steps

### 1. Establish the source finding

Pull the actual evidence, not a one-line impression of it. Prefer an explicit
identifier: `get_issue(issue_id)` (MCP) or `pjm search` for the event id /
exact phrase, then read the surrounding thread — the originating `log_issue`,
every `record_attempt`, and the closing `record_fix` or `add_decision`, in
order. You need enough of the story to state, separately:

- what happened;
- what caused it;
- what fixed or resolved it;
- what general lesson (if any) someone is actually proposing.

Do not generalize from an isolated sentence when richer projectmem evidence
for the same issue is sitting right next to it — a `record_fix` often
compresses an attempt sequence that changes what the "real" lesson is.

### 2. Check whether projectmem already handled it

Projectmem auto-promotes a narrow class of findings on its own: any
`attempt`/`decision`/`note` whose text opens with a signal prefix (`gotcha:`,
`lesson:`, `warning:`, `caution:`, `pitfall:`, `avoid:`, `don't `, `do not `,
`never `, `bug:`) — or any failed/partial attempt — gets checked against a
machine-wide "promotable libraries" set and, on a match, written straight to
`~/.projectmem/global/library_gotchas.jsonl`. This happens on every write,
silently, with no agent involved. Before proposing anything, rule out that it
already happened:

- `get_global_gotchas(library=...)` (MCP, if the library name is known) or
  `pjm global list --library <name>` / `pjm global list -f json` (CLI, for a
  full-text look).
- If an existing global entry substantially covers the same lesson: stop here
  and recommend **ALREADY GLOBAL**, citing the entry's id and
  `source_project`. Do not propose promoting it again under a different
  wrapping.
- If the finding is plausibly a dependency/tool gotcha (it names a
  manifest-declared library and describes *that library's own behavior*) but
  no global entry exists, check whether the original event text used one of
  the signal prefixes above. If it didn't, this is most likely a **projectmem
  auto-promotion false negative** — a mechanical miss, not evidence of low
  generality — and should be reported as exactly that rather than folded into
  a general-pattern recommendation.

### 3. Classify origin — reasoning support, not a new taxonomy

Distinguish, at minimum:

- repository-local implementation (a bug or decision in this project's own
  code);
- external dependency/framework/tool/platform (the lesson is about how
  something else behaves);
- potentially general engineering/process behavior (the lesson isn't really
  about any one piece of software).

Use deterministic evidence where it exists — a project's detected stack
(`pjm global detect`, or reading its manifest directly) tells you *whether a
library is actually declared*. That is a fact. Whether the incident was
*caused by* that library's own behavior, versus how this project happened to
use it, is a judgment call — keep the two labeled separately in your notes
and in the final report. A library name appearing in the event text is not
by itself evidence of causation (a gotcha about a Vercel bundle-size cap
might get text-matched to an unrelated package purely because that package
name also appears in the same sentence — check what the finding is actually
*about*, not just which words it contains).

### 4. Search for independent recurrence

Skip this step entirely if step 2 already returned ALREADY GLOBAL.

Otherwise:

- Enumerate other projectmem-initialized projects (`pjm global status`'s
  "Projects:" line, or `~/.projectmem/projects.json`).
- Generate several independent lexical reformulations of the lesson's
  underlying shape — invent these fresh from what the lesson is actually
  about, not from a fixed synonym list. A lesson about an implicit mutable
  write/reference target might reasonably prompt searches like "most recent",
  "latest", "misattribut", "wrong target", "implicit default", "current
  pointer", "symlink" — but that is an example of the kind of variety to
  reach for, not a checklist to run verbatim on every finding.
- For each reformulation, run `pjm search "<query>"` (add `-r` for
  regex/OR-patterns) inside each other project's checkout
  (`cd <path> && pjm search ...`), and read the actual hits — don't stop at
  match counts.
- For every candidate hit, classify it explicitly as one of:
  - **independent recurrence** — a different incident, in a different
    repository, with the same underlying shape, that was not derived from
    the original finding;
  - **deliberate propagation** — the same lesson or policy text, copied or
    closely paraphrased into another repository shortly after the original
    (near-identical wording, matching or immediately-following dates, or an
    explicit cross-reference to the source finding);
  - **coincidental overlap** — shares vocabulary but not the underlying
    failure shape.
- Only entries in the first bucket count toward recurrence. Name the other
  two explicitly in the report if found — do not silently drop them, and do
  not let them inflate the recurrence count.
- Separately, disclose your own prior exposure: if you already knew about a
  candidate analog before running this search — from an earlier
  investigation, a prior session, or prior discussion of this same finding —
  say so. Keep the two axes distinct: whether the underlying event in the
  other project predates and is unconnected to the source finding is
  evidence about recurrence; whether you already knew where to look for it
  is evidence about how much to trust this discovery. Prior exposure doesn't
  disqualify a genuinely independent event — one that predates and is
  unconnected to the source finding stays independent recurrence regardless
  of who already knew about it — but it should lower confidence in the
  discovery, since foreknowledge can steer reformulations toward a known
  answer instead of finding one cold. Don't let a previously-known thin
  analogy read as strong evidence merely because you knew where to look.

Do not manufacture recurrence by treating a weak or generic echo as a match
just because a search returned something.

### 5. Apply the preservation test

Ask directly: would this change a decision in another repository or future
project? Answer using what steps 1–4 actually found — not how interesting or
well-written the incident is. This is unavoidably a judgment call; say so
plainly rather than dressing it up as a computed result.

### 6. Recommend

Use exactly one of:

- **ALREADY GLOBAL** — projectmem already owns this knowledge; cite the entry.
- **KEEP LOCAL** — origin and/or recurrence evidence doesn't clear the
  preservation-test bar.
- **PROMOTE AS GENERAL PATTERN** — independent recurrence (not propagation,
  not coincidence) plus a preservation-test judgment that clears the bar.
- **INSUFFICIENT EVIDENCE** — the honest answer when the evidence is thin,
  ambiguous, or the search came back empty. This is a normal, useful result,
  not a failure to produce one of the other three.

When step 2 found a probable auto-promotion false negative, say so as its own
explicit note alongside whichever of the four labels applies — do not silently
relabel it as PROMOTE AS GENERAL PATTERN. A missed dependency gotcha is a
projectmem mechanics problem, not evidence of cross-project generality.

## Precision bias — refuse these shortcuts

This experiment favors precision over recall on purpose: a false-positive
promotion pollutes a shared store that other projects will trust; a
false-negative just leaves something local a little longer, until more
evidence shows up. Concretely, refuse to:

- treat one interesting incident as a general pattern without independent
  recurrence;
- treat the absence of a dependency/library match as evidence of generality
  (it's evidence of nothing, either way);
- count deliberate copying of the same lesson into several repositories as
  recurrence;
- accept vague conceptual resemblance ("this feels related") as a match —
  name the specific shared shape or don't count it;
- promote on the strength of "this seems broadly useful" alone — that
  sentence, unsupported by steps 1–4, should normally produce INSUFFICIENT
  EVIDENCE, not a promotion.

Do not use how much projectmem memory exists, or how many candidates a search
turned up, as a signal of anything. Volume is not evidence.

## What this skill must never do

- Write a global pattern or gotcha, or call any projectmem write tool/command
  on the user's behalf.
- Write, touch, or reference Obsidian Mind / `om` in any way.
- Modify projectmem's code, configuration, or storage.
- Maintain its own recurrence counts or cache — every run starts from
  scratch against real evidence.
- Build or consult a semantic/vector index.
- Decide permanent storage architecture for promoted knowledge — that's a
  separate, later question.

## Report

Use this structure:

```
## Recommendation
ALREADY GLOBAL | KEEP LOCAL | PROMOTE AS GENERAL PATTERN | INSUFFICIENT EVIDENCE
<+ "projectmem auto-promotion false negative" note, if applicable>

## Proposed lesson
<One concise, generalized sentence — only when recommending promotion.>

## Evidence
- Source: <project>/<event or issue id>, <date>
- Origin: <fact — declared dependency? which manifest, if so> /
  <judgment — is the incident actually caused by that dependency's behavior?>
- Already-global check: <found, with entry id — or not found, with what was
  searched>
- Independent analogous occurrence(s): <project/event id and the specific
  shared shape — or "none found after N reformulations">
- Propagation / coincidence excluded from recurrence: <name anything found
  here explicitly, even though it doesn't count>

## Judgment
<2–4 sentences: why the evidence does or doesn't clear the preservation-test
bar. Grounded in steps 1–4, not restated enthusiasm.>

## Confidence / uncertainty
<Name the weakest link plainly — ambiguous origin classification, thin
recurrence, a judgment call that could reasonably go the other way. If a
step-4 candidate analog was already known to you before this search, say so
here, and note separately whether the underlying event is still
independently dated despite that prior exposure.>
```

Leave a line as "not found" or "not established" rather than omitting it —
an absent line reads as "not checked," which is worse than an honest gap.
