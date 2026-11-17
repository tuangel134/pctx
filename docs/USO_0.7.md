# PCTX 0.7 — contexto vigente para trabajar y delegar

Los registros JSON siguen siendo canónicos; los índices y exports se reconstruyen.
Las lecturas comprueban vigencia y nunca ejecutan los comandos guardados.

## Reemplazar estados antiguos y hacerlos caducar

```bash
pctx record --id estado.pathfinding.v2 --type fact \
  --statement 'Pathfinding compila; T009 resuelta' \
  --replaces estado.pathfinding.v1 --ttl 86400 --quiet
```

La relación `replaces` se guarda atómicamente en el registro nuevo. El anterior
queda archivado lógicamente en contexto, búsqueda, panel y cola de revisión, sin
borrar su archivo ni historial. `pctx history --id estado.pathfinding.v1` permite
inspeccionarlo. Las sustituciones se conservan al editar y se rechazan ciclos,
targets privados, inexistentes o gestionados por otros ciclos de PCTX.
Para corregir una sustitución equivocada, registra un estado nuevo correcto o
restaura un respaldo; no se reactivan afirmaciones antiguas al editar una relación.

También puedes usar una clave estable en el mismo ámbito:

```bash
pctx record --claim-key pathfinding.estado --scope runtime \
  --statement 'Nuevo estado comprobado' --ttl 86400 --quiet
```

Otro ID nuevo con esa clave/ámbito reemplaza automáticamente al anterior. Dos
escritores se serializan: queda un solo estado vigente. Usa `--replaces` para
relacionar registros antiguos que aún no tienen clave. No se adivina una sustitución
por palabras parecidas ni se cambia la memoria de otros proyectos automáticamente.

`--ttl` fija segundos de validez desde la última actualización material; admite
1–31536000. `--expires-at '2026-10-25T18:00:00-06:00'` fija un vencimiento absoluto.
La fecha absoluta tiene prioridad si se especifican ambos. Un registro con
`stability=volatile` sin TTL explícito caduca a las 24 horas, incluidos registros
legacy. Los registros estables conservan su vigencia salvo cambios de evidencia.
Una lectura expone `state=stale`, `declared_state` y el motivo; no modifica archivos.
Un escaneo puede persistir esa obsolescencia. Repetir una escritura idéntica no
renueva la validez: verifica o actualiza el estado real.

El ranking coloca conocimiento vigente antes que el obsoleto y usa la recencia
como señal adicional de relevancia. Las restricciones esenciales se conservan con
avisos si su vigencia necesita revisión. Los snapshots de Git del escáner se
contrastan en vivo; una observación local idéntica no requiere generar timestamps
nuevos en cada llamada.

## Comprobaciones ejecutadas por PCTX

```bash
pctx record --id fact.estado --type fact \
  --statement 'La comprobación rápida pasa' \
  --check-command 'bash tools/estado_rapido.sh' --check-timeout 120 --quiet
pctx verify --id fact.estado
# Usa la revisión que devuelva la vista previa:
pctx verify --id fact.estado --run --expected-revision 1
```

El comando se guarda como `argv`, sin shell implícito, y se ejecuta desde la raíz
solo con `--run`. En MCP, `pctx_verify` muestra la vista previa y
`pctx_verify_run` exige `execute=true` y `expected_revision`. Leer contexto,
importar informes o consultar un registro nunca ejecuta sus instrucciones.

PCTX registra ID de ejecución, comando, fechas, duración, código de salida,
timeout y hash de hasta 64 KiB de salida. No persiste ni devuelve la salida cruda.
Reconoce conteos de unittest, pytest y líneas como `152/152`; si el texto afirma
un cociente, debe coincidir con el conteo observado para marcarlo verificado.
Es evidencia de lo que ejecutó ese comando, con su alcance y entorno; no una
auditoría independiente de todas las afirmaciones del registro.

Un fallo, timeout, comando no disponible, conteo incompatible, evidencia vieja o
cambio de fuentes durante la ejecución deja el registro `stale`. Una ejecución
correcta captura la identidad del workspace; cambios posteriores de fuentes
invalidan su vigencia aunque aún no se haya escaneado. Los archivos públicos
ocultos que Git sigue también participan. Excluye logs y artefactos generados
mediante `.pctxignore` para que no se confundan con fuentes. La comprobación no
mantiene el bloqueo PCTX mientras corre; puede llamar a herramientas PCTX sin
bloquear otros workers. Si el registro cambia mientras corre, el resultado no se
adjunta a una definición distinta. Una fecha absoluta vencida no se amplía al verificar.

`--quiet` también está disponible en `verify`; un resultado no verificado devuelve
código de salida 1. Las verificaciones no inflan contadores de revisión del checklist.

## Evidencia de Git

```bash
pctx record --id fact.rama --type fact --statement 'Estado válido en main' \
  --git-evidence main --ttl 86400 --quiet
# También admite main@HASH y la forma --evidence git:main@HASH.
pctx plan review --id plan.tarea --expected-revision 3 --outcome passed \
  --summary 'Criterios comprobados en esta rama' --reviewer W4 \
  --evidence git:main --covered-criteria criterion.ID
```

