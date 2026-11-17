# PCTX 0.3: guía de uso

PCTX es un programa local de Python 3.10 o posterior. Tiene CLI, servidor MCP y
panel gráfico en el navegador. No utiliza modelos ni APIs de pago: los hechos se
extraen estáticamente y la IA o la persona registra decisiones y significado.

## Instalación en este equipo

```bash
cd /ruta/al/proyecto
python3 install.py
```

El instalador crea un entorno aislado en `~/.local/share/pctx/venv`, instala el
proyecto editable, crea `~/.local/bin/pctx` y añade
`~/.local/share/applications/pctx.desktop` al menú de aplicaciones. No modifica
el Python del sistema. La instalación inicial puede descargar herramientas de
construcción; el funcionamiento posterior es local y sin dependencias externas.

Abre **PCTX** en el menú de aplicaciones o ejecuta:

```bash
~/.local/bin/pctx --root /ruta/al/proyecto gui
```

Si el código fuente cambia, la instalación editable usa ese código. Cierra y
vuelve a abrir el panel y reinicia los MCP para cargar la versión nueva.
Si mueves el código fuente, vuelve a ejecutar el instalador y regenera las
configuraciones de clientes, que contienen rutas absolutas.

Para instalar desde el paquete distribuible:

```bash
python3 -m venv /ruta/a/entorno-pctx
/ruta/a/entorno-pctx/bin/python -m pip install /ruta/a/pctx-0.3.0-py3-none-any.whl
/ruta/a/entorno-pctx/bin/pctx gui
```

## Abrir un proyecto sin comandos

1. Pulsa **Abrir proyecto**.
2. Escribe la ruta o pulsa **Elegir carpeta…** y navega por las carpetas locales.
3. Mantén marcada la inicialización para crear o regenerar las vistas de PCTX.
4. Pulsa **Abrir proyecto**. El código fuente no se modifica.
5. Activa **Seguimiento automático** si quieres que el panel detecte cambios.

El registro de carpetas recientes vive en `~/.config/pctx/projects/`. Solo guarda
rutas. La memoria de cada proyecto vive dentro de ese proyecto. Para pruebas se
puede cambiar el registro mediante `PCTX_CONFIG_DIR`.

## Qué puedes hacer en el panel

| Sección | Uso |
| --- | --- |
| Vista general | Ver cantidad de archivos, registros, revisión pendiente y última actualización. |
| Contexto | Leer/copiar la exportación completa o preparar una tarea con presupuesto aproximado de tokens. |
| Tareas y continuidad | Guardar objetivo, criterios, pasos y bloqueos; cerrar una sesión; retomar una tarea pendiente. |
| Arquitectura | Buscar componentes, ver conexiones, copiar Mermaid y añadir relaciones que el escáner no puede inferir. |
| Conocimiento | Expandir, inspeccionar historial y evidencia; confirmar, corregir o sustituir con un enlace explícito. |
| Conectar una IA | Generar/instalar configuraciones, comprobar el MCP local y preparar una copia portable para MCP Master. |
| Diagnóstico | Revisar memoria y límites; crear respaldos privados, previsualizar y restaurar con protección frente a cambios. |

El gráfico del panel es una vista SVG compacta del mismo JSON que genera Mermaid.
Muestra hasta 18 componentes y la lista visible hasta 80 conexiones; usa la
búsqueda o el archivo de arquitectura para ampliar. No descarga Mermaid ni
otros recursos desde Internet.

## Dónde están los archivos

Dentro de la carpeta seleccionada:

```text
PROJECT_CONTEXT.md                 exportación completa para personas e IAs
architecture.md                    mapa Mermaid y notas manuales
TASKS.md                           tarea actual y sesiones recientes
AGENTS.md                          instrucciones breves para asistentes
.project-context/
  manifest.json                    identidad y presupuestos del proyecto
  records/*.json                   hechos, decisiones, restricciones y evidencia
  architecture.json                conexiones generadas y conexiones registradas
  work/TASKS.json                  estado e historial de tareas
  work/HANDOFF.json                resultado y pendientes de la última sesión
  .cache/snapshot.json             hashes del último análisis
  .cache/refresh.json              estado de la última regeneración
  .private/backups/                respaldo de configuraciones antes de sustituirlas
  .private/records/                registros privados, excluidos de exportación y Git
  .runtime/pctx.pyz                copia portable opcional del programa
  .lock                           bloqueo compartido entre procesos
```

