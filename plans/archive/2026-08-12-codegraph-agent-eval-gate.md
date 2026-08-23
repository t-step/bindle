# CodeGraph adoption gate: agent-eval before any standing deployment

Date: 2026-08-12. Status: **concluded — FAIL.** CodeGraph uninstalled and unregistered from Valence
and global Claude Code config; nothing standing left behind. See docs/DECISIONS.md D021.

## Outcome

A single, low-cost answer to "would CodeGraph (github.com/colbymchenry/codegraph) meaningfully help
in Valence specifically" — before paying any coordination cost (dual-harness wiring, a standing
indexing daemon, a discoverability skill, a recurring re-audit obligation) on a full trial.

## Why now

`docs/DECISIONS.md` D020 dropped the prior code intelligence trial (code-review-graph /
codebase-memory-mcp) after a rigorous session-transcript audit found zero real invocations across
101 sessions in its two actual usage repos (Valence, cover-story), despite the server being <!-- private-ok: Bindle's own repo/decision names, not personal info -->
available in nearly all of them. CodeGraph looked like a stronger candidate on paper (66.1k stars,
MIT, disclosed benchmark methodology, native cross-agent support, honest documented limitations —
see conversation of 2026-08-12), but D020's lesson was explicit: a better tool is not automatically
a used tool, and availability is not evidence.

Working through cost/benefit before designing a trial (rather than after) surfaced a reason to doubt
a full trial pays off at all:

- **Codebase scale:** Valence is 336 files / 2,488 nodes / 7,534 edges — a normal medium monorepo,
  not the scale (tens of thousands of files, deep indirection) where structural graph tools show
  their biggest wins. CodeGraph's own README flags accuracy ceilings specifically in reflection/DI-
  heavy frameworks (Spring 83.3%, ASP.NET 83.9%, Django 74.1%); Valence's stack (Next.js/TypeScript +
  FastAPI) doesn't lean on that pattern much.
- **Observed task mix:** across the 101 audited sessions, tool usage was execution-heavy (5,375
  `Bash`, 1,858 `Read`, 924 `Edit`, 362 `Write`), not exploration-heavy. CodeGraph's own benchmark
  targets architecture-comprehension questions ("how does X reach Y," blast radius) — a different
  task shape than what actually dominated real work in these repos.
- **Coordination cost is certain regardless of payoff:** dual-harness wiring (Claude Code + Codex),
  a standing per-repo indexing daemon, a discoverability skill to build and maintain, and a real
  recurring cost to re-run the same rigorous session audit periodically, since D020 established that
  passive "looks fine" checks aren't trustworthy on their own.

Conclusion: don't design or commit to the full trial (opt-out deployment + discoverability skill +
evaluation period) yet. Gate on a cheap, non-standing check first.

## Scope

CodeGraph ships its own evaluation harness: `.claude/skills/agent-eval/` in its own repo, triggered
by `/agent-eval` or "benchmark/audit/validate codegraph." It runs an agent against a real codebase in
two arms (with and without CodeGraph), measuring tool-call counts, file reads, cost, and token usage,
with contamination detection (voids a run if the "without" arm reached CodeGraph through Bash — the
same false-positive class our own D020 audit had to correct for after an initial string-match gave a
wrong signal).

Running this once against Valence costs nothing standing: no daemon left running afterward, no
dual-harness commitment, no skill to maintain, no lasting install obligation.

This step happens **in Valence, not in Bindle** — Valence is a sibling repository (AGENTS.md: do not
modify sibling repositories; confirm the repository root before making changes). Bindle's role is
recording the decision and the gate criteria here, not executing the check.

## Gate criteria (set before looking at results, per D020's near-miss lesson)

- Run `/agent-eval` against Valence, comparing CodeGraph-assisted vs. baseline (rg/grep/Read) on
  real architecture/flow questions native to Valence's actual codebase.
- **Pass →** a real, repo-specific uplift on cost/tool-calls/tokens for CodeGraph-shaped questions.
  Worth then designing the fuller trial (opt-out deployment, discoverability skill, manual path,
  passive-usage audit) as previously discussed.
- **Fail or marginal →** do not proceed to a standing deployment. Record the result here or in a
  successor decision entry and stop.

## Result (2026-08-12)

