# Arquitectura real — run `01M2NTWGMWX1ERNRQ9AMT8BG2M`

Datos reales extraídos por el subsistema de Exploración (determinista, sin LLM) contra `cobol-accounting-system`. Sin base de datos ni archivos: `DataProgram` guarda el balance en `WORKING-STORAGE` (memoria del proceso), no hay `SELECT`/`FD`/`EXEC SQL` en ninguno de los 3 programas.

## 1. Grafo CALL real (COBOL original)

```mermaid
flowchart LR
    MAIN["MainProgram<br/>main.cob<br/>menu: View/Credit/Debit/Exit"]
    OPS["OperationsProgram<br/>operations.cob<br/>TOTAL/CREDIT/DEBIT"]
    DATA["DataProgram<br/>data.cob<br/>READ/WRITE balance"]

    MAIN -->|"CALL 'OperationsProgram'<br/>USING TOTAL/CREDIT/DEBIT"| OPS
    OPS -->|"CALL 'DataProgram'<br/>USING READ/WRITE"| DATA

    MEM[("WORKING-STORAGE<br/>(memoria del proceso)<br/>NO hay archivo/BD")]
    DATA -.balance vive aqui.-> MEM

    style MEM fill:#fbf3e4,stroke:#c8932e,color:#1c2321
    style MAIN fill:#e4efe9,stroke:#1f6f5c,color:#1c2321
    style OPS fill:#e4efe9,stroke:#1f6f5c,color:#1c2321
    style DATA fill:#e4efe9,stroke:#1f6f5c,color:#1c2321
```

**Orden topológico real** (calculado por `exploration_core.build_graph_edges`): `main.cob → operations.cob → data.cob`.

## 2. Clustering en módulo de migración

Los 3 programas están conectados por CALL, así que el subsistema de Exploración los agrupa en UN solo módulo (union-find sobre el grafo — `work_items.connected_cobol_groups`):

```mermaid
flowchart TB
    subgraph MOD["mod-001: Dataprogram + Mainprogram + Operationsprogram — wave 0"]
        direction LR
        MAIN2["MainProgram"] --> OPS2["OperationsProgram"] --> DATA2["DataProgram"]
    end
    MOD --> TARGET["src/Application/UseCases/<br/>{Dataprogram,Mainprogram,Operationsprogram}/"]

    style MOD fill:#e4efe9,stroke:#1f6f5c,color:#1c2321
    style TARGET fill:#fbf3e4,stroke:#c8932e,color:#1c2321
```

11 business rules draft generadas (3 CALL sites × repetición por rama de menú + 2 GOBACK) — determinista, sin LLM todavía.

## 3. Capa agéntica — Multi-Agent Graph con Strands (experimento verificado hoy)

```mermaid
flowchart TB
    subgraph DETERMINISTIC["Capa determinista (exploration_core.py) — YA CORRE, sin costo LLM"]
        PARSE["parse_structural()<br/>regex: divisions, PIC, paragraphs"]
        GRAPH["build_graph_edges()<br/>CALL/COPY edges"]
        CLUSTER["connected_cobol_groups()<br/>union-find"]
    end

    subgraph STRANDS_GRAPH["strands.multiagent.Graph — propuesto, mismo orden real de hoy"]
        direction LR
        N1["Nodo: Discovery<br/>tool sobre inventory_source()"]
        N2["Nodo: Structural<br/>tool sobre parse_structural()"]
        N3["Nodo: Dependency<br/>tool sobre build_graph_edges()"]
        N4["Nodo: Business Rules<br/>agente real (LLM)"]
        N1 --> N2 --> N3 --> N4
    end

    subgraph VERIFIED["Verificado HOY, 1 llamada real"]
        TOOL["@tool parse_cobol_structure"]
        AGENT["strands.Agent<br/>model=claude-sonnet-4-5<br/>via ANTHROPIC_API_KEY"]
        TOOL --> AGENT
        AGENT --> COST["input=1661 output=272<br/>cost=$0.009063"]
    end

    PARSE -.expuesta como tool a.-> N2
    GRAPH -.expuesta como tool a.-> N3
    N2 -.mismo patron probado en.-> VERIFIED

    style DETERMINISTIC fill:#e4efe9,stroke:#1f6f5c,color:#1c2321
    style STRANDS_GRAPH fill:#f6e9df,stroke:#b3541e,color:#1c2321
    style VERIFIED fill:#fbf3e4,stroke:#c8932e,color:#1c2321
```

**Siguiente iteración** (no ejecutada, pendiente tu confirmación por costo): construir el `Graph` de 4 nodos completo con `GraphBuilder` de Strands, mismo orden que `exploration_orchestrator.py` ya corre hoy en `asyncio.gather` manual, pero con orquestación declarativa.

## Resumen de infraestructura de este run

| Componente | Real hoy |
|---|---|
| Base de datos | **Ninguna** — balance en memoria, sin `SELECT`/`FD`/`EXEC SQL` |
| Persistencia | Ninguna en el COBOL original; el C# migrado sí necesitará decidir dónde persistir (gap a resolver en Architecture Proposal) |
| Grafo CALL | 2 edges reales, 3 programas, 1 módulo de migración |
| Capa agéntica activa | Exploración = determinista (gratis); Planning = 1 llamada LLM (`llm.plan_manifest`); Generating = 1 agente headless por work item |
| Strands | Instalado y verificado con 1 llamada real ($0.009), Graph completo no wireado a producción todavía |