Se guarda la referencia y el commit completo. Cuando avanza, se borra o deja de
resolverse la referencia, el registro queda desfasado; una verificación del checklist
pasa a necesitar revisión. No se hace fetch ni se accede a la red. Cada registro
compara su propio commit, incluso si varios usan la misma rama. Sigue disponible
la evidencia por archivo; sus hashes se invalidan al cambiar su contenido.

## Brief para cada worker

```bash
pctx brief --budget 800
pctx brief --budget 800 --role W4
```

Siempre contiene objetivo, siguiente paso, restricciones, bloqueos y últimos
cambios. Filtra tareas/responsables, IDs, etiquetas y `--role W4` de los registros;
conserva restricciones globales. Un rol desconocido muestra ausencia de datos y
esenciales incompletos. No arrastra automáticamente la traza de otro trabajador.
Los checkpoints de reservas y los intentos importados permiten recuperar cambios.

El presupuesto cubre el texto completo del brief, incluidos títulos y avisos, con
la estimación chars/4. El JSON de `--json` o el sobre MCP añaden su propio coste.
Las omisiones son explícitas; un resumen incompleto requiere ampliar por ID o
consultar el plan. En el panel está en **Contexto → Generar brief para worker**,
con rol, presupuesto y botón de copiar. La consulta no crea una tarea global.

## Informes de workers como parte de la memoria

```bash
pctx import-reports --glob '**/HECHO-*.md' --path INTEGRACION-LOG.md
pctx import-reports --path .delegacion/HECHO-W4.md --role W4 --quiet
pctx report --path .delegacion/HECHO-W4.md --role W4 \
  --text '# Runtime
Implementado el adaptador; falta probar en dispositivo.'
pctx report --path .delegacion/INTEGRACION-LOG.md --append --role W4 \
  --text 'Runtime integrado; falta validación física.'
```

La importación por defecto busca HECHO-*.md e INTEGRACION-LOG.md. Cada sección
conserva un ID por origen y encabezado, evidencia de sección y rol. Los encabezados
W3/W4 del log compartido mantienen sus respectivos roles; añadir una entrada no
reasigna las anteriores. Reimportar sin cambios no duplica ni añade revisiones.
Editar una sección actualiza el mismo ID; añadir otras no invalida las anteriores.
Las entradas quedan `inferred`, de tipo `attempt` o `issue`; decir “152/152” en
un informe no demuestra que PCTX ejecutó la batería. Los bloques de comandos
no se convierten en checks. Se rechazan transcripciones y patrones de secretos.

La API `report` puede escribir esos documentos sin reserva de código. El nombre
está limitado a HECHO-*.md o INTEGRACION-LOG.md. Sobrescribir requiere el hash
actual mediante `--expected-hash`; `--append` se serializa y evita repetir un
bloque idéntico. No autoriza escribir archivos de código. Límites: 256 KiB por
informe, 128 secciones por archivo y 1000 secciones/200 archivos por lote; la salida
muestra a lo sumo 100 IDs y declara truncamiento.

## Reservas recuperables y menos ruido

Las rutas literales seguras como `.delegacion` se aceptan al reservar. Se siguen
rechazando traversal, credenciales, `.git`, `.project-context` y alias por enlaces.
Un ID abreviado como T009 se resuelve solo si corresponde a una única tarea;
si falta o es ambiguo, el error identifica el proyecto y recomienda consultar
`plan list` con la misma raíz. No se crea una tarea incorrecta por aproximación.

Las adquisiciones limpian las reservas vencidas con una revisión que conserva su
checkpoint. `pctx coordinate cleanup` permite hacerlo explícitamente. Las lecturas
siguen sin escribir. Un trabajador vencido debe parar y volver a adquirir. Una
liberación tardía no toca la reserva del sucesor; informa que no guardó el resumen
tardío, que puede entregarse como informe. Todos los workers deben usar PCTX 0.7
y compartir la raíz canónica; actualiza los zipapps con `pctx portable`.

```bash
pctx record --statement 'Avance breve' --quiet
pctx call pctx_record_update --allow-write --quiet \
  --args '{"type":"fact","statement":"Avance breve","quiet":true}'
pctx export --policy manual
# Tras agrupar cambios, genera bajo demanda:
pctx export
pctx adapters sync
# Para volver al comportamiento automático:
pctx export --policy auto
```

`quiet` evita la salida normal; los errores conservan el código de salida.
MCP `pctx_record_update quiet=true` devuelve solo ID, estado y revisión. El modo
manual es por proyecto y evita que escrituras, reservas o refresh regeneren
PROJECT_CONTEXT.md y los adaptadores instalados. Las consultas en vivo siguen
leyendo JSON actual. Los generados pueden quedar como fotografías anteriores
hasta el próximo export explícito. El modo automático se conserva por compatibilidad;
con datos iguales, exportar o pedir contexto repetidamente conserva bytes y mtime.
Los archivos manuales fuera de bloques gestionados se conservan.
