# Propuestas (backend)

## Estado (2026-09-16)

| Ítem | Estado | Notas |
|------|--------|--------|
| Diagrama CALL inline (Migration Modules) | **Hecho (Step 2)** | Hero `RepositoryLandscape` = CALL pack + zoom/pan/hover; color por kind no por file |
| Superficie draft pack / revisión humana (Step 2) | **Hecho** | Command bar, módulos, notas, Lock; solo pantalla 2 |
| Business rules en tarjetas | **Hecho** | `BusinessRuleCards.tsx` — usuario pide **menos protagonismo** (colapsar por default) |
| risk_tier + wave en UI del plan | **Pendiente** | Backend listo; Step 5 / `WorkItemBoard` sin badges |
| Strands SDK en exploración | **Pendiente** | Decisión de producto; ESS actual con asyncio |
| Phase 2 agentica (reglas reales) | **Pendiente** | Stubs `deterministic_draft` en pack |
| Dedup reglas BR-CALL duplicadas | **Hecho** | `dedupe_business_rules` al cerrar el módulo |

**Siguiente diseño acordado (solo Step 2):** grafo interactivo como elemento principal; business rules en acordeón cerrado por default. **Aplicado 2026-09-16:** CALL graph hero + rules accordion + pipeline humano (Understanding / Review) con “Show detail”.

 — para reenviar al agente de frontend / al usuario

Convención: aquí deposito sugerencias de cambio que NO están en mi scope directo
(frontend, o decisiones que el usuario quiere revisar antes). El usuario las
reenvía cuando corresponde. No implemento nada de esta lista sin que me lo pidan.

## Pendientes

- **Reducir el pipeline a 5 fases visibles para el humano (colapsar, no eliminar).**
  Usuario, verbatim: "esperaría algo más reducido, algo intuitivo humanamente" — 15
  eventos de fase para un repo de 3 archivos es ceremonia desproporcionada. Propuesta:
  1. **Entendiendo tu código** = Discovery + Structural + Dependency + Modules +
     Business logic + Graph + Documentation (exploration_orchestrator.py)
  2. **Revisión** = Human Lock (`POST /exploration/lock`) — único punto de acción humana
  3. **Planificando** = Environment Setup + Analyzing (orchestrator.py)
  4. **Construyendo y verificando** = Generating + Build + Test + Parity + todo el
     ciclo Repairing (mostrar como "en progreso · N reintentos", no cada gate)
  5. **Listo** = Documenting + PASSED/FAILED
  Los 15 eventos internos siguen corriendo y persistiendo igual (auditoría/debug
  intactos) — esto es agrupación en la UI (`PhaseTimeline`/similar), no cambio de
  arquitectura backend. Requiere un mapeo `phase_real -> fase_visible` del lado
  frontend, con un toggle "ver detalle" para quien quiera las 15 fases reales.

- ~~**Diagrama de arquitectura inline en "Migration Modules".**~~ **Parcial** — ver `ModuleCallGraph.tsx`. Usuario pidió
  verlo directo en esa pantalla, no en un link externo. Datos reales YA
  disponibles vía `GET /migration/{run_id}/exploration/pack` →
  `call_graph_resolved.edges` + `modules[].member_paths`. Renderizar con
  Mermaid (`flowchart`) client-side por módulo, mismo shape que
  `docs/ARCHITECTURE.md` en el repo (sección "Grafo CALL real"). No requiere
  nuevo endpoint — el pack ya trae los edges.

  Diagrama real para el módulo `mod-001` de este run (generar client-side con
  `mod.member_paths` + `pack.call_graph_resolved.edges`, no hardcodeado):

  ```mermaid
  flowchart LR
      MAIN["MainProgram<br/>main.cob"]
      OPS["OperationsProgram<br/>operations.cob"]
      DATA["DataProgram<br/>data.cob"]
      MAIN -->|CALL| OPS
      OPS -->|CALL| DATA
  ```

  Mapeo directo del pack: `call_graph_resolved.edges` → cada `{from_path,
  to_path, target_program_id}` es una flecha; `modules[].member_paths` decide
  qué nodos van en qué subgrafo cuando hay más de un módulo.

