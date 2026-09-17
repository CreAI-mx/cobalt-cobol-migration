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

- **`POST /migration/{run_id}/parity-demo` ignora el parámetro `program`.**
  Confirmado real por agente de verificación: `parity_demo.py::_detect_fixture()`
  está hardcodeado a `"account_lookup"` siempre que ese archivo exista en la
  fuente — no importa qué `program` se pida en el body. Esto es una
  limitación PRE-EXISTENTE ya documentada en `parity_gate.py` (docstring:
  "parity_demo.py is a manual Step-5 UI button hardcoded to one program
  shape... [parity_gate.py] is the real gate"), no una regresión de hoy. El
  gate real y automático (`parity_gate.py`, corre dentro de la migración)
  SÍ soporta múltiples programas — verificado hoy con un run PASSED 3/3.
  Si se quiere que el sandbox manual de la UI soporte elegir programa,
  requiere generalizar `_detect_fixture`/`_run_cobol_oracle`/`_run_csharp_side`
  para aceptar el parámetro `program` real y despachar el fixture correcto
  por programa (reusar `cobol_io_profile.derive_fixture` en vez de la lógica
  ad-hoc de account_lookup que tiene hoy).

- **`/migration/runs` (listado) debe mostrar también fase/% de Exploración, no
  solo status de Migración.** Confusión real de usuario: la lista solo trae
  `migration_runs.status` (PASSED/FAILED/ABORTED/RUNNING) — un run cuya
  Migración nunca arrancó pero cuya Exploración sigue viva en background se ve
  igual que uno completamente muerto ("ABORTED"), sin ninguna señal de que
  Exploración sigue trabajando. Fix: el listado debe hacer join con
  `exploration_sessions` (o el endpoint agregar el campo) y mostrar algo como
  "Exploration: RUNNING (fase X, Y%)" cuando `exploration_sessions.status`
  no sea terminal, incluso si `migration_runs.status = ABORTED`. Dato ya
  disponible vía `GET /migration/{run_id}/exploration/status` (`live`,
  `status`) — solo falta agregarlo a la vista de listado.

- **Bug real de UX encontrado por E2E con navegador (Playwright, clicks reales):**
  el botón "Lock" en Step 2 puede fallar con 409 (exploración aún no realmente
  terminada) SIN mostrar error visible al usuario — la UI deja avanzar
  Architecture → Manifest → aprobar → Step 5 → "Migrar" de todas formas. El
  usuario solo se entera del fallo real hasta el final (4 pantallas después),
  cuando el backend rechaza `/start` con 409 (gate real, ya implementado y
  funcionando en backend). Fix: si el click a "Lock" devuelve error, mostrarlo
  inmediatamente y bloquear el avance a Architecture/Manifest hasta que
  Exploration esté realmente `LOCKED`.
- **Botón "Migrar" en español** rompe consistencia con el resto de la UI (en
  inglés) — debería decir "Migrate" o "Start Migration".
- Varios `404 Not Found` en consola durante el recorrido completo (no bloquean
  el flujo pero ensucian la consola) — recursos no encontrados, no identificados
  a detalle por el agente E2E.

- **"Pseudocode flow" volvió a horizontal — debe ser vertical.** Usuario:
  "debe ser siempre en vertical, me hiciste algo muy feo todo en horizontal,
  ya estaba bien esto". Regla ya guardada como standing reminder global.
  Revisar el componente que renderiza el flowchart de pseudocódigo (grafo de
  nodos start/end/process/decision/loop) y forzar orientación vertical
  (top-to-bottom) siempre, sin importar cantidad de nodos.

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
