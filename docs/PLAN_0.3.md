# Plan de ejecución de PCTX 0.3

Fecha: 9 de octubre de 2026. Proyecto: `/ruta/al/proyecto`.

Objetivo: conservar y recuperar el conocimiento necesario para continuar una tarea
al cambiar de sesión o de IA, con evidencia, límites visibles y recuperación de datos.
Este documento desarrolla las diez mejoras del goal activo; una fase terminada no
equivale a una entrega completa. Actualizar los estados con evidencia del trabajo real.

## Estado y continuidad

- [x] Inspeccionar instrucciones, código, contexto y procesos existentes.
- [x] Respaldar el estado anterior a cualquier cambio de esta ejecución.
- [x] Completar la línea base y registrar sus resultados.
- [x] Fase B: contexto protegido, evaluación, relevancia y expansión.
- [x] C1: historial, comparación y restauración de registros.
- [x] Fase C: revisiones, revisión de evidencia y reanudación.
- [x] D1-D3: escaneo, recuperación, panel y diagnóstico.
- [x] Auditoría de pruebas, wheel/zipapp e instalación local.
- [x] Entrega integrada validada; contexto y cierre con snapshot final.

Respaldo inicial, externo a la raíz escaneada:
`~/pctx-backups/pctx-before-0.3-20261009T174936Z.tar.gz`.
Se verificó lectura del archivo y presencia de código, tests y manifiesto: 206 entradas.
SHA-256: `e5eb4d31b7125d8d271f0a5d2871e360f123eac2bc784160c8c2fa4cd5c959bb`.
Los permisos del archivo son privados. No restaurarlo sobre el trabajo actual por defecto.

Continuación solicitada: automatización `retomar-pctx-0-3`, en esta conversación,
programada para el 9 de octubre a las 12:50, America/Chihuahua. Al activarse debe
pausarse antes de continuar para impedir repeticiones. La automatización se activó a las 18:50 UTC y quedó verificada como `PAUSED`.
Su activación no demuestra que el límite de uso se haya restablecido.

Para retomar: leer este plan y `TASKS.md`, comprobar el código y los procesos vivos,
consultar el goal y continuar el primer criterio pendiente. No reiniciar trabajo por
una salida ausente o una observación interrumpida. No lanzar un segundo vigilante.

## Línea base y decisiones de diseño

Avance del 9 de octubre: código `0.3.0`. Fases B, C y D implementadas;
se está verificando la entrega integrada antes de cerrar el goal. Evidencia y comandos
en `docs/VALIDACION_0.3.md`. Los datos siguientes describen la línea base previa,
no el comportamiento actual de estos componentes.

La implementación inspeccionada declara 0.2.0 y esquema 1. No hay repositorio Git.
`compile.py` ordena registros por tipo y coincidencias de palabras; añade bloques
enteros si caben. Las omisiones se enumeran en metadatos, pero el texto compilado
solo anuncia su cantidad. No existe una reserva fiable para todas las restricciones.
`storage.upsert_record` reemplaza el registro actual sin conservar sus revisiones.
`tasks.py` mantiene una tarea activa y un historial limitado a 40 tareas.
`handoff verify` compara actualmente HEAD, rama y estado Git: esa comprobación
no demuestra que no cambió el contenido de un proyecto sin Git.

Comprobaciones iniciales de esta ejecución:

- `python3 benchmarks/clean_room.py`: PASS, 750 tokens aproximados, 8 registros.
- `python3 -m pctx --root /ruta/al/proyecto doctor --json`: 0 errores,
  0 advertencias, 11 registros.
- `python3 -m pctx --root /ruta/al/proyecto handoff verify`: coincide
  según el verificador actual; conservar la limitación sobre proyectos sin Git.
- `python3 -m unittest discover -s tests -q`: 28 pruebas pasan, 7.467 segundos.

Mantener los JSON canónicos portables, las APIs existentes y una instalación local
sin dependencias de ejecución obligatorias adicionales. Los índices y cachés serán
reconstruibles. No introducir un modelo o embeddings como requisito de búsqueda.
Mantener una tarea activa por carpeta. No inicializar Git para suplir continuidad.