- **Evaluar Strands SDK para el subsistema de Exploración.** `exploration_orchestrator.py`
  ya corre un pipeline determinista (discovery → structural → dependency →
  module-synthesis → business-rules) a mano con `asyncio.gather`. Se podría
  portar a un `strands.multiagent.Graph` (DAG determinista, mismo orden) o
  `Swarm` si se quiere handoff dinámico entre pasos. Ventaja: orquestación
  declarativa, tools reusables (`@tool` sobre `exploration_core.parse_structural`
  etc). Requiere `pip install strands-agents` + credenciales (Bedrock o
  Anthropic directo — ya hay `ANTHROPIC_API_KEY` en `.env`). NO implementado
  aún — es un cambio de framework sobre un subsistema que ya funciona, decisión
  del usuario si vale la pena el swap.

- **Mostrar risk_tier + wave en la UI del plan.** Backend ya calcula `wave`
  ordenado por riesgo cuando hay un exploration pack bloqueado
  (`planner.py::_module_risk_tier`, `_exploration_prompt_section`). El plan
  (`GET /migration/{run_id}/plan`) ya trae `work_items[].wave`. Sería útil
  que la vista del plan agrupe visualmente por wave (badge LOW/HIGH) en vez
  de listar todos los work items sin indicar orden de riesgo.
- ~~**Superficie para `exploration_sessions.draft_pack_json` en la UI.**~~ **Hecho** (Step 2 ESS). Referencia histórica:
  Ya existe `GET /migration/{run_id}/exploration/pack`, `POST .../lock`,
  `POST .../modules/{id}/notes` — pero no vi vista dedicada. Sería el paso
  de "revisión humana" antes de Planning (igual al gate de arquitectura que
  ya existe).


## Diseño Step 2 (aplicado en frontend)

### Migration modules — dossier

1. **CALL architecture** — subgrafo por `modules[].member_paths` + `call_graph_resolved.edges`
   (componente `ModuleCallGraph.tsx`). Equivalente visual al Mermaid de arriba, sin dependencia
   Mermaid en bundle.

2. **Business rules** — ya no lista plana `ul.rule-list`. Tarjetas (`BusinessRuleCards.tsx`):
   - Agrupadas por archivo COBOL (`main.cob`, `data.cob`, …).
   - Título corto: `Paragraph · MAIN-LOGIC` o `External call · DATAPROG`.
   - Badge **Draft** (ámbar) / Agent (violeta) / Confirmed (verde).
   - Texto largo del stub solo en hint secundario; CTA ancla abre **FilePeek** en origen.
   - Scroll acotado en dossier (`max-height` ~60vh) + “Show all N rules”.

3. **Revisión humana** — notas por módulo sin cambio (`POST .../notes`); Lock pack alimenta planner.

### Feedback del usuario sobre el diseño de arriba (2026-09-16)

- **Menos protagonismo a Business Rules.** El usuario vio las tarjetas y las
  encontró demasiado dominantes visualmente (mucho texto repetido — recordar
  el bug real de duplicados en `BR-CALL-OperationsProgram` x3, ya reportado
  arriba). El grafo CALL debe ser el elemento visual principal de la pantalla
  de Exploración, business rules secundario/colapsado por default.
- **Solo pantalla 2 (Exploración) por ahora** — no expandir a otras pantallas
  todavía.
- **Grafo embebido, no solo Mermaid-equivalente** — usuario pidió algo "como
  plotly", es decir interactivo (zoom/pan/hover), no un diagrama estático.
  Si `ModuleCallGraph.tsx` ya es interactivo (SVG/D3/react-flow), esto ya
  está cubierto — si es estático, considerar upgrade.

### Pendiente backend (mejora copy, no UI)

- Sustituir stubs `draft_business_rules` por salida agentica Phase 2 (`source: agent`) con reglas
  en inglés denso ancladas a párrafo — las tarjetas ya distinguen Draft vs Agent.
