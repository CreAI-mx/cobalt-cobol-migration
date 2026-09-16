# Exploration/Onboarding documentation package — design

**Scope.** This is for the Exploration subsystem only (`backend/exploration_core.py`,
`backend/exploration_orchestrator.py`, `backend/routers/exploration.py`) — the multi-agent
onboarding pass that produces the `ExplorationPack`. It is **not** the migration/conversion
pipeline (`backend/llm.py:convert_work_item`, Phase 4 onward). No files outside this document were
modified while writing it.

**Reference analyzed.** `/tmp/docs-ref/docs/` — a documentation package for a 3-file, 85-line COBOL
account system (`main.cob`, `operations.cob`, `data.cob`). All 19 files were read in full: README,
`00-trazabilidad/esquema-de-ids.md` + `registro-trazabilidad.csv` (61 rows), `01-funcional/*` (22
business rules, 4 use cases, glossary, 10 open questions), `02-tecnico/*` (program inventory, data
dictionary, dependency map, integration/batch inventories, 9 Mermaid AS-IS diagrams, complexity/risk),
`03-to-be/*` (target architecture, OpenAPI, COBOL→C# mapping, placeholder modernized-system doc),
`04-evidencia/*` (test plan, `ejecutar-pruebas-legacy.sh`, equivalence report, rule coverage), and
`docs/tools/validar_trazabilidad.py`.

---

## 1. What the current pack already covers, section by section

`build_exploration_pack()` (`backend/exploration_core.py:169`) returns a dict with
`{inventory_summary, modules[], call_graph_resolved, open_items, planner_seed}`. Mapped against the
reference package:

| Reference section | Current pack coverage | Gap |
|---|---|---|
| 00 Trazabilidad (IDs + CSV) | None. `draft_business_rules()` (`exploration_core.py:142`) generates `id: f"BR-{para}"` per paragraph but never records a file:line, only `anchors: [f"{path}:{para}"]` — a paragraph *name*, not a line number. | Full gap — see §4. No registry, no line numbers to build one from. |
| 01 Catálogo de reglas de negocio | Stub rules exist (`draft_business_rules`) plus real ones from `_agentic_business_rules()` (`exploration_orchestrator.py:37`) once Strands runs. Rules have `id/text/anchors/source` — no `origen` (line-anchored), no `verificación`, no `estado_validación`, no per-rule risk link. | Schema is close; needs richer fields, not a redesign. |
| 02 Casos de uso | None. `PARAGRAPH_RE` finds paragraph names; nothing groups them into actor/event/flow use cases. | Full gap — LLM territory (§3). |
| 03 Glosario de negocio | None. | Full gap — LLM territory. |
| 04 Preguntas abiertas | `open_items` exists but is populated only from `build_graph_edges()`'s unresolved `CALL` targets (`exploration_core.py:84`) — a narrow, purely structural source. No blocking/non-blocking distinction, no linkage to business rules. | Partial — mechanism exists, source is too narrow. |
| 05 Inventario de programas | `inventory_summary` = 3 counts (`files, programs, copybooks`). Real per-program metrics (LOC, division count, paragraph count, CALL fan-in/fan-out, dead paragraphs) are computed transiently inside `build_exploration_pack`'s loop but discarded — only aggregated into `mod["risks"]`. | Cheap to add — data already computed, just not persisted per-program (§2). |
| 06 Diccionario de datos | `parse_structural()`'s `PIC_FIELD_RE` (`exploration_core.py:24`) already extracts name/PIC/COMP-3/REDEFINES tags per variable, but this list is discarded after complexity scoring — never surfaced in the pack. | Cheap — parsing exists, only assembly is missing (§2). |
| 07 Mapa de dependencias | `call_graph_resolved.edges` + `topological_order` cover the call graph. No fan-in/fan-out numbers, no coupling classification, no impact-analysis narrative. | Partial — graph exists, analysis layer missing. |
| 08 Inventario de integraciones | None. Never checked. | Full gap, but cheap and must be evidence-based, not assumed (§2). |
| 09 Catálogo de procesos batch | None. | Same as above. |
| 10 Diagramas AS-IS (Mermaid) | None rendered; the data (`call_graph_resolved`, `modules`) is sufficient to generate at least a call graph diagram. | Cheap — pure rendering from existing data (§2). |
| 11 Complejidad y riesgo | `complexity_tier` (LOW/MEDIUM/HIGH) per file and free-text `mod["risks"]` strings exist. No risk registry with IDs, severity, or a migration-order recommendation beyond `conversion_order_hint`. | Partial — needs an ID'd registry and a written risk narrative (LLM, §3). |
| 12 Arquitectura objetivo .NET | `suggested_target_projects` (path guesses) and `planner_seed.directive_fragments` exist. No bounded-context analysis, no declared-assumptions table gated on open questions. | Full gap — LLM territory, and must be explicitly gated on `open_items` (§3, §5). |
| 13 OpenAPI spec | None. | Full gap — LLM territory. |
| 14 Mapeo COBOL→C# | None beyond the implicit PIC→type mapping baked into conversion prompts elsewhere in the pipeline (not part of Exploration). | Full gap — LLM territory. |
| 15 Modernized system doc | N/A — explicitly a post-conversion placeholder in the reference itself. | Out of scope for Exploration by definition; same in Cobalt. |
| 16–18 Evidencia (test plan, equivalence, coverage) | None. | **Out of scope for Exploration** — see §6 below; requires actually compiling/running COBOL, which Exploration never does. |

**Bottom line:** sections 05–07 and 10 are mostly a data-plumbing problem (the numbers already
exist somewhere in a function's local scope and just need to be returned). Sections 08–09 need a
real deterministic check, not an assumption. Sections 00, 01, 02, 03, 04, 11, 12, 13, 14 need either
new deterministic passes or genuine LLM reasoning. Sections 16–18 are declared out of scope for this
subsystem.

---

## 2. New deterministic functions (no LLM) — cheap wins

All of these belong in `exploration_core.py`, next to `parse_structural`, and read data that is
already being computed per-file in `build_exploration_pack`'s loop (`exploration_core.py:187-201`)
— today that loop throws most of it away after risk-string extraction.

### 2.0 Prerequisite: line numbers in `parse_structural` (blocking everything below)

`parse_structural()` currently returns paragraph names (`PARAGRAPH_RE.finditer` group only),
variable dicts without a line field, and `calls` as bare strings from `CALL_RE.findall(text)` — none
of them carry a line number today. `_complexity_tier` and REDEFINES detection do compute a line
*string* transiently (`text.rfind("\n", 0, m.start())`, `exploration_core.py:52`) but discard the
line *number*. Every citation in §00, §05, §06, §07 depends on line numbers existing, so this is
P0, not a refinement:

```python
def _line_no(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1
```

Add `"line": _line_no(text, m.start())` to each variable dict, each paragraph entry (switch
`paragraphs_json` from `list[str]` to `list[dict]` with `name`/`line` — additive under a pack schema
bump, see §5), and each CALL match (switch `CALL_RE.findall` to `CALL_RE.finditer` to get `.start()`).

### 2.1 Program inventory (→ 05)

`inventory_program(struct: dict, path: str, loc: int) -> dict` — returns `{path, program_id, loc,
divisions, paragraph_count, variable_count, comp3_count, redefines_count, call_fanout,
complexity_tier, dead_paragraphs}`. `dead_paragraphs` = paragraphs never targeted by a `PERFORM
<name>` in the same file — a `PERFORM_RE = re.compile(r"PERFORM\s+([A-Z0-9][A-Z0-9-]*)", re.I)`
scan, set-difference against paragraph names. Assemble a `program_inventory: list[dict]` at the top
level of the pack, one row per COBOL file — currently the equivalent data is computed then discarded
inside the modules loop.

### 2.2 Data dictionary (→ 06)

`data_dictionary(struct: dict, path: str) -> list[dict]` — reshapes `variables_json` (already has
name/pic/tags/line after §2.0) into `{path, name, pic, line, comp3, redefines, level_guess}`.
`level_guess` = the leading digits already captured but discarded by `PIC_FIELD_RE`'s optional group
1 (`exploration_core.py:25`, `(\d+\s+)?`). Assemble as top-level `data_dictionary: list[dict]`,
deduplicated by `(path, name)`.

### 2.3 Integration + batch inventory (→ 08, 09) — must be evidenced, not assumed

This must never simply assert "none" — that would be as fabricated as inventing a business rule.
Run named checks and record what was scanned and what matched:

```python
INTEGRATION_CHECKS = [
    ("file_section",  re.compile(r"^\s*FILE SECTION\b", re.M | re.I)),
    ("file_io",       re.compile(r"\b(OPEN|READ|WRITE|CLOSE)\s+[A-Z0-9-]+", re.I)),
    ("embedded_sql",  re.compile(r"EXEC\s+SQL", re.I)),
    ("cics",          re.compile(r"EXEC\s+CICS", re.I)),
    ("sort_merge",    re.compile(r"\b(SORT|MERGE)\b", re.I)),
    ("jcl_present",   None),  # checked via classify_kind() on inventory_source() output, not regex
]

def check_integrations(files: list[SourceFile], texts: dict[str, str]) -> dict:
    results = []
    for name, pattern in INTEGRATION_CHECKS:
        if pattern is None:
            hits = [f.path for f in files if classify_kind(f.path) == "jcl"]
        else:
            hits = [p for p, t in texts.items() if pattern.search(t)]
        results.append({"check": name, "files_scanned": len(texts), "hits": hits})
    return {"checks": results, "verdict": "none_found" if not any(r["hits"] for r in results) else "found"}
```

Same shape covers batch processes (JCL presence, `SORT`/`MERGE` verbs, schedule-looking paragraph
names). Output goes to top-level `integration_inventory` / `batch_inventory` keys — a table of
checks with hit counts, matching the reference's "verification by type — result: none" framing
rather than a bare claim.

### 2.4 AS-IS Mermaid diagrams (→ 10)

Pure rendering from data that already exists (`call_graph_resolved.edges`, `modules`) — no new
parsing:

```python
def render_call_graph_mermaid(edges: list[dict]) -> str:
    lines = ["graph TD"]
    for e in edges:
        lines.append(f'  {_mermaid_id(e["from_path"])}["{e["from_path"]}"] --> {_mermaid_id(e["to_path"])}["{e["to_path"]}"]')
    return "\n".join(lines)

def render_module_diagram(modules: list[dict]) -> str: ...   # one flowchart per module cluster
```

Two diagrams are free (call graph, module clustering). A third — data flow of a named field, e.g.
"balance" — needs cross-referencing `data_dictionary` writes/reads per paragraph, which is doable
deterministically once §2.0/§2.2 exist, but is a second pass, not P0.

### 2.5 Risk registry with stable IDs (→ 11, partial)

Convert today's free-text `mod["risks"]` strings into `{"id": f"RSK-{n:03d}", "text": ..., "anchor":
"path:line", "severity": "critical|high|medium|low"}`. Severity can be assigned deterministically for
known patterns (unsigned PIC with no `ON SIZE ERROR` → high; `REDEFINES` → medium; dead paragraph →
low), same as the reference does narratively — the *classification rule* is deterministic even
though the *narrative* explaining a risk should still go through the LLM pass in §3.

---

## 3. What genuinely requires an LLM, and which pattern to use

Two output shapes appear in the reference, and Cobalt already has one proven pattern per shape —
this is a "which existing tool fits," not an open framework choice:

| Reference section | Output shape | Pattern | Precedent already in Cobalt |
|---|---|---|---|
| 01 Business rules (enriched: enunciado + origen + verificación) | Structured JSON merged back into the pack | **Strands** (`_agentic_business_rules`) | `exploration_orchestrator.py:37-101` — already calls a real agent, parses a JSON array, records cost via `cost_logs`, falls back to drafts on any failure. Extend its prompt/schema; don't build a second mechanism. |
| 02 Use cases, 03 Glossary, 04 Open questions (narrative synthesis) | Structured JSON (arrays of use-case objects, glossary terms, question objects with blocking flags) | **Strands**, same call shape as above, one extra prompt/parse pair per section | Same file, same pattern — a second (or combined) `_agentic_*` function alongside `_agentic_business_rules`. |
| 11 Risk narrative (why each RSK-* matters, not just its classification) | Structured JSON, one paragraph per registry entry | **Strands** | Same. |
| 12 Target architecture, 14 COBOL→C# mapping decisions, 13 OpenAPI spec, 00-README-level prose | Whole **files** — multi-page `.md` prose, a `.yaml` spec | **headless `claude -p`**, `--allowedTools Read,Write` | `backend/llm.py:651 write_mvp_docs()` — exact precedent: subprocess, `--output-format stream-json`, cost/usage parsed from the `result` envelope, writes directly into a target directory. |

**Rule of thumb, stated once:** if the output feeds back into the pack JSON (frontend renders it,
`planner_seed` consumes it) → Strands, structured, small, cheap, already has cost accounting wired.
If the output *is* a deliverable file meant to be read as prose or a spec by a human → headless
`claude -p` writing directly into `migration-state/runs/{run_id}/docs/`, mirroring
`write_mvp_docs`'s allow-listed `Read,Write` sandboxing so the agent can read source it needs but
cannot execute anything.

Do not introduce a third pattern (e.g., a bespoke prompt-and-parse loop outside Strands) for
sections that fit either of the two above.

---

## 4. Traceability: a real CSV + a real validator

### 4.1 What "real" requires

The reference validator (`docs/tools/validar_trazabilidad.py`) checks, in order: (1) no duplicate
IDs, (2) every `archivo_fuente` exists, (3) every `linea_inicio`/`linea_fin` is a valid range inside
that file's current line count, (4) every ID cited in prose is declared in the registry, (5) every
declared ID is cited somewhere (dead-registry warning). Running it as-is against `/tmp/docs-ref`
fails 61/61 — it resolves paths from `Path(__file__).resolve().parents[2]`, i.e. its own package
root, not from an arbitrary COBOL source tree. Cobalt's version must resolve `archivo_fuente`
relative to `migration-state/runs/{run_id}/source/`, not the validator's own location.

### 4.2 Registry generation

Once §2.0 line numbers exist, a registry row is mechanical: one row per `program_inventory` entry
(`PGM-nnn`), one per `data_dictionary` entry (`DAT-nnn`), one per structural business-rule draft or
agentic rule (`BR-XXX-nnn`), one per risk registry entry (`RSK-nnn`), one per open item (`QA-nnn`).
`metodo_verificacion` is **always `lectura_codigo`** for everything Exploration produces — never
`ejecucion` (see §6: Exploration does not compile or run COBOL). This must be hardcoded, not left to
an LLM to fill in, or it will eventually fabricate an `ejecucion` claim.

```python
def build_traceability_registry(program_inventory, data_dictionary, business_rules, risks, open_items) -> list[dict]:
    rows = []
    for p in program_inventory:
        rows.append({"id": f"PGM-{p['seq']:03d}", "tipo": "programa", "nombre": p["program_id"],
                     "archivo_fuente": p["path"], "linea_inicio": 1, "linea_fin": p["loc"],
                     "metodo_verificacion": "lectura_codigo", "estado_validacion": "pendiente"})
    for d in data_dictionary:
        rows.append({"id": f"DAT-{d['seq']:03d}", "tipo": "campo", "nombre": d["name"],
                     "archivo_fuente": d["path"], "linea_inicio": d["line"], "linea_fin": d["line"],
                     "metodo_verificacion": "lectura_codigo", "estado_validacion": "pendiente"})
    # ... BR-*, RSK-*, QA-* analogous, anchor parsed from "path:line" strings
    return rows
```

### 4.3 Validator, adapted

Port `validar_trazabilidad.py` nearly verbatim, changing only: (a) the root resolution
(`RUNS_DIR / run_id / "source"` instead of `parents[2]`), (b) the ID pattern to match whatever
prefixes Cobalt's registry actually emits, (c) run it as part of the doc-render step (§5) so a stale
citation fails the render rather than silently shipping. Put it at
`backend/exploration_docs/validate_traceability.py`, invoked from the render step, not exposed as an
API endpoint (it's a build-time gate, not a user action).

---

## 5. Output format: pack JSON grows, plus a rendered `.md` tree

**Decision: both, with the pack as the source of truth and the `.md` tree as a projection.**

- The pack JSON (`exploration_sessions.draft_pack_json` / `locked_pack_json`) stays the
  machine-readable spine. `Step2Exploration.tsx` is being edited live by another agent right now
  against the current schema — new keys (`program_inventory`, `data_dictionary`,
  `integration_inventory`, `batch_inventory`, `mermaid_diagrams`, `traceability_registry`,
  `use_cases`, `glossary`) must be **additive only**. Bump `exploration_pack_schema` from `1` to
  `2` (`exploration_core.py:206`) the first time any new key is added, and never rename or remove an
  existing key — a schema-2 consumer can ignore keys it doesn't know about; a renamed key breaks the
  frontend agent's in-flight work.
- A file tree under `migration-state/runs/{run_id}/docs/` (mirroring the reference's `docs/`
  layout: `00-trazabilidad/`, `01-funcional/`, `02-tecnico/`, `03-to-be/`) is **rendered from the
  pack**, not generated independently — one render function per section, each a pure function of
  pack fields, so the two never drift. This gives the human-facing artifact the reference package
  has (downloadable, greppable, diffable across runs) without a second source of truth. The `claude
  -p` sections (§3, table row 2) write directly into this tree since their output *is* prose files;
  the Strands sections render into pack fields first, then get projected into `.md` by the same
  renderer as everything else, for one consistent rendering path.
- `docs/README.md` at the root of that tree gets the same "start here by role" table the reference
  has, generated deterministically from a static template plus the live counts (rule count, risk
  count, blocking-question count) — no LLM needed for the index page itself.

### Known bug to fix as part of this work, not silently

`exploration_lock` (`routers/exploration.py`, `exploration_lock` handler) calls
`core.build_exploration_pack(run_id, source_dir, locked=True)` **freshly** — it does not pass
`human_notes_by_module`, and it discards whatever `_agentic_business_rules` wrote into
`draft_pack_json`, since `build_exploration_pack` always starts from `draft_business_rules()`'s
deterministic stubs. Locking currently **overwrites agent-produced business rules and human module
notes with deterministic stubs**, and writes that regression into both `locked_pack_json` and
`draft_pack_json`. Any doc-package work must change this: locking should **promote the existing
draft pack** (deserialize `draft_pack_json`, stamp `locked_at`, write to `locked_pack_json`) rather
than re-derive it. This is a prerequisite for the doc package meaning anything at lock time — a
locked pack currently loses exactly the content (real business rules, human notes) that would matter
most as a permanent record.

---

## 6. Explicitly out of scope: `04-evidencia`

The reference's `04-evidencia/` (17 `ejecucion`-verified rules, 23/23 test suite, equivalence
report) is grounded in actually compiling and running the COBOL (`cobc -x ...`,
`ejecutar-pruebas-legacy.sh`) against controlled inputs. Exploration, as built, never invokes
GnuCOBOL or executes anything — it only parses text. Every claim Exploration can produce is
`metodo_verificacion = lectura_codigo`, never `ejecucion`. Emitting an "evidencia" section from
Exploration would fabricate verification that never happened. If this capability is wanted later, it
is a distinct phase (a real GnuCOBOL harness, closer to `parity-validation`/`bugfix-loop`'s territory
than Exploration's), not something to bolt onto this subsystem now. Same reasoning applies more
softly to `03-to-be`: render it as the reference does — a declared-assumptions table gated on open
questions (§3) — never as an asserted architecture, since Exploration cannot know which assumptions
the bank/user will actually confirm.

---

## 7. Phased implementation, cheapest/most valuable first

| Phase | Work | Cost | New LLM calls | Depends on |
|---|---|---|---|---|
| P0 | Line numbers in `parse_structural` (§2.0) | Cheap — pure regex/offset math | None | — |
| P1 | Traceability registry builder + adapted validator (§4) | Cheap — mechanical assembly + ported script | None | P0 |
| P2 | Deterministic doc data: program inventory, data dictionary, integration/batch checks, Mermaid diagrams, risk registry (§2.1–2.5) | Cheap — mostly surfacing data already computed and discarded | None | P0 |
| P3 | Pack schema v2 (additive keys) + `.md` tree renderer + README index (§5) | Medium — new module, but pure functions of pack data | None | P1, P2 |
| P4 | LLM-authored sections: enriched business rules, use cases, glossary, blocking open questions, risk narrative (§3, Strands) | Medium — extends `_agentic_business_rules`'s proven call/parse/cost-log pattern | Yes, Strands, small JSON payloads | P2 (needs registry-ready anchors) |
| P5 | LLM-authored to-be prose: target architecture, COBOL→C# mapping, OpenAPI spec (§3, headless `claude -p`) | Higher — multi-file prose generation, longer subprocess runs | Yes, `claude -p`, mirrors `write_mvp_docs` | P4 (should cite the same rule/question IDs P4 produced), gated on open questions per §6 |
| — | `04-evidencia` (compile + run COBOL, equivalence testing) | — | — | **Out of scope for Exploration** (§6) |
| — (bugfix) | Fix `exploration_lock` to promote the draft pack instead of re-deriving it | Cheap, but must land before P3's renderer is trusted at lock time | None | — |

P0–P2 need zero new agent calls and mostly expose data structures that already exist transiently
inside current loops — they are the highest ratio of value to risk and should land first regardless
of how the LLM sections are sequenced afterward.