## Fase B: contexto útil y medible

### B1. Benchmark antes de cambiar el selector (mejora 5)

Crear fixtures temporales deterministas y un informe JSON con escenario, versión,
presupuesto, tokens aproximados, hechos esperados recuperados, omisiones esenciales,
registros irrelevantes y duración. Guardar la línea base fuera de los datos canónicos.
Comparar las mismas entradas y los mismos presupuestos antes y después del cambio.
Los tiempos son mediciones, no una prueba estable para CI; las invariantes sí lo son.

Escenarios: proyecto pequeño; centenares y miles de registros con ruido; consulta
en español e inglés; rutas y componentes; restricción larga; exceso de restricciones;
handoff con bloqueos; evidencia obsoleta; decisiones sustituidas; IDs largos; caracteres
Unicode; presupuesto mínimo; registros privados. Repetir para detectar orden inestable.
Separar cobertura esencial de precisión general: un registro irrelevante no debe
ganar a una decisión aplicable solo por tener un tipo con mayor puntuación.

Aceptación: cada hecho esencial esperado aparece completo o queda identificado
inequívocamente como omitido; nunca se declara completitud si falta uno. Cero filtración
de datos privados y de prueba marcados como secretos. Presupuestos respetados según
la estimación declarada; no presentar caracteres/4 como conteo exacto del modelo.

### B2. Paquete esencial con omisiones explícitas (mejora 1)

Separar selección, renderizado y reporte. Construir primero el resumen de trabajo:
objetivo, restricciones aplicables, bloqueos y próximos pasos. Una restricción global
aplica siempre; no descartar restricciones por ausencia de palabras coincidentes.
No truncar una afirmación de forma que cambie su sentido. Reservar presupuesto para
la advertencia y referencias de expansión antes de añadir registros opcionales.

El reporte debe incluir completitud esencial, IDs seleccionados, esenciales omitidos,
motivos, coste estimado y referencia para recuperarlos. Si ni las referencias caben,
emitir una advertencia inequívoca y una vía de consulta al reporte completo fuera del
paquete. No saltar una restricción larga y luego afirmar que se preservó lo esencial.
Excluir registros sustituidos y datos privados antes de ordenar y explicar resultados.

Aceptación: regresiones para objetivo/bloqueos que casi agotan el presupuesto,
restricciones más largas que el paquete y múltiples restricciones en conflicto.
Las salidas CLI, MCP y panel deben comunicar la misma condición de incompletitud.

### B3. Relevancia explicable y expansión (mejoras 2 y 6)

Crear una selección compartida por búsqueda y compilación: normalización de texto,
coincidencia de rutas/evidencia, alcance del componente y enlaces de arquitectura.
Limitar expansión por relaciones para evitar que el grafo introduzca todo el proyecto.
Dar prioridad a la aplicabilidad y conservar estados inferido/obsoleto como advertencias.
Cada resultado debe explicar las coincidencias y su estado, con desempate determinista.

Añadir lectura individual por ID y consulta por componente en CLI/MCP, con filtros
coherentes de privacidad. El resumen inicial apunta a referencias estables; la expansión
entrega la evidencia y detalles solicitados. No depender de archivos Markdown desfasados.
Documentar comandos y herramientas nuevos solo cuando estén implementados.

Aceptación: búsqueda por ruta recupera decisiones sin coincidencia en el enunciado;
un componente relacionado mejora la recuperación con límites comprobables. Una
expansión por ID devuelve exactamente el registro autorizado y su evidencia; IDs
desconocidos y privados no revelan datos ni su contenido mediante explicaciones.

## Fase C: memoria recuperable y continuidad

### C1. Historial de registros (mejora 3)

Incorporar revisiones con identificadores estables y comparación de contenido útil,
ignorando timestamps para evitar revisiones vacías. Registrar origen, fecha, digest,
evidencia y relaciones explícitas de sustitución. Mantener el JSON actual como vista
canónica; evitar un nuevo almacén alternativo que pueda divergir silenciosamente.