Run by a peer Claude session working directly in Valence (`valence-e6`), which paused and got
explicit user authorization before making any global-scope change (npm global install, MCP entry
in `~/.claude.json`, a global hook) — a peer session request is not itself authorization for effects
outside the target repo, and it correctly treated it that way.

**Method deviation from plan, for a good reason:** CodeGraph's npm package doesn't ship `/agent-eval`
as an installed skill — the skill drives `scripts/agent-eval/audit.sh` from CodeGraph's own GitHub
source, which benchmarks against a fixed public-repo corpus, not arbitrary target repos. Rather than
clone their repo and hack their corpus for a one-off, a lightweight two-arm headless harness was
built matching their own documented headless design (`claude -p`, stream-json, tool-call/cost/token
parsing), run against the four real Valence questions from this plan. Setup: `codegraph@1.4.1`,
`codegraph init` on Valence (306 files, 2,727 nodes, 7,731 edges). 4 questions × 2 arms (baseline:
`--safe-mode`, no CLAUDE.md/hooks/MCP, Read/Grep/Bash only; codegraph: `--strict-mcp-config` with
only the codegraph server, default CLAUDE.md/hooks active). Contamination check passed: the baseline
arm made zero Bash calls across all four runs, so it could not have reached codegraph.

**Findings:**

- **Tool calls:** codegraph used far fewer — 7 vs. 24 total, a 71% reduction. Turns: 11 vs. 28.
- **Cost:** codegraph was *more* expensive overall — $0.6611 vs. $0.4024 (+64%), losing on 3 of 4
  questions individually. Cause: each `codegraph_explore` call returns a large novel payload billed
  at cache-write rates, while the baseline's grep/read calls benefit from cheap cache-read reuse
  across turns in the same session. Total token volume was ~15% lower for codegraph, but the billing
  *mix* shifted toward the pricier category — fewer tokens and fewer calls still cost more.
- **Correctness** (every citation checked against actual source): baseline was correct on all 4
  questions. Codegraph was correct on questions 2–4 (and slightly more thorough on question 3), but
  hallucinated a wrong answer on question 1, the flagship trace-to-HuggingFace-publish question — it
  claimed no HTTP/code path from the web app to `publish_revision_to_huggingface` exists and that
  it's CLI-only, which is false (`apps/web/src/lib/hf-export/actions.ts:78` → `POST /v1/hf/publish` →
  `apps/api/.../main.py:144-173` → `publish_revision_to_huggingface`). It found that exact path
  correctly when asked the closely related blast-radius question — a reliability failure on that
  specific question, not a fixed blind spot.

**Also worth naming:** CodeGraph's own disclosed README benchmark claimed "44% cheaper." This
real-world Valence test found the opposite (+64% more expensive) — a genuine, direct contradiction of
a well-methodologied vendor benchmark, not just "results vary." Even a benchmark with disclosed
methodology can diverge from real-world results in a specific repo; this reinforces evaluating
empirically in the actual target context rather than trusting even good-faith published numbers.

**Verdict per the predetermined gate criteria: FAIL.** Tool-call reduction is real but doesn't
translate to lower cost, and it produced a wrong answer on the single most representative question.
CodeGraph was fully uninstalled (`codegraph uninit`, `rm -rf .codegraph`,
`codegraph uninstall -t claude -y`) and verified clean: no binary, no MCP entry in `~/.claude.json`,
no CodeGraph block in `~/.claude/CLAUDE.md`, no refs in `~/.claude/settings.json`, Valence git status
clean.

## Evidence

- `docs/DECISIONS.md` D020 (the prior trial's audit method and result).
- CodeGraph README and `.claude/skills/agent-eval/SKILL.md` (github.com/colbymchenry/codegraph),
  read 2026-08-12.
- Valence session-transcript tool-use tally, 96 sessions, 2026-08-02 through 2026-08-12 (same method
  as D020).

## Open questions

- Resolved: `/agent-eval` ran via a peer Claude session (`valence-e6`) working directly in Valence,
  under its own explicit user authorization for the global-scope steps.
- Moot: the gate failed, so the fuller trial design (skill nudge + opt-out deployment + manual path)
  is not pursued. Not written up further.

## Decisions

- Gate the CodeGraph question on a single controlled benchmark run before any standing deployment or
  trial design — held. The gate did its job: it caught a real problem (cost regression + a wrong
  answer on the flagship question) before any coordination cost was paid.
- CodeGraph: not adopted. Recorded as docs/DECISIONS.md D021.
