# Cambios

## 0.7.1 — 2026-10-24

- Brief por rol conserva tarea, handoff y registros compartidos con marca `[global]`;
  prioriza objetivo/acciones del worker y excluye asignaciones de otros roles.
- Sin datos específicos del rol, muestra contexto global disponible y avisa que
  los esenciales de ese worker están incompletos. CLI/MCP/panel comparten la selección.
- Últimos cambios puede mostrar el checkpoint y actualizaciones de memoria,
  sin presentarlas como código verificado. Restricciones desfasadas siguen avisadas.
- `record --ttl` acepta segundos y unidades enteras s/m/h/d/w, guardando segundos.
- Errores de reemplazo explican actualización del mismo ID y búsqueda en la raíz
  correcta; destinos privados e inexistentes conservan la misma respuesta.

## 0.7.0 — 2026-10-24

- Archivado lógico automático por `replaces` o `claim_key`, caducidad volátil y
  ranking con vigencia/recencia sin promover ruido sobre coincidencias semánticas.
- Checks explícitos con revisión esperada, timeout, conteos observados y hash
  acotado de salida; snapshots de fuentes y evidencia Git invalidables en vivo.
- `brief --budget 800 --role W4` en CLI/MCP/panel con cinco partes fijas y omisiones.
- Importación idempotente de informes por sección; roles del log compartido,
  procedencia y estado inferido conservados. Escritura limitada a informes sin reserva.
- Limpieza de reservas vencidas con checkpoints, rutas de delegación seguras,
  alias inequívocos y liberación tardía que no altera la reserva del sucesor.
- `--quiet`, respuestas compactas, export manual por proyecto y escrituras de
  contenido idéntico que conservan inode/mtime; compatibilidad del CLI de decisiones.


## 0.6.0 — 2026-10-12

- Reservas temporales de tareas y rutas para sesiones de IA que comparten raíz;
  detección atómica de solapamientos de carpetas/archivos y jerarquías del plan.
- Renovación, revisión esperada, caducidad, historial y liberación con checkpoint.
- Ocupación temporal visible y trabajo listo filtrado; heartbeats independientes
  de revisiones/evidencias del checklist y del índice de recuperación.
- CLI/MCP/panel y guías de trabajo paralelo sin sobrescribir la traza del coordinador.
- Restaurar un respaldo libera reservas antiguas con historial; rutas privadas,
  alias inseguros y modificaciones genéricas de reservas se rechazan.


## 0.5.0 — 2026-10-11

- Metas, tareas, bugs y comprobaciones en JSON canónico con jerarquía, prioridad,
  responsable, criterios de aceptación y dependencias sin ciclos.
- Casillas de hecho separadas de verificado; cierre protegido por pendientes,
  criterios, revisión aprobada y evidencia vigente. Reabrir/editar invalida comprobaciones.
- Revisiones con resultado/revisor/fecha/evidencia, contador e historial. Reintentos
  protegidos por event_id y escrituras concurrentes por revisión esperada.
- Cinco dificultades explícitas con motivo, riesgo independiente y filtros de
  trabajo disponible para repartir entre IAs sin selección o gasto automático.
- CLI/MCP/panel con páginas, resumen breve para contexto/TASKS, árbol Markdown
  portable, diagnósticos de verificaciones obsoletas y protección de IDs reservados.

## 0.4.0 — 2026-10-09

- Recuperación unificada de registros activos y documentos con FTS5, fragmentos,
  hashes de revisión, filtros, paginación y presupuesto de JSON visible.
- Consultas sin escritura: índice faltante, obsoleto o corrupto se declara y se
  reconstruye únicamente en memoria; contenido siempre tomado de fuentes actuales.
- Grafo de evidencia, relaciones explícitas portables y archivos de arquitectura;
  navegación limitada a dos saltos, sin reconstruir conocimiento con un LLM.
- Herramientas CLI/MCP/panel para buscar, ampliar, navegar y reconstruir el índice.
  El contexto de tarea incluye documentos después de las restricciones esenciales.
- Embeddings ONNX CPU opcionales, fusión RRF, modelo local explícito y validación de
  identidad/dimensiones. Sin API de pago, consultas guardadas ni descarga automática.
