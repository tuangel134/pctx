# PCTX — ejecución y continuación

## 0.7.1 — 24 de octubre de 2026

Corrección del caso W7: brief incorpora tarea/handoff y registros globales
identificados, sin asignar ese trabajo al worker ni incluir otros roles.
TTL de registros acepta 1d/24h/30m; reemplazos explican actualización por mismo ID
y destinos visibles en la misma raíz. Evidencia desfasada conserva sus avisos.
Validación: 194 pruebas (8 regresiones nuevas), 58 flujos Chromium sin errores JS,
11 recuperaciones y paquetes limpios. Evidencia en validation/release-0.7.1.json;
uso en docs/USO_0.7.1.md. Las sesiones externas del plan general siguen pendientes.

## 0.7.0 — 24 de octubre de 2026

Memoria vigente: reemplazos lógicos atómicos, TTL y evidencias comprobadas en vivo;
ranking reciente sin degradar la búsqueda semántica. Checks explícitos con resultado
observado, conteos, timeout y snapshots de fuentes; evidencia Git rama@commit.
Brief de cinco partes por rol en CLI/MCP/panel; importación idempotente de informes
como afirmaciones y escritura limitada a informes sin reservar código. Recuperación
de reservas vencidas, rutas seguras de delegación, quiet y export bajo demanda/determinista.
Validación local: 186 pruebas, 57 recorridos Chromium, once escenarios de recuperación,
incremental equivalente, léxico 7/10 e híbrido 10/10 y wheel/zipapp limpios.
Instalación 0.7, comprobación ejecutada por PCTX, respaldo y handoff documentados en
`docs/USO_0.7.md`, `docs/VALIDACION_0.7.md`, `validation/release-0.7.json`
y `validation/final-0.7.json`. Las sesiones externas siguen pendientes.

## 0.6.0 — 12 de octubre de 2026

Coordinación cooperativa entre sesiones: reservas atómicas por tarea y rutas,
caducidad, renovación, checkpoint, traspaso e historial en JSON canónico.
CLI/MCP/panel comparten reservas; el checklist muestra ocupación temporal y
filtra disponibilidad sin sumar revisiones ni alterar la evidencia al renovar.
Restaurar respaldos libera reservas antiguas. Contexto e historial acotados;
los trabajadores preservan la traza global del coordinador.
Validación local: 141 pruebas, 55 recorridos Chromium, once casos de recuperación,
regresión incremental y recuperación de conocimiento sin cambios, wheel/zipapp
limpios e instalación 0.6.0. Evidencia y límites: `docs/COORDINACION_0.6.md`,
`docs/VALIDACION_0.6.md`, `validation/release-0.6.json` y `validation/final-0.6.json`.
Siguen pendientes las sesiones reales entre clientes/modelos externos.

## 0.5.0 — 11 de octubre de 2026

Metas/checklists implementados con estados, jerarquía, criterios, dependencias,
revisiones con contador/evidencia/vigencia, cinco dificultades y riesgo separado.
CLI/MCP/panel comparten JSON e historial; consultas acotadas y selección de trabajo
listo/sin responsable. El plan real mantiene comprobaciones locales y pendientes externos.
Validación: 120 pruebas, 47 recorridos Chromium sin errores JS, once casos de recuperación,
wheel/zipapp limpios e instalación local 0.5.0. Detalle y límites en
`docs/CHECKLISTS_0.5.md`, `docs/VALIDACION_0.5.md`, `validation/release-0.5.json`
y `validation/final-0.5.json`. Traspasos reales entre IAs/clientes siguen sin probarse.

## 0.4.0 — 9 de octubre de 2026

Recuperación unificada implementada: SQLite FTS5 reconstruible, fragmentos con
referencias vigentes, salida acotada, grafo de evidencia/relaciones, documentos
en contexto y ONNX CPU opcional sin descargas ni servicios implícitos.
Validación: 92 pruebas, 34 recorridos Chromium, 11 escenarios de recuperación,
wheel/zipapp limpio e instalación local 0.4.0 con extras semánticos.
Benchmark sintético: 0.3 recupera 2/10 respuestas, texto/grafo 7/10, híbrida 10/10;
9918 / 6007 / 7727 tokens estimados respectivamente. Los clientes externos y el
cambio real entre IAs siguen pendientes de prueba, fuera del alcance local.
Plan, uso y evidencia: `docs/PLAN_0.4.md`, `docs/RECUPERACION_0.4.md`,
`docs/VALIDACION_0.4.md`, `validation/release-0.4.json`, `validation/final-0.4.json`.

## 0.3.0 — 9 de octubre de 2026

Las fases B, C y D están implementadas: las diez mejoras del goal tienen código
y pruebas. Entrega integrada: 72 pruebas unittest, 11 escenarios de recuperación
y 28 recorridos Chromium pasan; wheel/zipapp en venv limpio e instalación editable
0.3.0 comprobados. Contexto final validado con doctor, adaptadores y handoff;
resultados en `validation/release-0.3.json` y `validation/final-0.3.json`.
Plan y criterios: `docs/PLAN_0.3.md`; matriz y pruebas: `docs/VALIDACION_0.3.md`.
La automatización `retomar-pctx-0-3` se activó y quedó verificada como pausada.

Se preservan el respaldo inicial externo y el wheel 0.2. Las sesiones reales
externas siguen sin probarse. No se inicializó Git ni se publicaron cambios.

## Historial de la entrega 0.2