Diseñar el protocolo de escritura bajo el bloqueo compartido: si una interrupción
deja revisión y registro descoordinados, detectar el estado y permitir recuperación
explícita. Una escritura atómica de un archivo no garantiza una transacción de dos.
Conservar revisiones corruptas como evidencia del problema. Restaurar una revisión
crea otra revisión, valida secretos y no vuelve a afirmar evidencia histórica como actual.

Aceptación: edición idempotente, cambios concurrentes, historial corrupto, fallo
entre escrituras, comparación y restauración. Privacidad aislada incluso al cambiar
sensibilidad: ningún historial previamente público debe seguir revelando contenido
que se ha clasificado privado. Definir esa transición y probarla antes de exponerla.

### C2. Revisión de evidencia, duplicados y conflictos (mejora 4)

Mostrar archivos afectados, hashes esperados/actuales y registros dependientes.
Confirmar exige revisar evidencia actual; corregir conserva historial; sustituir enlaza
ambos registros. Identificar duplicados por contenido normalizado y candidatos a
conflicto por ámbito/clave/relaciones explícitas. Una similitud textual no prueba una
contradicción: comunicar candidatos sin decidir cuál es verdadero automáticamente.

Aceptación: modificar/eliminar evidencia marca registros afectados, sin alterar otros;
las acciones de revisión producen estados y revisiones consistentes. Los posibles
conflictos siguen visibles hasta una resolución explícita y trazable.

### C3. Reanudación con diferencias (mejora 7)

Guardar un snapshot compacto por checkpoint/handoff con hashes de archivos del
proyecto y referencias/digests de memoria, aplicando exclusiones existentes. Comparar
añadidos, modificados y eliminados, rama/HEAD si existen y afirmaciones afectadas.
No contar vistas generadas como cambios de código ni modificar el snapshot guardado
al consultar diferencias. Preservar criterios, bloqueos y próximos pasos omitidos.

Aceptación: detectar cambios de contenido sin Git y en archivos ya modificados con
Git aunque porcelain no cambie; distinguir renombre si hay evidencia suficiente.
Reanudar desde CLI/MCP/panel conserva pendientes y muestra lo que requiere revisión.

## Fase D: eficiencia, recuperación e interfaz

### D1. Escaneo incremental transparente (mejora 8)

Reutilizar análisis estáticos de contenido identificado por hashes y versión del parser.
Invalidar por cambios de manifiestos, exclusiones y configuración. Un cambio de mtime
no demuestra un cambio semántico; una coincidencia de mtime tampoco prueba igualdad.
Ofrecer verificación completa para detectar cachés inválidas y documentar cualquier
optimización basada en metadatos. Agrupar ráfagas del watcher conservando cambios
añadidos/modificados/eliminados antes de refrescar el snapshot.

Reportar archivos descubiertos, procesados, reutilizados y límites de cantidad/tamaño.
La cobertura truncada debe verse en API, contexto y diagnóstico, no como éxito completo.
Aceptación: proyecto sin cambios, cambio pequeño, borrado, ráfaga, exclusión nueva,
caché corrupta, cambio con tamaño/mtime preservados y límite de archivos. Comparar
escaneo completo e incremental para los mismos resultados; publicar tiempos medidos.

### D2. Respaldos, esquemas y restauración (mejora 9)

Respaldar memoria con manifiesto e integridad antes de migrar. Previsualizar diferencias
y validar completamente un respaldo antes de escribir. Usar staging y bloqueo; hacer
un respaldo previo a restauración; manejar interrupciones sin perder el estado anterior.
Rechazar rutas fuera de raíz, enlaces peligrosos y archivos inválidos. Un respaldo
local completo puede contener registros privados y debe tener permisos privados;
una exportación portable normal mantiene las exclusiones de privacidad.

No aumentar el esquema por cambiar solo la versión del producto. Si cambia el formato,
implementar migración explícita y fixtures de esquema anterior; rechazar futuros
esquemas desconocidos en vez de normalizarlos silenciosamente.
Aceptación: ida/vuelta, corrupción, recorrido de rutas, respaldo privado, migración
desde 0.2, fallo de restauración y recuperación del estado previo.

### D3. Panel y diagnóstico de integración (mejora 10)

