---
name: migration-doc-generation
description: Cross-cutting skill — generates an ontological markdown graph for the migrated C# solution. T-box (SCHEMA.md), A-box (GRAPH.md), instance READMEs next to code, provenance MDs per COBOL program. Root README.md is for humans. Agents start at GRAPH.md and open one node. English, dense, factual.
---

# Migration Doc Generation

Purpose: documentation is a **typed knowledge graph in markdown**, not a pile of READMEs. A human runs the system from the root README. A coding agent queries `docs/ontology/GRAPH.md` (A-box), then opens **one** node path.

Callers: `backend/llm.py` `generate_documentation` / `_DOC_PROMPT_TEMPLATE`; `backend/routers/pipeline.py` `_run_doc_generation`. No HTTP API or SQLite schema. User asked for an advanced structured ontological MD system.

## Two audiences (never mix)

| File | Audience | Job |
|---|---|---|
| `README.md` (solution root) | Human | Build/run. Points at GRAPH.md for agents. No types, no edges. |
| `docs/ontology/SCHEMA.md` | Agents | **T-box** — classes, relations, constraints. |
| `docs/ontology/GRAPH.md` | Agents | **A-box — agent entry.** Nodes + edges tables only. |
| `docs/ontology/CONTEXT.md` | Both | Bounded context of the migrated system. |
| `docs/ontology/provenance/{Name}.md` | Agents | COBOL origin of one UseCase (`cob.{Name}`). |
| `docs/ontology/invariants/` | Agents | Must-not-break rules (`inv.*`) with `governs` edges. |
| Instance `README.md` next to code | Agents | Leaf body for `mod.*` / `uc.*`. GRAPH links here. |
| `docs/DOCUMENTATION.md` | Both | Derived reading map from GRAPH. Not the ontology. |

## Ontology (T-box)

Classes and stable ids:

| type | id pattern | Instance lives |
|---|---|---|
| Schema | `schema` | `docs/ontology/SCHEMA.md` |
| Graph | `graph` | `docs/ontology/GRAPH.md` |
| Context | `ctx` | `docs/ontology/CONTEXT.md` |
| Module | `mod.domain` `mod.application` `mod.infrastructure` `mod.cli` | `{Sln}.{Layer}/README.md` |
| UseCase | `uc.{Name}` | `UseCases/{Name}/README.md` |
| Entity | `ent.{Name}` | `Domain/Entities/` or ValueObjects README |
| Provenance | `cob.{Name}` | `docs/ontology/provenance/{Name}.md` |
| Invariant | `inv.{slug}` | `docs/ontology/invariants/` |
| Deviation | `adr.{slug}` | `docs/CONVERSION-NOTES.md` |

Relations (edges, not prose):

| rel | domain → range | Meaning |
|---|---|---|
| `part_of` | UseCase/Module → Module/Context | Containment |
| `implements` | UseCase → Provenance | COBOL program this handler is |
| `depends_on` | UseCase → UseCase | CALL graph |
| `governs` | Invariant → UseCase | Must-not-break |
| `traced_from` | Entity → Provenance | PIC / copybook origin |

Constraints:

- Every `uc.*` on disk has exactly one `implements cob.*`.
- `depends_on` follows the Phase 3 CALL graph; never invent edges.
- GRAPH.md lists every instance README that exists. Missing node = failed generation.
- GRAPH.md contains **no** handler logic, PIC tables, or test matrices.

## GRAPH.md shape (A-box)

```markdown
---
id: graph
type: Graph
audience: agent
---
# Graph

How to use: pick **one** node id. Open its path. Do not ingest sibling MDs.

## Nodes
| id | type | label | path | implements |
| uc.Data | UseCase | Data | {Sln}.Application/UseCases/Data/README.md | cob.Data |

## Edges
| from | rel | to |
| uc.Data | part_of | mod.application |
| uc.Data | implements | cob.Data |
| uc.Operations | depends_on | uc.Data |
```

## Instance frontmatter

Every generated MD except root README:

```yaml
---
id: uc.Data
type: UseCase
label: Data
audience: agent
part_of: [mod.application]
implements: [cob.Data]
depends_on: []
invariants: [inv.ws-lifetime]
cobol_origin: data.cob
graph: docs/ontology/GRAPH.md
read_when: ["changing STORAGE-BALANCE CALL lifetime"]
do_not_read_for: ["CLI menu loop"]
---
```

## Layout

```
README.md
docs/ontology/SCHEMA.md
docs/ontology/GRAPH.md          # agent start
docs/ontology/CONTEXT.md
docs/ontology/provenance/{Name}.md
docs/ontology/invariants/README.md
docs/DOCUMENTATION.md           # derived map
docs/ARCHITECTURE.md
docs/ONBOARDING.md
docs/CONVERSION-NOTES.md
docs/source/                    # carried COBOL-era markdown
{Sln}.Domain/README.md          # live conversion has no src/ prefix
{Sln}.Application/UseCases/{Name}/README.md
```

Phase 4 writes each `uc.*` README next to the handler. Doc-generation assembles SCHEMA + GRAPH + provenance + layer READMEs after all handlers exist. Do not overwrite UseCases/*/README.md.

## Exit criteria

- An agent given only GRAPH.md can name the path of any UseCase README.
- SCHEMA.md defines every type and relation used in GRAPH.md.
- Root README contains no ontological tables.
- GRAPH.md contains no module bodies.

## Style

English, dense, factual, no hedging. Failures stated plainly.

## Output

Markdown in the target C# tree, plus a copy under `runs/<id>/09-doc-generation/`.