Objetivo autorizado: mejorar PCTX ahora, con interfaz gráfica local, actualización fiable e integración con distintas IAs/proyectos. La ejecución programada continúa el trabajo pendiente; no debe empezar desde cero.

## Criterios de aceptación

- Panel local para abrir/inicializar proyectos, consultar memoria, arquitectura, tareas, registrar conocimiento y configurar integraciones.
- Vigilancia opcional de cambios, detección de evidencia obsoleta y generación coherente sin bucles causados por archivos generados.
- Escrituras serializadas entre CLI, MCP y panel; recuperación explícita ante interrupciones o corrupción.
- MCP lectura/escritura, recursos y guía de ciclo de trabajo; puente CLI invocable mediante terminal del MCP Master.
- Configuraciones instalables conservando otros servidores y reglas manuales.
- Pruebas unitarias, integración HTTP/MCP, interacción real con el panel y paquete instalable.
- Documentación que distinga lo probado de la compatibilidad no comprobada en clientes externos.

## Estado inicial comprobado

2026-09-12: versión 0.1, 10 pruebas pasan. No hay repositorio Git en esta carpeta. Python del sistema 3.14; Tk no funciona por ausencia de libtk, por lo que la interfaz será un panel web exclusivamente local sin dependencias de ejecución adicionales.

## Implementado y comprobado

- Servicio compartido (`service.py`), bloqueos reentrantes de procesos/hilos y seguimiento de archivos con hashes. También funciona mientras un MCP permanece conectado con `--watch`.
- Panel gráfico (`dashboard.py`, `pctx/web/`) con proyectos, selector de carpetas, contexto, tareas, reanudación, conocimiento, revisión, arquitectura visual, integraciones y diagnóstico. Servidor exclusivamente loopback con acceso temporal autenticado.
- Configuraciones instalables para VS Code, Cursor, Claude Code y bloque genérico; preservación de otros servidores y respaldos privados.
- Puente de comandos finitos `pctx call`, guía de Master MCP y copia portable `.project-context/.runtime/pctx.pyz`. Inspeccionados los nombres de herramientas del dispatcher de Tessarion; no se modificó Tessarion.
- MCP con validación de argumentos, recursos y prompt; actualización por ID estable, conservación de pendientes al finalizar y recuperación de tareas.
- Presupuestos de contexto que incluyen cabecera, exclusión de registros privados, subproyectos, exclusiones personalizables, evidencia obsoleta y errores de corrupción sin reinicialización silenciosa.
- Instalación editable local 0.2.0 en `~/.local/share/pctx/venv`, enlace `~/.local/bin/pctx`, lanzador `~/.local/share/applications/pctx.desktop`.
- 28 pruebas automatizadas pasan, incluyendo escritura concurrente por 12 procesos, vigilancia de MCP sin llamadas adicionales, privacidad, presupuesto, zipapp aislado y API HTTP.
- Prueba Chromium: 16 recorridos de interfaz pasan; capturas de escritorio/móvil y reporte en `validation/` (excluido del contexto).
- Construcción de wheel y prueba en venv limpio pasan: CLI, MCP, zipapp, assets del panel y apagado.
- Documentación en `docs/GUIA_USO.md`, `docs/INTEGRACIONES.md` y `CHANGELOG.md`.

## Continuación activada el 12 de septiembre a las 09:46 (Chihuahua)

La ejecución única programada ya se activó durante el trabajo. Continuar desde esta implementación; no hay que volver a crear el panel ni duplicar una automatización.

Cierre: pruebas finales de memoria, privacidad, interfaz y paquete pasan. La instalación editable 0.2.0 y el lanzador de aplicaciones están disponibles. El informe reproducible está en `docs/VALIDACION.md`. Se inició el panel de la instalación local para la entrega; se apaga con su botón y puede abrirse nuevamente desde el menú PCTX. La memoria del propio PCTX conserva la entrega y las comprobaciones externas pendientes.

## Límites y comprobaciones externas

Revalidación del 13 de septiembre de 2026: la continuación volvió a activarse pese a haberse solicitado una sola ejecución. Se pausó la automatización existente mediante Codex y se comprobó su estado `PAUSED`, sin crear otra. La instalación sigue en 0.2.0; las 28 pruebas unittest y los 16 recorridos Chromium pasan de nuevo, sin errores de JavaScript. El diagnóstico de memoria no encontró errores ni advertencias. No se rehízo la implementación ni se consideraron resueltas las comprobaciones externas siguientes.

- Gateway real de Tessarion comprobado: contexto, registro, checkpoint, handoff y lectura posterior mediante host_terminal_execute; zipapp con lectura/escritura/cierre mediante terminal_execute en sandbox workspace-write. Queda sin verificar la elección automática de herramientas en una conversación de ChatGPT web; no confundirla con la prueba del gateway desde Codex.
- No se probaron sesiones reales dentro de todos los IDEs ni Windows/macOS. El formato portable no implica compatibilidad universal de clientes ni comprensión semántica completa.
- Una tarea activa por carpeta; bloqueos de escritura no equivalen a planificación concurrente multiagente. Los parsers estáticos conservan límites documentados.
- No se abrió un endpoint público, no se publicó un servicio y no se modificaron despliegues ajenos.

La memoria canónica del proyecto está en `.project-context/`. Consultar también `TASKS.md` y `PROJECT_CONTEXT.md`. Actualizar este estado antes de ceder o terminar la sesión.
