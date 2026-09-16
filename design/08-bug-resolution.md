# 08 — Bug Detection and Resolution Loop for Parity Gate Failures

Status: design (not implemented). Scope: the loop that fires when the Parity Gate
(behavioral-equivalence test suite comparing COBOL reference output against the
migrated C# output) reports a divergence during agentic migration of
`/home/frg/creai/cobol/cobol-accounting-system` (COBOL `main.cob` / `operations.cob` /
`data.cob` → C#, per the surrounding phase docs 01–07 in this `design/` tree, not yet
written at the time of this doc).

Core thesis, taken directly from the Anthropic internal migration retrospective this
system is modeled on: **a divergence is a process defect until proven otherwise, not a
file defect.** The default action on failure is never "patch the C# file and rerun." The
default action is "classify the divergence, then decide whether the fix belongs in the
code, in the test oracle, or in the rulebook that generates code." Patching the file is
one *output* of the loop, not the entry point.

---

## 1. Triage taxonomy

Every Parity Gate failure lands in exactly one of four buckets. Triage happens before
any code is touched.

### 1.1 `REAL_BUG` — migration defect
The C# does not implement what the COBOL specifies. The COBOL is the source of truth;
the port is wrong. Examples: `COMPUTE` truncation/rounding mode not replicated
(COBOL `ROUNDED` vs. default truncation), `PACKED-DECIMAL`/`COMP-3` scale mismatch,
`PERFORM ... VARYING` off-by-one against a C# `for`, a `88`-level condition-name
mistranslated as a boolean instead of a value-set membership test, paragraph fall-through
semantics (COBOL sections without `GOBACK` fall into the next paragraph) dropped in a
method-per-paragraph refactor.

### 1.2 `INTENTIONAL_IMPROVEMENT` — proposed, not silently applied
The COBOL behavior is undesirable and the agent (or operator) wants the C# to do
something better: e.g. COBOL silently truncates an overflowing `PIC 9(5)` amount field
instead of raising; C# should throw `OverflowException`. This bucket is **never**
auto-resolved by an agent. It requires an explicit, logged, human-approved waiver before
the Parity Gate is allowed to pass with divergent output at that test vector. See §3.

### 1.3 `LEGACY_QUIRK_TO_PRESERVE` — bug-for-bug fidelity required
The COBOL behavior is objectively wrong or arbitrary but downstream systems (reports,
regulators, reconciliation against 30 years of ledger data) depend on it exactly as-is.
Example: COBOL `DIVIDE ... GIVING ... REMAINDER` truncates toward zero on negative
operands in a way that looks like a bug but is baked into every historical statement.
The fix is to make the C# *reproduce* the quirk, with a comment citing the COBOL
paragraph and line, not to "correct" it.

### 1.4 `TEST_ORACLE_DEFECT` — the Parity Gate itself is wrong
The comparator has a bug: wrong tolerance on decimal comparison, timezone-naive date
diff, a golden fixture generated from an already-broken COBOL run, non-determinism in
test data generation (unseeded RNG, wall-clock timestamps in output). This bucket routes
to fixing the harness/fixtures, never the migrated code.

---

## 2. Decision authority per bucket — deterministic vs. LLM vs. human

Authority is assigned by how cheaply and reliably the question can be answered
mechanically, not by how "important" the bug looks.

| Step | Mechanism | Rationale |
|---|---|---|
| Detect divergence | **Deterministic** (Parity Gate diff: exact for integers/strings, epsilon-bounded decimal compare for currency, semantic date compare) | No judgment needed to know two outputs differ. |
| Classify bucket (1.1–1.4) | **LLM judgment, gated** | Requires reading COBOL semantics, the C# diff, and the failing test vector together — a comprehension task, not a lookup. The LLM proposes a bucket + cites COBOL source lines + confidence score. |
| Accept `REAL_BUG` classification | **LLM autonomous** if confidence ≥ threshold (see §5) AND the fix is scoped to the same paragraph/method already implicated by the failing test | This is the common case and must not require a human in the loop for every single off-by-one, or the loop cannot scale past a handful of bugs. |
| Accept `INTENTIONAL_IMPROVEMENT` | **Human-in-the-loop, mandatory, no exception** | This is a scope decision (does the ported system get to behave differently from the legal/audited legacy system?) that carries business and compliance risk no LLM confidence score should be trusted to clear alone. |
| Accept `LEGACY_QUIRK_TO_PRESERVE` | **Human-in-the-loop on first occurrence per quirk class; deterministic replay after** | First time a given COBOL arithmetic/rounding quirk is flagged, a human confirms "yes, preserve." Once confirmed, the fact is written into the rulebook (§4) and every future instance of the *same* quirk class is applied deterministically by rule lookup, not re-litigated by the LLM. |
| Accept `TEST_ORACLE_DEFECT` | **LLM proposes, deterministic CI check enforces** | The LLM identifies the harness bug; a fix to the harness must itself pass a meta-test (the harness change is reviewed like any other code change, plus a regression fixture proving the old fixture was wrong) before it's allowed to silence the original failure. |
| Low-confidence classification (any bucket) | **Human-in-the-loop, blocking** | Ambiguity is the one condition that always escalates regardless of bucket. |

Rule of thumb: deterministic where determinism is possible (detection, quirk replay,
oracle-fix verification); LLM where comprehension is required and error cost is
recoverable (bug classification, fix authoring); human where the decision changes the
system's contractual behavior (improvements, first-time quirk waivers, low confidence).

---

## 3. The fix–verify–reapply loop

```
                      ┌─────────────────────┐
                      │  Parity Gate FAILS   │
                      │  (test vector T,     │
                      │   field F, expected  │
                      │   E vs actual A)     │
                      └──────────┬───────────┘
                                 ▼
                 ┌───────────────────────────────┐
                 │ 1. TRIAGE (LLM + COBOL/C# diff)│
                 │  bucket ∈ {REAL_BUG,           │
                 │   INTENTIONAL_IMPROVEMENT,     │
                 │   LEGACY_QUIRK, ORACLE_DEFECT} │
                 │  + confidence + cited lines    │
                 └──────────────┬─────────────────┘
                                 ▼
                 ┌───────────────────────────────┐
                 │ 2. GATE ON CONFIDENCE / BUCKET │
                 │  low-conf OR IMPROVEMENT OR    │
                 │  first-of-quirk-class          │
                 │        → HUMAN CHECKPOINT      │
                 │  else → proceed autonomously   │
                 └──────────────┬─────────────────┘
                                 ▼
                 ┌───────────────────────────────┐
                 │ 3. AUTHOR FIX                  │
                 │  REAL_BUG      → patch C#      │
                 │  IMPROVEMENT   → patch C# +    │
                 │                  waiver record │
                 │  LEGACY_QUIRK  → patch C# to   │
                 │                  replicate +   │
                 │                  cite COBOL loc│
                 │  ORACLE_DEFECT → patch harness/│
                 │                  fixture        │
                 └──────────────┬─────────────────┘
                                 ▼
                 ┌───────────────────────────────┐
                 │ 4. RE-RUN PARITY GATE          │
                 │  full suite, not just vector T │
                 │  (regression check on already- │
                 │   passing vectors is mandatory)│
                 └──────────────┬─────────────────┘
                        pass ────┼──── fail again (same T)
                          │      │
                          ▼      ▼
                 ┌────────────┐ ┌───────────────────────────┐
                 │ 5. RECORD  │ │ 6. ESCALATE, do NOT retry  │
                 │  outcome + │ │  the same fix a 2nd time   │
                 │  bucket +  │ │  blindly — see §4 repeated-│
                 │  fix into  │ │  failure escalation        │
                 │  ledger    │ └───────────────────────────┘
                 └──────┬─────┘
                        ▼
                 ┌───────────────────────────────┐
                 │ 7. RULEBOOK UPDATE CHECK       │
                 │  does this bug class recur     │
                 │  across ≥N vectors/paragraphs? │
                 │        → see §4                │
                 └───────────────────────────────┘
```

Invariants enforced by the loop, independent of bucket:
- **Full regression, not point-fix verification.** Step 4 reruns the entire Parity
  Gate corpus, not only vector `T`. A fix scoped to one paragraph frequently repairs or
  (worse) breaks sibling call sites (e.g. a shared `PERFORM` paragraph invoked from
  three places in `operations.cob`).
- **No blind retry.** If the same test vector fails twice with different fix attempts,
  the loop does not try a third mechanical patch — it escalates to a human with the
  fix history attached (see §4, repeated-failure trigger). Blind retry is the exact
  failure mode this design exists to prevent.
- **Every accepted fix is attributable.** The ledger entry (step 5) records: test
  vector id, COBOL source lines cited, bucket, confidence, who/what approved
  (agent-autonomous vs. human name), the diff, and — for `LEGACY_QUIRK` and
  `INTENTIONAL_IMPROVEMENT` — the waiver rationale in plain language a non-engineer
  auditor can read, since this is a financial (accounting-system) migration.

---

## 4. Repeated-failure → rulebook update (the "fix the process, not the code" lesson)

The Anthropic retrospective's central lesson: when the same *class* of divergence shows
up across multiple files, the correct response is not N file-by-file patches — it's one
change to the process that generates the code (system prompt / migration ruleset /
codegen template), followed by regenerating or re-verifying the affected files under the
corrected process.

**Trigger.** A rulebook update is proposed automatically when either:
- the same triage bucket + same COBOL construct (e.g. "PIC clause with implied decimal
  point mapped without scale", "88-level condition-name treated as boolean",
  "`ON SIZE ERROR` clause dropped") recurs across **≥3 distinct paragraphs or files**, or
- the fix–verify loop needed a 2nd human-escalated attempt on the same vector (§3 step 6)
  — any second escalation is itself a rulebook-update trigger regardless of recurrence
  count, since it signals the first fix attempt encoded a wrong general assumption, not
  just a local slip.

**What a rulebook is, concretely, in this system.** The persistent artifact that steers
the migration agent's codegen — the system prompt / migration skill instructions /
few-shot translation rules the agent consults per COBOL construct (e.g. "how to
translate `COMPUTE ... ROUNDED`", "how to translate `88`-level condition names", "how to
translate paragraph fall-through"). This is distinct from any single generated C# file.

**Update procedure:**
1. **Generalize the defect.** State the rule that was violated as a construct-level
   statement, not a file-level one: "COBOL `PIC S9(7)V99 COMP-3 ROUNDED` compute targets
   must map to `decimal` with `Math.Round(x, 2, MidpointRounding.AwayFromZero)`, not
   plain C# division," rather than "fix line 214 of `LedgerPosting.cs`."
2. **Author the rule as an explicit, versioned rulebook entry** with: the COBOL pattern
   it matches, the required C# pattern, the failing vector(s) that surfaced it, and the
   bucket it belongs to (a `LEGACY_QUIRK` rule and a `REAL_BUG` rule look different — the
   former documents *why* the odd behavior is intentional, so future agents don't
   "fix" it again).
3. **Re-scan, not re-patch.** Search the already-migrated codebase for every other
   occurrence of the COBOL pattern the rule now covers (deterministic grep/AST match on
   the COBOL side is possible and preferred over asking the LLM to "remember" — COBOL
   fixed-format columns and `PIC` clauses are regex/parser-tractable). Regenerate or
   patch every match under the new rule in one batch, then run the full Parity Gate
   once over the batch — not once per file.
4. **Version the rulebook change itself** (git commit / rulebook changelog entry) with
   a pointer to the ledger ids (§3 step 5) that motivated it, so a future audit can
   trace "why does the migration prompt say X" back to concrete evidence.
5. **Add a regression fixture** for the corrected construct so a future prompt/rulebook
   edit can't silently regress this class again — this is the harness-side analog of a
   unit test for a code fix.

**Why this must be mandatory, not optional-when-convenient:** file-by-file patching
without a rulebook update guarantees the same construct-level mistake reappears every
time the agent encounters that COBOL pattern in a not-yet-migrated file, because nothing
changed about what taught the agent to make the mistake in the first place. The
Parity Gate score can look like it's trending up while defect *rate per new file* stays
constant — the visible signal (fewer failures) then reflects "fewer files left to
migrate," not "fewer mistakes per file," which is the metric that actually matters for
throughput on the remaining backlog.

---

## 5. Confidence threshold and calibration

The LLM triage step (§2) must emit a numeric or ordinal confidence alongside the bucket,
and that confidence must be calibrated against the ml-senior verify-before-assert
standard already governing this operator's other model work: **plausible is not
verified.** Concretely:

- Confidence is not self-reported free text ("I'm quite confident") — it is derived from
  a checklist the triage prompt must complete: (a) COBOL source lines cited and quoted
  verbatim, (b) the specific PIC/COMPUTE/PERFORM semantics invoked named explicitly,
  (c) the C# diff line(s) responsible for the divergence identified, (d) at least one
  alternative bucket considered and explicitly ruled out with a reason. Any incomplete
  checklist item forces `LOW_CONFIDENCE` regardless of what the model otherwise states.
- The autonomous-fix threshold (§2, `REAL_BUG` autoship path) starts conservative
  (require all four checklist items plus a fix scoped to the single already-implicated
  paragraph) and is only loosened after the ledger (§3 step 5) shows a track record —
  e.g. N consecutive autonomous `REAL_BUG` fixes that passed full regression with zero
  human overrides — not loosened by default or by assumption.
- Every human override of an LLM triage decision (human says `REAL_BUG` was actually
  `LEGACY_QUIRK`, or vice versa) is itself logged and periodically reviewed as a set —
  if overrides cluster on one COBOL construct, that construct's confidence checklist is
  insufficient and gets a rulebook-level addition (this is the same §4 mechanism applied
  to the triage rules, not just the codegen rules).

---

## 6. Interfaces this design assumes (for the implementing phase docs)

- Parity Gate emits structured failure records: `{vector_id, cobol_source_ref,
  csharp_source_ref, field, expected, actual, diff_kind}` — not just a pass/fail count.
  `diff_kind` distinguishes numeric-tolerance, string-exact, date-semantic, and
  ordering/sequencing mismatches, since triage needs this to reason about bucket.
- A ledger store (append-only; file or lightweight DB under
  `cobol-accounting-system/` or a sibling `migration-ledger/`) persists every §3 step 5
  record and every §5 override record — this is the substrate the rulebook-update
  trigger (§4) queries for recurrence counts.
- The rulebook itself lives as a versioned file (or small set of files) consumed by the
  migration agent's system prompt/skill, separate from any single generated C# file, so
  that "fix the process" has a concrete artifact to edit and diff.
- Human checkpoints are a blocking interaction (not fire-and-forget) — the loop halts at
  step 2 or step 6 until an explicit human decision is recorded in the ledger; it does
  not proceed on a timeout or default.