- Benchmark reproducible de traspaso sintético, paráfrasis y coste de resultados;
  privacidad, concurrencia, corrupción y regresiones cubiertas por pruebas.

## 0.3.0 — 2026-10-09

- Contexto esencial prioritario, omisiones explícitas y reporte separado del paquete
  con presupuesto aproximado; consultas CLI de solo lectura con JSON válido.
- Recuperación por texto, vocabulario español/inglés explícito, evidencia, alcance y
  un salto acotado de arquitectura; motivos de selección y exclusión.
- Expansión por ID/componente en CLI, MCP y panel; los registros privados no se exponen.
- Revisiones dentro del mismo JSON canónico, comparación y restauración protegida
  por revisión esperada. Una restauración crea una nueva revisión inferida.
- Panel con advertencias de incompletitud, informe de selección, expansión e historial.
- Benchmark de once escenarios comparado con el código 0.2 respaldado; pruebas de
  privacidad, presupuestos, concurrencia, interrupción e integridad de revisiones.
- Revisión compartida de hashes de evidencia, corrección y sustitución con historial;
  candidatos a duplicado/conflicto explícitos, sin resolución automática.
- Snapshots portables por checkpoint/handoff; diferencias de contenido con o sin Git,
  evidencia afectada y pendientes conservados. Los watchers no borran el baseline.
- Cachés de parsers por hash/configuración/versión, verificación completa y agrupación
  de ráfagas; límites de archivos, lectura y arquitectura visibles.
- Respaldos privados con integridad y previsualización; restauración protegida por
  digest, respaldo previo, journal y recuperación tras muerte del proceso.
- Migración explícita de historiales opcionales del esquema 1; formatos futuros y
  transiciones público/privado rechazados sin sobrescritura silenciosa.
- Panel con revisión/diferencias/respaldos; diagnóstico finito de MCP con llamada real,
  raíz/identidad/versión y permisos efectivos, también desde zipapp aislado.

## 0.2.0 — 2026-09-12

- Panel local: proyectos recientes y selector de carpetas, contexto, tareas,
  conocimiento con revisión, mapa visual/Mermaid, integraciones y diagnóstico.
- Instalador Linux aislado y acceso desde el menú de aplicaciones.
- Seguimiento opcional en panel, CLI y MCP; conserva archivos modificados antes
  de refrescar hashes y evita ciclos por archivos generados.
- Servicio compartido de regeneración y bloqueos reentrantes entre procesos e
  hilos para CLI, MCP, tareas, arquitectura y panel.
- Detección explícita de memoria corrupta y actualizaciones interrumpidas;
  conservación de notas manuales de tareas.
- Recuperación de tareas pendientes, conservación de campos omitidos al cerrar
  e IDs estables para actualizar conocimiento sin duplicarlo.
- Validación de argumentos MCP, recursos y prompt de ciclo de trabajo.
- Paquetes de contexto que incluyen cabecera dentro del presupuesto aproximado.
- Filtrado de registros privados en exportaciones y búsquedas; exclusiones
  `.pctxignore`, correcciones de Git sin commits y nombres con espacios.
- Análisis de manifiestos en subproyectos y retirada de comandos que dejan de
  existir; no se propone pytest solo por encontrar una carpeta de tests.
- Configuraciones MCP fusionables para VS Code, Cursor y Claude Code; bloque
  genérico y guía de MCP Master basada en herramientas locales inspeccionadas.
- Zipapp portable para ejecutar PCTX dentro del workspace de un terminal aislado.
- Pruebas de concurrencia, cambios, presupuestos, privacidad, HTTP, MCP y flujos
  de interfaz en Chromium, incluyendo tamaños de escritorio y móvil.

### Límites comprobables

El programa no interpreta toda la semántica de un repositorio ni fuerza el uso
de herramientas por una IA. La instalación y el flujo visual están probados en
Linux. Las configuraciones se prueban contra PCTX; no equivalen a pruebas de una
sesión real dentro de cada IDE o de ChatGPT web. Los bloqueos serializan archivos,
pero no crean varias tareas activas independientes en una misma carpeta.
