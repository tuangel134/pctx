# Metas, checklists y reparto por dificultad — PCTX 0.5

Cada meta, tarea, bug o comprobación tiene ID estable, padre, descripción,
prioridad, responsable, dependencias y criterios de aceptación. Se conserva como
extensión `checklist` de un registro JSON canónico de tipo `note`, esquema 1,
en `.project-context/records/plan.*.json`. No requiere otra base de datos.
Los enlaces `supports` y `depends_on` participan en el grafo existente.
Los registros no se borran al terminar: se cancelan con motivo o se reabren.

## Estado y revisiones

Estados: pendiente, en curso, hecho, por revisar, bloqueado, verificado y cancelado.
La casilla marca hecho o vuelve a pendiente. No afirma que se ejecutaron pruebas.
Un padre no se puede cerrar con hijos pendientes; una dependencia cancelada no
cuenta como satisfecha. La jerarquía admite ocho niveles de subpuntos y rechaza ciclos también
cuando combinan padres con dependencias.

Solo registrar una revisión aumenta `review_count`. Cada revisión conserva fecha,
revisor declarado, resultado (pasó/falló/bloqueada/no concluyente), resumen,
criterios comprobados y rutas/hash SHA-256 de archivos de evidencia. El historial
canónico conserva todas las revisiones; el registro actual mantiene solo contador
y última revisión. Consultar, editar o marcar hecho no suma revisiones.
No se copian contenidos de evidencia ni conversaciones. No se aceptan pruebas
mediante rutas privadas/ocultas, credenciales, claves, symlinks o fuera del proyecto.

Verificar exige al menos un criterio, última revisión aprobada que cubra todos
los criterios, evidencia disponible con hash vigente, definición actual y revisiones
vigentes de hijos/dependencias. Estos también deben estar verificados (hijos
cancelados se excluyen). Editar la definición o reabrir el trabajo invalida su
revisión anterior, incluso si luego se revierte el título. Cambiar responsable
no altera la revisión propia; una revisión de padre ligada a la revisión del hijo
puede necesitar actualización. Cambios de evidencia o requisitos relacionados se detectan
al consultar, antes de escanear: `declared_status` conserva la declaración y `status`
expone `needs_review`. Doctor avisa de verificaciones obsoletas.

PCTX comprueba integridad, cobertura declarada y vigencia de archivos. Quien
registra una revisión debe haberla realizado: un hash no demuestra que un test se
ejecutó ni garantiza independencia o calidad del revisor. No se inventan bugs,
revisiones ni migraciones de tareas antiguas.

## Dificultad y riesgo

La dificultad se clasifica explícitamente y exige una razón. Estas orientaciones
son relativas al proyecto; no equivalen a una garantía sobre ningún modelo:

| Etiqueta | Valor CLI/MCP | Orientación |
| --- | --- | --- |
| Sin clasificar | `unknown` | No hay información suficiente; valor inicial. |
| Fácil | `easy` | Cambio pequeño, aislado y comprobación clara. |
| Medio | `medium` | Varios pasos conocidos dentro de un componente. |
| Intermedio | `intermediate` | Coordinación entre componentes o integración. |
| Difícil | `hard` | Diseño, migraciones o incertidumbre considerable. |
| Súper difícil | `very_hard` | Problema amplio, novedoso o con muchas restricciones. |

Riesgo independiente: sin clasificar, bajo, medio y alto. Un cambio fácil de
seguridad o datos puede tener riesgo alto y requerir un revisor especializado.
Los hijos no heredan la dificultad de la zona padre: se clasifican según su propio alcance.
No se seleccionan proveedores, precios o modelos, ni se contratan servicios.
Puedes entregar la lista fácil a una IA económica y reservar otras dificultades
para otra IA, manteniendo la misma carpeta e identidad del proyecto.

`ready: true` exige punto hoja pendiente/por revisar, sin responsable y con
dependencias hechas o verificadas. Excluye padres, trabajo bloqueado/cancelado,
hecho/verificado y trabajo en curso o ya asignado. Antes de comenzar, lee detalle,
asigna `owner` y cambia a `in_progress` con revisión esperada. La escritura atómica
protegida por `expected_revision` evita que dos sesiones pisen el mismo punto.
No permite descubrir automáticamente qué IA es capaz de cumplir los criterios.

## CLI y MCP