Integrar paquete y omisiones, expansión, diferencias, historial y revisión en el panel
existente. Confirmaciones únicamente para operaciones que sustituyen datos, con
previsualización concreta. Mostrar estados vacíos/errores y vistas móviles legibles.
Reutilizar el servicio compartido y los bloqueos; no añadir lógica de memoria solo al UI.

Diagnóstico local: versión y ejecutable, raíz resuelta e identidad del proyecto, modo
lectura/escritura efectivo y handshake/listado/llamada MCP controlada. Una prueba
de lectura no debe escribir ni iniciar una tarea. No cambiar configuración de otros
clientes/proyectos para simular compatibilidad. Mantener límites explícitos para IDEs,
ChatGPT web y sistemas operativos sin sesiones reales probadas.

Aceptación: flujos HTTP/MCP y navegador real para revisar, expandir, comparar y restaurar;
errores y permisos aplicados en servidor; sin errores JS ni exposición privada. Prueba
local de diagnóstico positiva y negativa con proceso cerrado y salida reproducible.

## Validación y entrega

Ejecutar desde `/ruta/al/proyecto`:

```bash
python3 -m unittest discover -s tests -q
python3 benchmarks/clean_room.py
```

Ampliar los scripts existentes para nuevas regresiones y guardar reportes reproducibles.
Después de cambios al panel, ejecutar `tests/ui_smoke.cjs` con Playwright/Chromium
realmente disponibles; registrar cómo se resolvió el runtime. Construir wheel 0.3.0,
ejecutar `tests/wheel_smoke.py` en venv limpio y comprobar zipapp/CLI/MCP/assets/apagado.
Conservar el wheel anterior y el respaldo inicial. Actualizar `pyproject.toml`,
`pctx/__init__.py`, changelog, guías, informe de validación y estado de implementación.

Al cierre, registrar resultados y limitaciones en memoria del propio PCTX, actualizar
handoff con pendientes reales, regenerar vistas y ejecutar:

```bash
python3 -m pctx --root /ruta/al/proyecto adapters sync --check
python3 -m pctx --root /ruta/al/proyecto doctor --json
python3 -m pctx --root /ruta/al/proyecto handoff verify
```

Cada una de las diez mejoras requiere evidencia de código y una prueba de su conducta,
no solo un comando que termine en cero. El goal permanece activo hasta verificar todos
los criterios. No publicar ni desplegar como parte de esta entrega.

## Auditoría de la entrega

Las diez mejoras tienen implementación compartida y pruebas; ver la matriz de
`docs/VALIDACION_0.3.md` y `validation/release-0.3.json`. Wheel, zipapp e instalación
local 0.3.0 comprobados. Doctor sin errores/advertencias y adaptadores sin drift.
El cierre usa snapshot de contenido nuevo; su comprobación queda en
`validation/final-0.3.json`. Las sesiones externas se mantienen explícitamente
sin probar, separadas de esta entrega local.

Decisiones de formato: revisiones en `_pctx_history`, dentro del mismo JSON
canónico, con reemplazo atómico de valor e historial. El esquema principal sigue
siendo 1. `migrate` previsualiza e inicializa historiales opcionales con respaldo
previo; los registros legacy siguen legibles sin migrar. Una restauración de
memoria usa journal, staging privado y respaldo previo; tras un corte debe
usarse `backup recover` antes de leer o escribir memoria parcialmente aplicada.

Política de privacidad: las transiciones público/privado de un ID existente se
rechazan en ambas direcciones. `migrate` no cambia sensibilidades ni publica
historiales privados. Esta restricción deliberada evita dejar copias históricas
públicas; cambiar la clasificación de copias y exportaciones externas requiere
un procedimiento independiente. No mezclar versiones de escritores: una versión
antigua puede descartar extensiones de historial.

Los snapshots de continuidad excluyen vistas generadas y datos privados; el
watcher no avanza los checkpoints explícitos. El análisis incremental reutiliza
parsers, pero verifica todos los hashes: no depende de mtime. Sus límites se
reportan y el grafo sigue siendo una vista acotada.

Las sesiones externas de IDEs, ChatGPT web y Windows/macOS permanecen sin probar;
no forman parte de la validación local entregada ni se declaran resueltas.