Los JSON canónicos son la fuente de verdad. `PROJECT_CONTEXT.md` se regenera:
registra conocimiento desde el panel, el MCP o `pctx record`; editar solamente
esta exportación hará que tu edición desaparezca en el próximo refresco.

Las notas fuera de bloques administrados en `architecture.md`, `TASKS.md` y las
reglas de clientes se conservan. `.cache`, `.private`, `.runtime` y `.lock`
están excluidos por el `.gitignore` interno. Puedes versionar los demás archivos.

## Actualización automática y significado

El seguimiento revisa cada cinco segundos los archivos permitidos y compara sus
hashes. Agrupa ráfagas hasta un intervalo sin cambios de contenido; el refresco
puede tardar un intervalo adicional. Detecta archivos añadidos, modificados y eliminados, y cambios de
identidad de Git. Antes de guardar una nueva instantánea, acumula los archivos
afectados en la tarea activa. Después escanea hechos, marca evidencia obsoleta,
regenera la arquitectura, exporta contexto y sincroniza los adaptadores instalados.
Los propios archivos generados no provocan ciclos de actualización.

Un cambio de código puede hacer obsoleto un hecho anterior. PCTX lo marca como
`stale`; no afirma que el hecho siga siendo correcto. Una decisión como
«elegimos PostgreSQL por estas razones» requiere que la IA o tú la registre.
El seguimiento no captura conversaciones ni adivina intenciones.

Las escrituras de CLI, MCP y panel se serializan con un bloqueo por proyecto.
Esto evita perder registros por escrituras simultáneas. Sigue existiendo una
sola tarea activa por carpeta: dos agentes con objetivos distintos necesitan
coordinarse o trabajar en carpetas/worktrees separados.

## Pasar de una IA a otra

La primera IA carga `pctx_context`, registra avances y cierra con `pctx_finish`.
La segunda usa el mismo proyecto y `pctx_task_resume` para retomar pendientes,
después pide contexto para la tarea. Si el proceso se corta antes de cerrar,
la tarea activa conserva los últimos checkpoints. No puede recuperar acciones
que nunca llegaron a guardarse.

Al llamar `pctx_finish`, los campos omitidos conservan los pendientes y bloqueos
de la tarea. Envía `next_actions: []` o `blockers: []` solo cuando corresponda
limpiarlos. Una tarea con pendientes se cierra como pausada; con bloqueos, como
bloqueada; sin ambos, como terminada.

## Encender y apagar

| Modalidad | Encendido | Apagado |
| --- | --- | --- |
| Panel | Menú PCTX o `pctx gui` | **Apagar panel** o Ctrl+C en su terminal. |
| Vigilancia del panel | Interruptor de seguimiento | Desactivar interruptor o apagar el panel. |
| MCP gestionado por IDE | Instalar configuración y activarlo en el cliente | Detener/desactivar MCP desde ese cliente. |
| MCP manual | `pctx mcp serve --allow-write --watch` | Ctrl+C o cierre de su entrada estándar. |
| Vigilancia sin interfaz | `pctx watch` | Ctrl+C. |
| Operación única | `pctx scan` o `pctx call ...` | Termina sola. |

Cerrar una pestaña del navegador no apaga el proceso del panel. Usa su botón.
El panel solo escucha en `127.0.0.1`; imprime una URL de acceso temporal. No
expongas esa URL como un endpoint remoto ni la confundas con MCP.

## Alcance del análisis

Se puede inicializar cualquier carpeta con permisos de lectura/escritura, con
o sin Git. El análisis reconoce manifiestos comunes y hasta 48 subproyectos
anidados; la profundidad varía por ecosistema. El escaneo habitual tiene un
límite de 10 000 archivos y marca si fue parcial. `scan --max-files N` permite
un escaneo manual más amplio; el seguimiento conserva su límite de 10 000.

