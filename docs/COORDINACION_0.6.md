# Trabajo coordinado entre IAs — PCTX 0.6

PCTX mantiene metas, subtareas, dificultad y dependencias, y añade reservas
transitorias de tareas y zonas de código. Todas las sesiones deben usar la misma
raíz canónica y una versión compatible con este protocolo. Las reservas y sus
checkpoints son JSON portable en `.project-context/records/coord.*.json`; no
requieren base vectorial, proveedor, llamadas a modelos ni un servicio externo.

## Repartir un proyecto grande

El coordinador crea una meta con criterios y la divide en tareas pequeñas;
indica dificultad, riesgo y dependencias. Conviene asignar módulos independientes
y separar la revisión de la implementación. Una IA consulta únicamente el trabajo
que puede hacer y reserva su tarea y rutas antes de empezar. Otra IA puede trabajar
en una tarea independiente, mientras ve las zonas ocupadas y los checkpoints.

```bash
pctx context --read-only --task 'Implementar login' --budget 2000
pctx plan list --difficulty easy --ready --budget 1500
pctx plan detail --id plan.login --budget 2000
pctx coordinate list --status active --budget 1500
pctx coordinate claim --session-id ia-login-01 --task-id plan.login \
  --path src/login --path tests/login.py --ttl 900
```

`plan.login` debe existir. Guarda el `id` y `current_revision` devueltos por la
reserva. El ID de sesión es una etiqueta pública y estable para ese trabajador;
usa una distinta por sesión. La adquisición es atómica bajo el bloqueo del proyecto:
reservar `src/login` bloquea también `src/login/form.py`, y viceversa. Se compara
sin distinguir mayúsculas de forma conservadora. Reservar una meta bloquea
reservas de sus descendientes. Reservar subtareas hermanas permite trabajo paralelo
si sus rutas no se solapan. Las dependencias pendientes, tareas cerradas o bloqueadas
y un responsable permanente diferente impiden adquirir la reserva.

## Mientras se trabaja

Una reserva dura 15 minutos por defecto; admite entre 60 y 3600 segundos. Renueva
antes de `expires_at`, con margen suficiente para la siguiente edición o comando.
No hay renovación automática ni un proceso que permanezca despierto. Si la sesión
se interrumpe, la reserva vence; el trabajador anterior debe dejar de editar y
volver a adquirirla. Consulta el detalle y los archivos antes de continuar.

```bash
# Sustituye coord.ID y la revisión por los valores actuales.
pctx coordinate renew --id coord.ID --session-id ia-login-01 \
  --expected-revision 1 --summary 'Formulario implementado; falta validar errores'

pctx plan status --id plan.login --expected-revision 1 --status in_progress \
  --session-id ia-login-01 --lease-id coord.ID

pctx coordinate release --id coord.ID --session-id ia-login-01 \
  --expected-revision 2 --summary 'Formulario listo; siguiente paso: probar errores'
```

Renovar sin `--ttl` conserva la duración existente. `summary` es un checkpoint
breve, hasta 500 caracteres en una línea: resultado y siguiente paso, sin
conversaciones ni secretos. Liberar exige un resumen. No completa ni verifica
la tarea: usa los estados y revisiones explícitos del checklist. Las renovaciones
no incrementan revisiones del checklist ni invalidan sus evidencias. Cambiar una
tarea reservada exige el ID de reserva activa y el ID de sesión. Un ID vencido
no autoriza cambios aunque otra sesión haya vuelto a reservar la tarea.

Los cambios de una reserva requieren su `expected_revision`: si otro proceso
la renovó o liberó, consulta de nuevo. No reintentes adquisiciones ciegamente si
se perdió la respuesta; busca tu `session_id` en el listado. El historial retiene
checkpoints por revisión, con páginas y presupuesto. Tras 512 revisiones, guarda
un traspaso, libera y adquiere otra reserva. La liberación sigue disponible.

## Recuperación e interfaces

En **Metas y checklists → Trabajo entre IAs**, abre el detalle de una tarea,
indica sesión y rutas, y reserva. El panel muestra trabajador, tarea, rutas,
vencimiento, último checkpoint e historial; permite renovar o liberar. Actualiza
las reservas para ver su vigencia actual. `Trabajando` es ocupación temporal,
separada del estado declarado del trabajo. El filtro de trabajo listo excluye
tareas con reservas activas. Las tareas en curso tras un corte pueden retomarse
consultando `coordinate list --status expired`, su checkpoint y el checklist.

MCP expone `pctx_coordination` (lectura) y `pctx_coordination_update` (escritura
habilitada). Aceptan las mismas acciones y campos de CLI, con `paths` como lista.
La lectura y la detección de vencimiento no escriben. Contexto/TASKS incluyen un
resumen limitado; el historial de renovaciones queda fuera del índice de búsqueda.
Las vistas Markdown son fotografías: consulta siempre la herramienta en vivo
antes de editar. Las listas/detalles/historiales usan presupuesto aproximado
chars/4, paginación y aviso de truncamiento; si no cabe ningún elemento, aumenta
el presupuesto antes de avanzar.

La traza global `pctx_task_update`/`pctx_finish` sigue siendo de una sesión. En
trabajo paralelo, solo el coordinador la gestiona; los trabajadores usan
`pctx_context_report` o `context --read-only` y checkpoints de su propia reserva.
Así no sobrescriben la tarea global del otro trabajador.

Restaurar un respaldo libera las reservas contenidas en él con una nueva revisión;
no reactiva permisos de trabajadores antiguos. Detén a los trabajadores antes de
restaurar, inspecciona el código (el respaldo de memoria no restaura código) y
adquiere reservas nuevas. Los respaldos originales permanecen intactos. Si el
reloj retrocede antes del último heartbeat, la reserva se conserva como
`clock_anomaly`: no se puede renovar hasta resolverlo, y su sesión puede liberarla.
La caducidad usa el reloj del coordinador; evita cambios de reloj durante el trabajo.

## Alcance comprobable

Este es un protocolo de cooperación, no un bloqueo del sistema operativo ni una
barrera de autenticación. Editores, scripts o IAs que lo ignoren pueden escribir
código. Las sesiones no se autentican por su etiqueta. Todos los clientes deben
respetar las reservas y consultar la misma raíz y reloj; copias o worktrees con
memorias separadas no se sincronizan automáticamente. No se garantizan bloqueos
entre máquinas con un sistema de archivos que no respete el bloqueo local.

Los solapamientos se deciden por rutas literales, no por análisis de todos los
símbolos del código. Se rechazan rutas ocultas, privadas, absolutas, con glob,
traversal, symlinks o archivos enlazados de varias maneras. Archivos aún no creados
pueden reservarse. Revisar cambios e integrar módulos sigue siendo trabajo del
coordinador. La prueba local con procesos concurrentes no demuestra una sesión
real con varios proveedores de IA; ese ensayo permanece pendiente.