```bash
pctx plan create --id plan.meta --kind goal --title 'Completar el módulo' \
  --criteria 'Todos los subpuntos comprobados'
pctx plan create --id plan.prueba --parent plan.meta --kind check \
  --title 'Comprobar el caso básico' --criteria 'Resultado esperado observado' \
  --difficulty easy --difficulty-reason 'Un caso aislado y reproducible' --risk low
pctx plan summary --budget 1500
pctx plan list --difficulty easy --ready --budget 2000
pctx plan list --goal plan.meta --status needs_review
pctx plan list --parent plan.meta --offset 0 --limit 20
pctx plan detail --id plan.prueba --budget 3000
pctx plan edit --id plan.prueba --expected-revision 1 --owner 'sesion-A'
pctx plan status --id plan.prueba --expected-revision 2 --status in_progress
```

Consulta la revisión actual antes de **cada** cambio. Para liberar un responsable:
`--owner ''`. Para quitar un padre usa `plan edit --parent root`. Crea un nuevo
ID solo para un punto distinto. Los IDs ya existentes no se recrean silenciosamente.
`--criteria`, `--dependencies`, `--evidence` y `--covered-criteria` se pueden repetir;
al editar se reemplaza la lista indicada. MCP admite listas vacías explícitas
para borrar criterios/dependencias. No sobrescribas registros `plan.*` mediante
`record`, corrección genérica o restauración de una revisión: usa las acciones
específicas que preservan el contador. El respaldo/restore de memoria completa
conserva JSON e historial.

Para registrar una revisión **realizada**, usa los IDs de criterio del detalle:

```bash
pctx plan review --id plan.prueba --expected-revision 3 \
  --outcome passed --summary 'Qué se ejecutó y qué se observó' \
  --reviewer 'sesion-A' --evidence validation/resultado.json \
  --covered-criteria criterion.ID --event-id comprobacion-001
pctx plan status --id plan.prueba --expected-revision 4 --status verified
pctx plan history --id plan.prueba --offset 0 --limit 10 --budget 3000
```

Reutiliza el mismo `event_id` y el mismo contenido al reintentar una revisión tras
un fallo de conexión. Se devuelve `already_recorded` sin duplicar el contador,
incluso después de revisiones posteriores. Otro resultado con ese ID se rechaza.
Crear y editar también exigen inspección tras respuestas inciertas; no prometen
reintentos automáticos. La generación de Markdown puede recuperarse con `scan`
si se interrumpe el proceso después del commit JSON.

`pctx_plan` es de solo lectura (`summary`, `list`, `detail`, `history`), también en
conexiones habilitadas para escribir. `pctx_plan_update` permite `create`, `edit`,
`status`, `review` solo con escritura explícitamente habilitada. Los parámetros
coinciden con los nombres CLI usando guiones bajos.

## Panel, continuidad y tokens

Abre **Metas y checklists**: filtros, páginas, casillas, progreso directo de hijos,
detalle/criterios, formulario de edición, estado, revisiones e historial paginado.
Para subir/bajar en la jerarquía usa padre/meta o “Ver subpuntos”; “Nuevo punto”
crea otro elemento. Errores de revisión esperada conservan el formulario: consulta
el detalle actual antes de reintentar. La actualización automática no pisa borradores.

El contexto por tarea y `TASKS.md` incluyen una vista breve con metas y hojas abiertas,
IDs, dificultad, riesgo, disponibilidad y revisiones. No incorporan todo el historial.
Las restricciones esenciales tienen prioridad; si la vista breve no cabe, se declara
su omisión y se indica cómo consultarla. `PROJECT_CONTEXT.md` contiene el árbol portable
completo con casillas y criterios, sin historiales completos.

Las consultas de plan limitan **todo el JSON visible**, metadatos incluidos, mediante
caracteres/4. No son tokens exactos de un proveedor, ni incluyen esquemas/transporte
MCP. Si una página está truncada sigue `next_offset`; si no avanza o falta `detail`,
aumenta `budget`. La búsqueda existente también indexa descripción, motivo y criterios actuales del
checklist, sin su historial: permite recuperar documentos y fragmentos sin cargarlos todos. Los índices/vectores siguen siendo reconstruibles.

Los ejemplos son ilustrativos. No afirman verificaciones reales de otros proyectos
ni integración probada entre clientes externos.
