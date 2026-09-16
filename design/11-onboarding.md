# 11 — Onboarding Flow

Audience: a new engineer or stakeholder joining the agentic COBOL→C# migration project. Goal: productive read on the system's determinism boundary and a working local run within one sitting, dashboard literacy within the same session.

Demo repo: `/home/frg/creai/cobol/cobol-accounting-system` (GnuCOBOL sources `main.cob`, `operations.cob`, `data.cob`; a prior hand/Copilot-ported `node-accounting-app/` sibling as a reference migration — not part of the agentic pipeline itself, useful only as a sanity check of expected external behavior).

## 0. Preconditions (5 min, before the 30-minute clock starts)

- Repo cloned, `.claude/` and `.agents/` directories present (skills, agent defs).
- GnuCOBOL (`cobc`) installed and `cobc -x main.o operations.o data.o -o accountsystem` succeeds — this is the deterministic ground truth the whole pipeline is graded against. If this step fails, stop: nothing downstream is verifiable.
- Access to whatever LLM/agent runtime backs the pipeline (API keys / local harness) confirmed working with a trivial ping, not with the pipeline itself.

Rationale: an onboarding session that starts by debugging compiler installation instead of the migration system wastes the 30-minute budget. Separate infra setup from system understanding explicitly.

## 1. Understanding deterministic vs. agentic in under 30 minutes

Reading order, timed:

1. **(5 min) `cobol-accounting-system/README.md` + the three `.cob` files.** Not to learn COBOL — to fix the ground truth: three programs, a fixed menu contract (View/Credit/Debit/Exit), one numeric balance, no edge-case surface beyond overdraft and non-numeric input. This is the entire scope the agents operate on. A reader who skips this will misjudge agent output quality against an imagined larger system.
2. **(10 min) The pipeline's stage list, read as a table of "deterministic" vs "agentic" per stage** — not as prose. Every migration pipeline of this shape decomposes into roughly:

   | Stage | Nature | Why |
   |---|---|---|
   | COBOL parse / AST extraction | Deterministic | Grammar-driven, must be 100% reproducible or nothing downstream is trustworthy |
   | Structure/paragraph → call-graph mapping | Deterministic | Mechanical graph construction from the AST |
   | Semantic intent extraction (what does this paragraph *mean*) | Agentic | Requires reading COBOL idiom and naming intent, no formal spec exists |
   | C# code generation | Agentic | Requires judgment calls (idiomatic .NET shape, naming, structure) |
   | Compilation of generated C# | Deterministic | `dotnet build`, pass/fail, no judgment |
   | Behavioral parity testing (run both binaries against the same input vectors, diff output) | Deterministic | The check is deterministic even though the thing it checks (agent output) is not |
   | Failure triage / retry-with-feedback | Agentic | Deciding *why* parity failed and what to change requires reasoning |
   | Human-readable progress/dashboard reporting | Deterministic | Pure aggregation of the above stage results |

   The one-line rule to internalize: **anything that can be re-run and must produce byte-identical results is deterministic; anything that requires reading intent or making a judgment call under ambiguity is agentic.** Parity testing is the load-bearing example that trips people up — the *test* is deterministic even though it exists to check *non-deterministic* output. Get a new person to say this rule back correctly before moving on; it is the single most common confusion point.
3. **(10 min) One skill file + one agent definition, read side by side** (e.g. whichever skill drives semantic extraction, and whichever agent definition drives code generation). The point is to see where a prompt/skill hands off to deterministic tool calls (parser output, compiler exit codes) and where it hands control back to model judgment. This is more informative than reading pipeline orchestration code, because orchestration code all looks like plumbing until you've seen one skill's actual decision points.
4. **(5 min) Skim `TESTPLAN.md`** in the demo repo — it defines the acceptance surface (menu paths, edge cases) that the parity stage checks against. This closes the loop: stage table → concrete test vectors.

Checkpoint at 30 minutes: the new person should be able to answer, without looking anything up, "if the generated C# balance calculation is off by a rounding case, which stage produced the bug, and which stage will *catch* it?" (Answer: agentic code-gen produced it; deterministic parity testing catches it, but triage of *why* is agentic again.) If they can't answer this, repeat step 2 before proceeding — do not proceed to running the pipeline on a shaky model.

## 2. Running the pipeline locally against the demo repo

Sequenced so each step is verifiable before trusting the next:

1. **Verify the deterministic baseline runs standalone**, independent of any agent: compile and run `accountsystem` directly (commands in the demo README), exercise all four menu options once by hand. This produces the reference behavior the pipeline will later be judged against. Skipping this means later "parity: PASS" results are unfalsifiable to the new person.
2. **Run the pipeline in dry-run / single-stage mode if one exists** (parse-only, no LLM calls) against `main.cob`/`operations.cob`/`data.cob`. Confirm the AST/call-graph output looks sane before spending any agent budget. This isolates "the deterministic front-end works" from "the agent works," which matters because failures in stage 1 masquerade as agent failures if run end-to-end blind.
3. **Run one full stage (semantic extraction) in isolation** on a single paragraph (e.g. the debit operation in `operations.cob`) and read the output before letting the pipeline proceed automatically. First-run calibration: does the extracted intent match what a human reading the COBOL would say? This is the cheapest place to catch a misconfigured prompt/skill before it costs a full pipeline run.
4. **Run the full pipeline end-to-end** on the demo repo with cost/step limits set low (this is a 3-program, ~one-screen-of-COBOL system — if the run is trying to do more than a few dozen LLM calls, something is misconfigured or looping).
5. **Run the parity test suite** against the generated C# output and the original `accountsystem` binary, using the same input vectors from `TESTPLAN.md`. Confirm this step is the one place where "did it work" gets a real yes/no answer — everything upstream is process, this is the result.

New person should finish this section having produced, from a cold clone, one full pipeline run with a parity verdict they can point to and explain.

## 3. Reading the dashboard / progress output

Read it in the same deterministic/agentic split as section 1, because that split is what the dashboard is organized around (or should be — flag it as a gap in this doc if the current dashboard doesn't separate them):

- **Progress/status panel** — deterministic aggregation: stage N/total, pass/fail counts, wall-clock and token/cost spend per stage. Treat every number here as ground truth; if it disagrees with what you observe, the dashboard has a bug, not the pipeline.
- **Diff/parity panel** — deterministic comparison output (expected vs. actual, byte or field-level diff) attached to agentic-stage results. This is the panel to trust most: it's the closest thing to an objective pass/fail in the whole system.
- **Agent reasoning / trace panel** (if present) — this is a *log*, not a verdict. New people consistently over-trust confident-sounding agent explanations here; the standing rule from this project's ML-review discipline applies directly: an agent's stated justification is not evidence its output is correct, only the parity/compile results are. Read this panel for debugging *why*, never for confirming *whether*.
- **Cost/governance panel** (if present) — deterministic ledger of spend. Read once per run to build intuition for what a 3-program migration should cost; this is the baseline against which any future larger-repo estimate gets sanity-checked.

30-minute dashboard literacy checkpoint: given a screenshot of a failed run, the new person should be able to say which panel tells them *what* failed (progress panel: stage X), which tells them *how badly* (parity panel: N/M cases diverged), and which tells them *why* — with the caveat that the "why" is a hypothesis, not a fact, until re-verified against a re-run.

## 4. Documentation reading order — first vs. later

**Read before touching anything (this is the minimum to not cause harm):**
1. This doc (§0–§3).
2. `cobol-accounting-system/README.md` and `TESTPLAN.md` — the fixed scope and acceptance surface.
3. Whatever single doc in this `design/` series defines the deterministic/agentic stage boundary authoritatively (the pipeline architecture doc — read its stage table, skip its rationale prose on a first pass).
4. The skill + agent definition pair used in the walkthrough above (§1.3) — concrete before abstract.

**Read after the first successful local run, on demand:**
5. Any cost-governance or model-routing design doc — only relevant once you've seen one real cost report to compare it against.
6. Any CI/CD gating design doc — only relevant once you understand what "pass" means locally; reading gating rules before running the pipeline once is abstract and forgettable.
7. Parser/COBOL-semantics deep-dive docs — needed only when debugging a specific extraction failure, not for general orientation. Treat as reference material, not onboarding material.
8. Any multi-agent-framework comparison docs (Strands / Claude SDK / MSFT Agent Framework / AWS Transform, if this project surveys more than one) — these matter for someone choosing or changing the orchestration substrate, not for someone learning what the system currently does. Explicitly deprioritize for a first-week read.

**Anti-pattern to call out explicitly:** reading the full architecture document set before running anything. This project's own scientific-rigor standard (verify before asserting) applies to onboarding too — a person who can recite five design docs but hasn't run the pipeline once and read one real parity diff has unverified, not verified, understanding. Sequence hands-on before comprehensive.

## Open gaps to flag back to the team

- Confirm whether the live dashboard actually visually separates deterministic vs. agentic stages, or whether that split currently only exists in engineers' heads / architecture docs. If the latter, this onboarding doc is teaching a mental model the UI doesn't reinforce — worth a dashboard follow-up (`10-dashboard` track) to add an explicit badge per stage.
- Confirm a dry-run/single-stage mode actually exists (§2.2–2.3 assume one); if not, the fallback is manually invoking the relevant skill/agent in isolation, which should be documented as a named recipe rather than left for the new person to reverse-engineer.
