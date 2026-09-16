# Guía de documentación para migraciones COBOL → C#

**Qué es.** El catálogo completo de documentación a producir en un proyecto de migración COBOL → C#,
dividido en **antes de migrar** (AS-IS, COBOL) y **después de migrar** (TO-BE, C#), con la evidencia
que une ambos lados.

**Para qué sirve.** Cada entregable está vinculado a una fila del RFI respondido. La documentación no
es un anexo del proyecto: **es la evidencia de que lo respondido en el RFI se cumple sobre el código
real del banco.**

**Cómo usarla.** Como lista de verificación por aplicación migrada. Un entregable no está cerrado
hasta cumplir su criterio de cierre, y una ola de migración no avanza con entregables bloqueantes
abiertos.

---

## 1. Principio rector: la trazabilidad es la columna vertebral

Todo el paquete se sostiene sobre un único artefacto: un **registro de trazabilidad** donde cada
elemento —programa, campo, regla de negocio, riesgo, pregunta abierta— tiene un identificador estable,
un apuntador a su origen en el código legacy y un apuntador a su destino en el código modernizado.

```
código COBOL ──► regla extraída ──► decisión validada ──► código C# ──► prueba que la verifica
       └──────────── mismo identificador BR-* en los cinco pasos ────────────┘
```

Los demás documentos **citan identificadores**; no repiten contenido. Esto es lo que permite responder
de forma auditable a las tres preguntas que el banco hará sobre cualquier regla:

1. *¿De dónde salió?* → archivo y líneas del legacy.
2. *¿Cómo sé que es cierta?* → método de verificación (lectura de código vs. ejecución).
3. *¿Dónde quedó implementada?* → clase, método y prueba en C#.

**Sin este registro, el resto del paquete es prosa no auditable.** Es el primer entregable, no el último.

---

## 2. Fase 0 — Requisitos previos (gate de entrada)

No se inicia el análisis sin esto. Cada punto que falte es un riesgo que se materializará después.

| # | Requisito | Por qué bloquea |
|---|---|---|
| 0.1 | **Código fuente COBOL completo** del alcance, incluidos copybooks, CL/JCL y definiciones de archivo | Sin el fuente no hay AS-IS, y sin AS-IS no hay equivalencia demostrable |
| 0.2 | **Compilador disponible** para ejecutar el legacy | La verificación por ejecución distingue documentación demostrada de documentación afirmada |
| 0.3 | **Juegos de datos representativos** o capacidad de construirlos | Son la base de la comparación en paralelo |
| 0.4 | **Analista funcional del banco** asignado (4–6 h/semana) | Las reglas las valida el banco; el proveedor las documenta |
| 0.5 | **Responsable técnico de la plataforma legacy** | Resuelve accesos y dudas del entorno |
| 0.6 | **Alcance funcional acordado por escrito** | Define qué se compara y qué queda fuera |

> ⚠️ **El error más caro observado:** recibir el código C# ya generado **sin el COBOL de origen**.
> La documentación de migración cita el legacy en cada decisión ("líneas 51-54", "REWRITE línea 56");
> si el fuente no está disponible, ninguna de esas afirmaciones es verificable y toda la evidencia de
> equivalencia queda sin sustento. Ver anexo, caso 2.

---

## 3. Bloque A — Documentación PRE-migración (AS-IS, COBOL)

Responde a **qué hace el sistema hoy**. Es la base contra la que se mide todo lo demás.

| ID | Entregable | Audiencia | RFI | Prioridad |
|---|---|---|---|---|
| A1 | Registro de trazabilidad | Todos · auditoría | C32, C33, C44, C62 | 🔴 Bloqueante |
| A2 | Catálogo de reglas de negocio | Negocio | C27–C33, C47 | 🔴 Bloqueante |
| A3 | Procesos y casos de uso | Negocio | C47, C48, C49 | 🟠 Alta |
| A4 | Glosario de negocio | Negocio | C51 | 🟠 Alta |
| A5 | Preguntas abiertas y comportamiento no explicado | Negocio · dirección | — | 🔴 Bloqueante |
| A6 | Inventario y catálogo de programas | Técnica | C21, C22, C25, C36, C37 | 🟠 Alta |
| A7 | Diccionario de datos y definiciones de archivo/tabla | Técnica | C38, C40 | 🔴 Bloqueante |
| A8 | Mapa de dependencias y análisis de impacto | Técnica | C20, C24, C39 | 🟠 Alta |
| A9 | Inventario de integraciones e interfaces | Técnica · arquitectura | C41, C42, C64–C68 | 🟠 Alta |
| A10 | Catálogo de procesos batch | Técnica · operación | C43 | 🟡 Media |
| A11 | Diagramas AS-IS | Todos | C52–C63 | 🟠 Alta |
| A12 | Evaluación de complejidad, riesgo y roadmap | Dirección | C77–C87 | 🟠 Alta |

### A1 · Registro de trazabilidad
Un archivo estructurado (CSV/JSON) con: `id`, `tipo`, `nombre`, `archivo_fuente`, `linea_inicio`,
`linea_fin`, `metodo_verificacion`, `artefacto_to_be`, `estado_validacion`, `validado_por`, `fecha`.
Prefijos sugeridos: `PGM-`, `DAT-`, `UC-`, `BR-<dominio>-`, `RSK-`, `QA-`, `TC-`. Identificadores
**inmutables**: una regla derogada se marca, nunca se renumera ni se reutiliza el número.
**Cierre:** un validador automático confirma que no hay IDs duplicados, que todo archivo citado existe,
que todo rango de líneas es válido y que todo ID referenciado en la documentación está declarado.

### A2 · Catálogo de reglas de negocio
Una ficha por regla: enunciado en lenguaje natural, origen exacto en el código, método de verificación,
riesgo asociado y **casilla de validación firmada por el analista funcional del banco**.
Distinguir explícitamente las reglas deliberadas de los **comportamientos accidentales** —los que
resultan de un tipo de dato sin signo, de una validación ausente o de aritmética sin control de
desbordamiento. Marcarlos: son los que no deben reproducirse a ciegas.
**Cierre:** 100 % de reglas con firma del banco. Una regla sin validar no genera código.

### A3 · Procesos y casos de uso
Actores, eventos de negocio, flujo principal, flujos alternos y **casos límite con su comportamiento
real observado**. Incluir una matriz caso de uso × regla.
**Cierre:** todo caso de uso tiene al menos un caso de prueba ejecutado (ver D1).

### A4 · Glosario de negocio
Término funcional → campo en el código → cláusula `PIC` → **restricción real que impone el tipo**.
Sección obligatoria: *términos técnicos que aparentan ser de negocio* (un programa llamado
`DataProgram` que no persiste nada; operaciones `READ`/`WRITE` que sólo mueven variables en memoria).
Sección obligatoria: *conceptos ausentes* (divisa, folio, usuario, fecha valor) — su ausencia es un
hallazgo, y si el sistema objetivo los requiere, son **funcionalidad nueva**, no migración.

### A5 · Preguntas abiertas y comportamiento no explicado
Lo que el análisis **no puede resolver desde el código**. Cada pregunta con: contexto, por qué bloquea,
opciones, hipótesis del equipo (marcada como hipótesis) y espacio para la respuesta del banco.
Declarar lo que no se sabe es parte del entregable.
**Cierre:** cero preguntas bloqueantes abiertas antes de generar código del componente afectado.

### A6 · Inventario y catálogo de programas
Inventario de artefactos presentes **y ausentes** (copybooks, `FILE SECTION`, SQL embebido, CL/JCL,
pantallas). Por programa: responsabilidad, parámetros, invoca a / invocado por, puntos de decisión,
hallazgos técnicos. Sección de **código muerto y componentes sin uso** con su evidencia.

### A7 · Diccionario de datos
Cada campo con `PIC`, rango real, signo, escala y programas que lo leen o escriben. Matriz CRUD.
Tabla de semántica de tipos con su equivalente en C#.
**Punto crítico:** documentar si existe persistencia real. Un saldo en `WORKING-STORAGE` no persiste,
aunque el programa que lo aloja se llame `DataProgram`.

### A8 · Mapa de dependencias
Grafo de llamadas con cada relación clasificada como **explícita** (derivada del código) o **inferida**
(resuelta por interpretación, con su evidencia declarada). Nunca mezclarlas en silencio.
Incluir análisis de impacto por componente: qué se rompe si se modifica cada uno. De ahí sale el
**orden de migración**: de las hojas del grafo hacia la raíz.

### A9 · Inventario de integraciones
Verificación **por tipo** (archivos, SQL, MQ, FTP, REST, SOAP, data areas, spool, pantallas), con el
resultado de cada búsqueda. Un resultado vacío es un hallazgo válido y debe poder contrastarse.
**Regla de alcance:** las conclusiones aplican al código analizado; no se extrapolan a programas fuera
del alcance.

### A10 · Catálogo de procesos batch
Jobs, calendario, dependencias, puntos de reinicio y recuperación, ventanas operativas.
Si no hay batch, documentarlo: condiciona el calendario de corte de la migración.

### A11 · Diagramas AS-IS
Arquitectura, call graph, flujo de control por programa, secuencia, flujo de datos y BPMN.
En formato de texto versionable (Mermaid, PlantUML) para que se regeneren con el código, no en
imágenes sueltas. **Cada elemento cita su origen en el código.**

### A12 · Evaluación de complejidad y riesgo
Factores: LOC, dependencias, integraciones, complejidad funcional, riesgos técnicos. Clasificación
Baja/Media/Alta, matriz probabilidad × impacto, quick wins, roadmap por olas.
**Separar complejidad técnica de incertidumbre funcional**: son ejes distintos y suelen ir en sentido
contrario. Convertir el código puede ser trivial mientras decidir qué debe hacer el código convertido
no lo es.

---

## 4. Bloque B — Artefactos de transición

El puente entre los dos mundos. **Es donde se previenen los defectos de migración**, y donde el banco
autoriza que el sistema nuevo se comporte distinto del viejo.

| ID | Entregable | Audiencia | RFI | Prioridad |
|---|---|---|---|---|
| B1 | Arquitectura objetivo (TO-BE) con supuestos declarados | Arquitectura | C88–C95 | 🔴 Bloqueante |
| B2 | Documento de mapeo COBOL → C# | Desarrollo | C96–C105 | 🔴 Bloqueante |
| B3 | **Registro de divergencias firmado** | Negocio · auditoría | C106 | 🔴 Bloqueante |
| B4 | Especificación de API (OpenAPI), **si aplica** | Arquitectura · consumidores | C93 | 🟡 Condicional |

### B1 · Arquitectura objetivo
Dominios de negocio identificados, bounded contexts, modelo de dominio con sus invariantes, estructura
de solución y decisiones técnicas justificadas.
**Obligatorio: una tabla de supuestos declarados**, cada uno vinculado a la pregunta abierta de la que
depende y con la consecuencia de que cambie. Un supuesto no declarado es un defecto latente.
**Recomendación de altura:** no fragmentar en microservicios un sistema que no lo justifica. La
complejidad distribuida se paga en operación, no en migración.

### B2 · Mapeo COBOL → C#
El documento de mayor densidad técnica del paquete. Mínimo obligatorio:

- **Tipos.** Todo importe monetario es `decimal`, nunca `double` ni `float`. `PIC S9(n)V99` es decimal
  de precisión fija; un tipo binario introduce error de representación en un saldo contable.
- **Desbordamiento.** COBOL sin `ON SIZE ERROR` **trunca los dígitos de orden alto en silencio**;
  .NET lanza excepción o no desborda. Son comportamientos opuestos: la diferencia debe ser deliberada.
- **Signo.** `PIC 9(n)` sin `S` es **sin signo**: descarta el signo de una captura negativa. C# lo
  conserva e invertiría la operación. Ambos son defectos, distintos entre sí.
- **Redondeo.** Sin `ROUNDED`, COBOL trunca. `Math.Round` de .NET usa redondeo bancario por defecto.
  Usar truncamiento explícito para equivalencia.
- **Paso de parámetros.** COBOL usa `BY REFERENCE` por defecto; un parámetro de `LINKAGE`
  bidireccional no se traduce con `ref`/`out`, se separa en entrada y salida.
- **Estructuras de control.** Un `IF` sin `END-IF` extiende su alcance hasta el punto final: verificar
  el alcance real de cada rama antes de traducir, y desconfiar del retorno implícito de programa.
- **Comparaciones.** Verificar `>=` frente a `>`. Es el error de traducción más frecuente y sólo
  aparece en el caso límite.
- **Formato de presentación.** Conservar el formato exacto del legacy en el ejecutable de comparación,
  aunque el sistema productivo use otro.

**Cierre:** una lista de verificación de conversión que el revisor firma por componente.

### B3 · Registro de divergencias
**El entregable que el banco firma.** Toda diferencia deliberada entre legacy y modernizado, con:
identificador, caso de prueba afectado, comportamiento legacy, comportamiento nuevo, regla afectada,
motivo y **firma de aceptación**.

> Una diferencia acordada de antemano es una decisión de diseño. La misma diferencia descubierta
> después es un defecto. Un sistema modernizado que se comporta distinto sin aceptación formal es un
> hallazgo de auditoría, aunque el cambio sea una mejora.

Debe cubrir también los **defectos heredados que se preservan deliberadamente**: cuando el legacy
tiene un error y se decide reproducirlo por equivalencia estricta, esa decisión se documenta y se
firma igual que cualquier otra.

### B4 · Especificación de API
Sólo si el sistema objetivo expone una interfaz de servicio. Anotar cada operación con las reglas de
negocio que implementa y su origen en el legacy.
**No generar una especificación para una API que no existe.** Si el destino es un ejecutable de
consola o un proceso batch, este entregable no aplica y debe declararse como tal.

---

## 5. Bloque C — Documentación POST-migración (TO-BE, C#)

Se genera **con el mismo mecanismo** aplicado al AS-IS, no se redacta a mano, y se regenera en cada
ciclo de análisis.

| ID | Entregable | Audiencia | RFI | Prioridad |
|---|---|---|---|---|
| C1 | Catálogo de servicios y componentes | Técnica | C37, C108 | 🟠 Alta |
| C2 | Catálogo de reglas de negocio del sistema modernizado | Negocio · auditoría | C108 | 🔴 Bloqueante |
| C3 | Modelo de datos y contratos de persistencia | Técnica | C38, C40, C108 | 🔴 Bloqueante |
| C4 | Diagramas TO-BE | Todos | C52–C63, C108 | 🟠 Alta |
| C5 | Trazabilidad regla → clase → método → prueba | Auditoría | C106, C108 | 🔴 Bloqueante |
| C6 | Registro de riesgos técnicos del sistema nuevo | Técnica · dirección | C74 | 🟠 Alta |
| C7 | Documentación de configuración y parámetros | Operación · cumplimiento | — | 🟠 Alta |
| C8 | Runbook de operación | Operación | C35 | 🟡 Media |
| C9 | Documentación de seguridad y control de acceso | Seguridad · cumplimiento | C121, C122 | 🟠 Alta |

### C1 · Catálogo de servicios y componentes
Por componente: responsabilidad, firma pública, dependencias, componente legacy del que proviene.
**Verificar que la arquitectura documentada coincide con la real.** Una solución que anuncia capas
Domain / Application / Infrastructure pero cuyo proyecto Domain está vacío está mal documentada o mal
construida; en ambos casos la discrepancia se resuelve antes de entregar.

### C2 · Catálogo de reglas del sistema modernizado
El espejo de A2. Cada regla `BR-*` del AS-IS aparece aquí con su implementación real, **o** con una
justificación registrada de por qué no aplica.
**Una regla presente en A2 y ausente aquí es una regla perdida en la migración.** Detectarlo es el
propósito del documento.

### C3 · Modelo de datos y contratos de persistencia
Esquema del almacén, restricciones, índices y migraciones. Si la persistencia es por archivos planos
de ancho fijo, **el layout byte a byte es un contrato de interfaz** y debe entregarse con el código:
posición, longitud, tipo, escala y tratamiento del punto decimal implícito.
**Verificar que este documento existe físicamente en el entregable**, no sólo referenciado desde un
README.

### C4 · Diagramas TO-BE
Arquitectura de capas, dependencias entre proyectos, secuencia por caso de uso y modelo de dominio.
Mismo formato versionable que A11.

### C5 · Trazabilidad regla → implementación → prueba
Formato por regla:
```
BR-CTA-005 → Domain/Cuenta.cs:Cargar():42
             ↳ prueba: Domain.Tests/CuentaTests.cs:Cargar_ConSaldoExacto_Autoriza()
             ↳ origen legacy: operations.cob:32
```
**Cierre:** 100 % de reglas con implementación y prueba asignadas, o justificación registrada.

### C7 · Configuración y parámetros
Inventario de todo valor que gobierna una decisión de negocio, indicando **dónde vive**: configuración,
base de datos o constante compilada.

> ⚠️ **Punto de atención para banca.** Umbrales regulatorios (montos de reporte, listas de países de
> alto riesgo, límites operativos) implementados como constantes en el código obligan a recompilar y
> redesplegar para cambiar un parámetro regulatorio, y no dejan pista de auditoría del cambio.
> Si se heredan así del legacy, **documentarlo explícitamente** y escalarlo a cumplimiento: es una
> decisión de la institución, no del equipo de migración. Ver anexo, caso 2.

### C9 · Seguridad y control de acceso
Modelo de identidad, autorización, cifrado, registro de auditoría y retención.
Si el legacy no tenía ninguno —lo habitual—, **todo este bloque es funcionalidad nueva** y se
presupuesta como desarrollo, no como migración.

---

## 6. Bloque D — Evidencia de equivalencia

Une los dos lados. **Es lo que el banco firma para autorizar la salida a producción.**

| ID | Entregable | Audiencia | RFI | Prioridad |
|---|---|---|---|---|
| D1 | Suite de caracterización del legacy (línea base) | Técnica · QA | C107, C109 | 🔴 Bloqueante |
| D2 | Casos de prueba derivados de las reglas | QA · negocio | C107, C109, C111 | 🔴 Bloqueante |
| D3 | Reporte de ejecución en paralelo | Todos · auditoría | C106, C110 | 🔴 Bloqueante |
| D4 | Reporte de cobertura de reglas | Auditoría | C112 | 🔴 Bloqueante |

### D1 · Suite de caracterización del legacy
Automatizada y ejecutable, sobre el COBOL **compilado**. Registra el comportamiento real **incluidos
sus defectos**: es precisamente lo que permite demostrar después que su corrección fue deliberada y
autorizada, y no un error de conversión.
**Cierre:** la suite corre en un comando y todos sus casos pasan contra el legacy.

### D2 · Casos de prueba derivados de las reglas
Derivados del **catálogo de reglas del legacy**, no del código nuevo. Un caso escrito a partir del
código nuevo sólo demuestra que el código nuevo hace lo que hace.
Cobertura obligatoria de casos límite: el importe exacto, el importe un centavo por encima, cero,
negativo, no numérico, el máximo del campo y el máximo más uno.

### D3 · Reporte de ejecución en paralelo
Ambos sistemas reciben las mismas entradas; las salidas se comparan de forma automatizada. Requiere un
**ejecutable de comparación** en el lado modernizado que reproduzca la interfaz del legacy: sin él, la
equivalencia se afirma pero no se demuestra.
Clasificación de discrepancias por severidad. **Toda discrepancia que afecte un importe y no esté en
el registro de divergencias (B3) es crítica por definición**, con independencia de su magnitud.
Plantilla de reporte con veredicto y doble firma: responsable técnico y responsable funcional del banco.

### D4 · Reporte de cobertura de reglas
Matriz regla × extraída × validada × implementada × probada. Cierra el ciclo de trazabilidad y responde
a la única pregunta que importa: **¿alguna regla se perdió?**

---

## 7. Matriz de cobertura del RFI

| Compromiso del RFI | Fila | Entregables que lo evidencian |
|---|---|---|
| Inventario técnico y catálogo de programas | C36, C37 | A6, C1 |
| Diccionario de datos y definiciones de tablas | C38, C40 | A7, C3 |
| Dependencias | C20, C24, C39 | A8 |
| Interfaces y APIs | C41, C42, C64–C68 | A9, B4 |
| Catálogo de procesos batch | C43 | A10 |
| Documentación vinculada al código fuente | C44 | A1, C5 |
| Documentación regenerable | C45 | A1 + validador automático |
| Extracción y explicación de reglas de negocio | C27–C31 | A2 |
| Trazabilidad regla ↔ código | C32, C33 | A1, C5 |
| Casos de uso y procesos de negocio | C47, C48 | A3 |
| Documentación para usuarios funcionales | C49 | A2, A3, A4 |
| Glosarios de negocio | C51 | A4 |
| Diagramas y navegación al código | C52–C63 | A11, C4 |
| Evaluación de complejidad y roadmap | C77–C87 | A12 |
| Arquitectura objetivo y modernización | C88–C95 | B1 |
| Especificaciones OpenAPI | C93 | B4 *(si aplica)* |
| Conversión asistida, human-in-the-loop | C104, C105 | B2, B3 |
| **Validación de equivalencia funcional** | **C106** | **A1, B3, D1, D3, D4** |
| Generación de pruebas desde las reglas | C107 | D2 |
| Documentación del sistema modernizado | C108 | C1–C5 |
| Comparación legacy vs. modernizado | C110 | D3 |
| Evidencias de pruebas | C112 | D3, D4 |
| Auditoría y control de accesos | C121, C122 | C9 |

---

## 8. Criterios de cierre por fase

**Fin del descubrimiento (AS-IS)**
- [ ] A1 completo y validado por el verificador automático
- [ ] A2 con 100 % de reglas firmadas por el analista funcional del banco
- [ ] A5 sin preguntas bloqueantes abiertas
- [ ] A7 con la persistencia real documentada y confirmada
- [ ] D1 ejecutándose en verde contra el legacy

**Autorización para generar código**
- [ ] B1 con todos los supuestos declarados y resueltos
- [ ] B3 con todas las divergencias previstas **firmadas**
- [ ] B2 revisado por el arquitecto responsable

**Fin de la migración de un componente**
- [ ] C2 y C5 completos: toda regla con implementación y prueba, o justificación registrada
- [ ] C3 entregado físicamente, no sólo referenciado
- [ ] C7 con los parámetros de negocio inventariados y escalados los que sean regulatorios

**Autorización de salida a producción**
- [ ] D3 ejecutado: cero discrepancias críticas o altas no explicadas
- [ ] Toda diferencia observada corresponde a una entrada firmada de B3
- [ ] D4 con cobertura completa de reglas
- [ ] Doble firma: responsable técnico y responsable funcional del banco

---

## 9. Anexo · Hallazgos reales que justifican esta guía

Cada punto de esta sección se observó en un sistema real analizado. Ninguno es hipotético.

### Caso 1 — Sistema contable COBOL (3 programas, 85 líneas)

Documentado íntegramente desde el fuente, con verificación por **ejecución** del binario compilado.
Complejidad técnica baja, incertidumbre funcional alta: **9 de 22 reglas describían comportamientos
que probablemente nadie decidió.**

| Hallazgo | Detectado por | Implicación |
|---|---|---|
| Desbordamiento silencioso: saldo 1,000.00 + abono 999,999.00 → **999.00**, confirmado como operación exitosa | Ejecución | Reproducirlo por equivalencia estricta implantaría una pérdida de saldo silenciosa en un sistema nuevo |
| Un monto de `-50` produce un movimiento de **+50.00**: el tipo sin signo descarta el signo | Ejecución | Un error de captura se convierte en un movimiento válido y confirmado |
| Un monto `abc` produce 0.00 y el sistema **confirma el movimiento** | Ejecución | El operador cree haber operado |
| El saldo **no persiste**: reside en `WORKING-STORAGE` pese a llamarse `DataProgram` y usar operaciones `READ`/`WRITE` | Ejecución | El nombre del componente indujo a error sobre la arquitectura real |
| Un cargo por el importe **exacto** del saldo se autoriza (`>=`, no `>`) | Ejecución | Traducirlo como `>` produce un defecto visible sólo en el caso límite |

> **Lección.** Cuatro de los cinco hallazgos sólo aparecieron **al ejecutar el legacy**, no al leerlo.
> Cuando exista compilador, el requisito 0.2 no es opcional.

### Caso 2 — Sistema bancario COBOL portado a C# (.NET 8, 3 programas)

Paquete recibido **ya migrado**. El `MIGRATION.md` incluido era de buena calidad —tabla de
trazabilidad, decisiones razonadas y una sección honesta de limitaciones—, y aun así el paquete
presentaba brechas estructurales:

| Hallazgo | Implicación |
|---|---|
| **El fuente COBOL no se entregó** con el port | Las decisiones citan el legacy línea por línea; sin el fuente nada es verificable y la evidencia de equivalencia (C106) queda sin sustento |
| Umbrales AML como constantes compiladas (`AmountThreshold = 10000m`, `HighRiskCountry = "HIGH-RISK"`) | Cambiar un parámetro regulatorio exige recompilar y redesplegar, sin pista de auditoría → C7 |
| El proyecto `Domain` no contiene código, pese a anunciarse una arquitectura por capas | La documentación contradice al código; las reglas de negocio viven en la capa de aplicación → C1 |
| El layout de los archivos de ancho fijo se referencia desde el README pero **no está en el entregable** | El contrato de interfaz de la persistencia no se entregó → C3 |
| Una divergencia deliberada quedó marcada como *pendiente de verificación* contra el oracle | Correcto haberlo declarado; debe escalar a registro firmado → B3 |
| Un probable defecto del legacy (lectura de cuentas por posición y no por clave) se preservó deliberadamente | Decisión correcta de no corregir en silencio; requiere decisión firmada del banco → B3 |
| Existía un manifiesto de paridad, pero sin arnés de ejecución, fixtures ni reporte | La paridad estaba prevista, no demostrada → D3 |

> **Lección.** Un buen documento de migración no sustituye al paquete completo. La trazabilidad hacia
> un origen que no se entrega no es trazabilidad, y un manifiesto de paridad sin ejecución ni reporte
> no es evidencia de equivalencia.

---

## 10. Lista de verificación condensada

**Antes de migrar (COBOL)**
- [ ] A1 Registro de trazabilidad · [ ] A2 Reglas de negocio · [ ] A3 Casos de uso · [ ] A4 Glosario
- [ ] A5 Preguntas abiertas · [ ] A6 Inventario de programas · [ ] A7 Diccionario de datos
- [ ] A8 Dependencias · [ ] A9 Integraciones · [ ] A10 Batch · [ ] A11 Diagramas AS-IS
- [ ] A12 Complejidad y roadmap

**Transición**
- [ ] B1 Arquitectura objetivo · [ ] B2 Mapeo COBOL→C# · [ ] B3 **Divergencias firmadas**
- [ ] B4 OpenAPI *(si aplica)*

**Después de migrar (C#)**
- [ ] C1 Catálogo de servicios · [ ] C2 Reglas del sistema nuevo · [ ] C3 Modelo de datos
- [ ] C4 Diagramas TO-BE · [ ] C5 Trazabilidad regla→prueba · [ ] C6 Riesgos técnicos
- [ ] C7 Configuración y parámetros · [ ] C8 Runbook · [ ] C9 Seguridad

**Evidencia**
- [ ] D1 Línea base del legacy · [ ] D2 Casos derivados de reglas
- [ ] D3 Ejecución en paralelo · [ ] D4 Cobertura de reglas

---

### Las cinco reglas que resumen esta guía

1. **Sin el fuente legacy no hay migración documentable.** Es el requisito de entrada, no un detalle.
2. **Ejecutar el legacy, no sólo leerlo.** La mayoría de los hallazgos críticos sólo aparecen al correrlo.
3. **Distinguir la regla deliberada del accidente.** Reproducir un defecto por equivalencia estricta
   lo traslada a un sistema nuevo, y ahí ya no es herencia: es decisión.
4. **Toda diferencia se firma antes, no se descubre después.**
5. **La documentación se genera y se valida automáticamente**, o se desactualiza en el primer sprint.
