# 14 — Backend gaps (unconnected or stubbed)

For the backend team. Honest inventory of what the UI and schema already expect but the pipeline does **not** execute yet. Intake (zip + GitHub) is wired; do not re-litigate the 20 MB cap — it is gone.

Verified against `backend/routers/pipeline.py`, `backend/routers/intake.py`, `backend/db.py`, `migration-state/schema.sql`, and `frontend/src/` on 2026-09-15.

---

## Already connected (do not rebuild)

| Piece | Status |
| --- | --- |
| `POST /migration/intake` zip | Streams to disk. Raw cap **2 GB**, uncompressed **8 GB** (zip-bomb only). |
| `POST /migration/intake` GitHub | Public `https://github.com/owner/repo` only, `git clone --depth 1`, timeout **600s**. URL wins if a leftover zip is also present. |
| Phase 0 inventory | Whole-tree walk, sha256, LOC, `file_kind`. Deterministic. |
| Phase 1 structural parse | Regex fallback. Emits `cobol_analyses`. **Not ProLeap.** |
| Phase 2 business-logic extract | Headless Claude per COBOL source, budget `$5`. Writes `business_logic_extracts` + `cost_logs`. |
| Phase 3 CALL graph | Regex `CALL "..."` / `'...'`. |
| Phase 4 C# conversion | Headless Claude, leaf-first waves, writes `generated_files`. |
| `POST /migration/{run_id}/gate` | Persists `approved` / `rejected` (+ comment) in `gate_decisions`. **UI Step 4 now calls it.** |
| `GET /migration/{run_id}/events` | SSE union of PhaseEvent + FileEvent. |
| `GET /migration/{run_id}/extracts` | Implemented. **Frontend does not fetch it.** |
| `GET /migration/{run_id}/cost` | Implemented. Header cost chip consumes it after `/start`. |

---

## Gap 1 — Phase 5 test generation (stub)

**Today:** `_run_phases` appends `SKIPPED` / `"stub — see design/14-backend-gaps.md"`. No `dotnet test`. No `test_results` rows.

**Skill:** `.claude/skills/csharp-test-generation/SKILL.md`

**Do this:**

1. After Phase 4, for each `generated_files` row that compiled, invoke headless Claude with the skill prompt + the matching `business_logic_extracts.business_rules_json`.
2. Write xUnit tests next to the generated C# (layer-mirrored test project).
3. Run `dotnet test --collect:"XPlat Code Coverage"`.
4. Insert `test_results` (`line_coverage`, `branch_coverage`, `passed`, `report_path`).
5. Gate: line ≥ 90% per migrated class, branch ≥ 85%. Below threshold → `BLOCKED`, do not hand the file to Phase 6.
6. Budget cap (suggest `$PHASE5_BUDGET_USD`, same cost_logs pattern as Phase 2/4).
7. Emit FileEvents (`RUNNING` / `OK` / `FAILED` / `SKIPPED`) so Step 5’s feed is not a single SKIPPED chip.

**Schema already exists:** `test_results`. Do not invent a new table.

---

## Gap 2 — Phase 6 parity (skipped even when compilers exist)

**Today:** `_phase6_verdict()` finds `cobc` and `dotnet` on this machine, then still SKIPPED because “no generated C# yet to validate (Phase 4/5 still stubbed)”. That comment is stale — Phase 4 **does** generate C#. The real blockers are: Phase 5 stub, and Phase 6 never reads `generated_files` or runs fixtures.

**Skill:** `.claude/skills/parity-validation/SKILL.md`  
**Design:** `design/06-parity-testing.md`

**Do this:**

1. Require Phase 4 OK + Phase 5 OK for the unit (do not start parity on a file that failed tests).
2. `cobc -x` the original COBOL → `cobol_oracle`.
3. `dotnet build` the generated solution.
4. Run both against the same stdin fixtures (fresh process each run — COBOL WORKING-STORAGE resets per launch).
5. Byte-diff stdout (normalize timestamps/whitespace only).
6. Insert `parity_verdicts` per fixture (`match`, `divergence_class`).
7. 100% match required at demo scale. Mismatch → `bugfix-loop` skill, not a silent SKIPPED.

**Schema already exists:** `parity_verdicts`.

---

## Gap 3 — Phase 7 HITL is in the wrong place

Two different gates exist. They are not the same moment in the design.

