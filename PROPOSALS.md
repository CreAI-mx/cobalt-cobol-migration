# Propuestas (backend) — para reenviar al agente de frontend / al usuario

Convención: aquí deposito sugerencias de cambio que NO están en mi scope directo
(frontend, o decisiones que el usuario quiere revisar antes). El usuario las
reenvía cuando corresponde. No implemento nada de esta lista sin que me lo pidan.

## Pendientes

- **Diagrama de arquitectura inline en "Migration Modules".** Usuario pidió
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
- **Superficie para `exploration_sessions.draft_pack_json` en la UI.**
  Ya existe `GET /migration/{run_id}/exploration/pack`, `POST .../lock`,
  `POST .../modules/{id}/notes` — pero no vi vista dedicada. Sería el paso
  de "revisión humana" antes de Planning (igual al gate de arquitectura que
  ya existe).