Excluye dependencias, compilaciones, `.env`, claves privadas y las salidas de
PCTX. Añade patrones en `.pctxignore` para datos que no deban inspeccionarse.
Los patrones son una implementación ligera; fuera de Git no implementan toda la
semántica de archivos `.gitignore` anidados.

Los nuevos registros privados se guardan en `.private/records/`, no se exportan
ni aparecen en búsquedas. Un registro público existente no puede hacerse privado
reutilizando su ID sin archivarlo antes: así no se oculta que ya pudo haberse
versionado. La detección de
secretos es heurística: revisa lo que decides guardar. La información inferida
permanece diferenciada de la confirmada por una persona.

El presupuesto de un paquete de tarea incluye cabecera y contenido usando una
estimación de caracteres; no es un conteo exacto para todos los tokenizadores.
Si un registro no cabe, se informa de la omisión. No asumas que un paquete
pequeño representa todo el proyecto: usa búsqueda o la exportación completa.

## Recuperación y diagnóstico

```bash
pctx --root /ruta/al/proyecto doctor
pctx --root /ruta/al/proyecto scan
pctx --root /ruta/al/proyecto adapters sync --check
```

Si el refresco fue interrumpido, vuelve a actualizar para reconstruir las vistas.
Si un JSON canónico está corrupto, PCTX muestra un error y no lo reemplaza por
memoria vacía: repara el archivo señalado o recupera una versión de Git/respaldo.
Las escrituras son atómicas por archivo; varias vistas se actualizan bajo el
mismo bloqueo, pero no forman una transacción de base de datos con rollback.

La configuración de un cliente se fusiona conservando otros servidores. Si el
archivo existente no es JSON válido (por ejemplo JSONC con comentarios), se
rechaza el cambio; copia el bloque desde el panel y edítalo en el cliente.

## Desinstalación

El programa y su entorno están en `~/.local/share/pctx/venv`; el acceso directo,
en `~/.local/share/applications/pctx.desktop`; el enlace de terminal, en
`~/.local/bin/pctx`. Puedes retirar esos elementos y el registro de proyectos
desde el gestor de archivos. La memoria dentro de tus proyectos es independiente
y seguirá siendo legible sin instalar PCTX.

## Herramientas nuevas de 0.3

Consulta [validación y comandos](VALIDACION_0.3.md) para contexto de solo lectura,
expansión, historial, revisión, diferencias, respaldo/restauración, migración y
diagnóstico. El panel muestra esas mismas funciones mediante servicios compartidos.
`scan --full` omite cachés de parsers; todos los modos vuelven a verificar hashes.

Los respaldos locales incluyen memoria privada y no están cifrados. Se crean fuera
de la raíz del proyecto con permisos 0600; no los compartas como exportaciones
públicas. `PROJECT_CONTEXT.md` y la búsqueda habitual excluyen registros privados
así como snapshots históricos. Los cambios de sensibilidad de IDs existentes se
rechazan; `migrate` no los publica ni reclasifica.

## Metas, checklists y dificultad (0.5)

Abre **Metas y checklists** para metas/subtareas/bugs, estados, revisiones y filtros de dificultad/riesgo. [Guía completa](CHECKLISTS_0.5.md): hecho y verificado son estados distintos; solo una revisión registrada aumenta el contador.


## Varias IAs a la vez (0.6)

Abre **Metas y checklists → Trabajo entre IAs** para reservar tarea y rutas,
renovar con checkpoint y liberar con traspaso. Las sesiones usan una raíz común
con IDs distintos. El coordinador gestiona la traza global; trabajadores usan
contexto de solo lectura y checkpoints de reserva. Reparto por dificultad,
dependencias, recuperación y límites: [COORDINACION_0.6.md](COORDINACION_0.6.md).


## Memoria vigente y prompts cortos (0.7)

Usa `pctx brief --budget 800 --role W4` al delegar. Mantén claves de estado o
relaciones de reemplazo y TTL para hechos volátiles; importa los HECHO y el log
de integración para conservar avances sin duplicarlos. Los checks y Git tienen
evidencia observada en vivo. `record --quiet` y `export --policy manual` reducen
ruido. Guía completa: [USO_0.7.md](USO_0.7.md).