| Gate | When design wants it | What exists |
| --- | --- | --- |
| Architecture approval (wizard Step 4) | Before the user *looks* at Migrate & Test | UI + `POST /gate`. Pipeline **does not wait**. `/start` already ran Phase 4. |
| Phase 7 human-approval-gate | After Phase 6 parity, before merge | Pipeline emits SKIPPED. Endpoint writes `gate_decisions` but `_run_phases` never pauses. |

**Do this (pipeline, not UI chrome):**

1. Split `/start`: run Phases 0–3 (analysis) immediately; **do not** start Phase 4 until `gate_decisions.decision = approved` for that `run_id`.
2. After Phase 6 OK, set `gate_status=pending`, wait (poll SQLite or an asyncio Event) for a second `approved` on the **parity diffs**, then run Phase 8.
3. A `rejected` with empty comment must 422 — the column exists so the fixer can read *why*.
4. Frontend Step 5 should keep streaming SSE across that pause (`live` chip stays on).

Until (1) lands, clicking Approve on Step 4 records the decision after conversion may already have started. That is the current product bug, not a missing button.

---

## Gap 4 — Phase 8 merge (stub)

**Today:** SKIPPED `"not reached"`.

**Do this:**

1. Copy/commit generated C# from `migration-state/runs/{run_id}/` into a git-versioned output tree keyed by ULID (skill: cobol-to-csharp-conversion “Output is git-versioned per run”).
2. Only after Phase 6 match **and** Phase 7 approved.
3. Emit the solution path in the Phase 8 `detail` so the UI can link it. No new endpoint strictly required; a `GET /migration/{run_id}/output` would help.

---

## Gap 5 — ProLeap (Phase 1 still regex)

Phase 1 detail text already says `regex fallback parse (ProLeap not wired)`. Skill `cobol-structural-analysis` prefers ProLeap (JVM/ANTLR). Regex is allowed only if the parser is missing, and the fallback **must stay visible** on the event.

**Do this:** detect `java` + ProLeap jar (env `PROLEAP_JAR`), parse each COBOL file, write the same `cobol_analyses` JSON shape. Keep regex as explicit fallback.

---

## Gap 6 — Frontend does not consume Phase 2 extracts

`GET /migration/{run_id}/extracts` returns `suggested_component_name`, user stories, and rules. Step 3 (`targetArchitecture.ts`) names use cases from **filenames** (`transaction_posting.cbl` → `TransactionPosting`) and the copy still says Phase 2 naming is stubbed.

**Do this (frontend, small):** after Phase 2 OK (or on Step 3 mount), `GET .../extracts` and pass `suggested_component_name` into `deriveMapping` / `deriveTargetArchitecture`. Do not invent names in the UI when the extract exists.

---

## Gap 7 — Tables written vs never written

| Table | Writer today |
| --- | --- |
| `migration_runs` | intake + `/start` status update |
| `cobol_files` | intake |
| `cobol_analyses` | Phase 1 |
| `business_logic_extracts` | Phase 2 |
| `dependency_edges` | **not inserted** — Phase 3 only emits FileEvents; CALL graph is in-memory |
| `generated_files` | Phase 4 |
| `test_results` | nobody |
| `parity_verdicts` | nobody |
| `cost_logs` | Phase 2 (and Phase 4 if it logs) |
| `gate_decisions` | `POST /gate` (now from UI) |

Phase 3 should INSERT `dependency_edges` (`CALL` / `COPY` / `PERFORM`) so Phase 4 waves and later audits do not depend on process memory.

---

## Gap 8 — `/start` blocks the HTTP request for the whole run

`POST /migration/{run_id}/start` `await`s `_run_phases` (Phase 2+4 LLM, minutes). SSE is a second request, so it still streams, but the `/start` connection sits open until Phase 8’s SKIPPED. Under a proxy idle timeout this looks like a hung run.

**Do this:** `asyncio.create_task(_run_phases(...))`, return `202` + `status=RUNNING` immediately. `/status` already reads `_run_state`.

---

## Suggested build order

1. Persist `dependency_edges` (deterministic, no LLM).
2. Background `/start` (ops reliability).
3. Pause Phase 4 until Step 4 `approved` (fixes HITL lying).
4. Phase 5 tests → Phase 6 fixtures → Phase 8 merge.
5. ProLeap; wire extracts into Step 3.

Do not mark Phase 5/6/8 `OK` without writing the tables above. SKIPPED with a pointer here is the honest state.
