# PCTX 0.7.1 — corrección del brief W7

En 0.7.0, pasar `--role` descartaba toda la tarea y el handoff globales y los
registros sin asignación de rol. Por eso un `task update --next-action/--blocker`
correcto podía desaparecer del brief. Es un fallo corregido en 0.7.1.

```bash
pctx --root /ruta/proyecto brief --budget 800 --role W7
```

El brief incluye el contexto compartido con `[global]`: objetivo de la tarea o
handoff, próximos pasos, bloqueos y archivos cambiados. Los registros sin rol
asignado son compartidos; IDs/etiquetas/scope W1, W3, etc. conservan el filtro
anterior. Un registro con `roles` explícitos solo corresponde a esos roles.
Las tareas con responsable no se consideran globales.

El objetivo y los pasos específicos de W7 tienen prioridad. Si no hay datos
asignados a W7, el brief avisa y mantiene `essential_complete=false` y
`role_matched=false`, aunque sí muestre contexto global útil. No inventa una
asignación. El encabezado y ese aviso participan en el presupuesto chars/4.
CLI, MCP y el panel usan las mismas reglas y la lectura no escribe checkpoints.

Para dar un próximo paso a W7 sin modificar la traza global del coordinador:

```bash
pctx --root /ruta/proyecto record --type next_action \
  --id microbastion.next_step --role W7 \
  --statement 'Validar las colisiones y registrar el resultado' --ttl 1d --quiet
```

El mismo `--id` actualiza el registro y conserva sus revisiones. No uses
`--replaces microbastion.next_step` para reemplazarlo por sí mismo.
`--replaces` sirve para un registro diferente que ya existe y es visible en la
misma raíz; puedes encontrar su ID con `pctx --root /ruta/proyecto search QUERY --json`.

```bash
pctx --root /ruta/proyecto record --type next_action \
  --id microbastion.next_step.v2 --role W7 \
  --statement 'Revisar el resultado de las colisiones' \
  --replaces microbastion.next_step --ttl 24h --quiet
```

Un destino inexistente, privado o de otra raíz no se crea ni publica mediante
reemplazo. El error indica cómo buscar y cómo actualizar el mismo ID, sin
revelar la existencia de registros privados.

`record --ttl` acepta segundos (`86400`) o una cantidad entera con `s`, `m`, `h`,
`d`, `w`: `30m`, `24h`, `1d`, `1w`. Guarda siempre un entero de segundos en JSON,
entre 1 y 31536000. MCP conserva `ttl_seconds` como entero. El TTL de las reservas
sigue siendo un entero de 60 a 3600 segundos.

Si editas REGLAS.md o CONTEXTO-CLAUDE.md después de adjuntarlos como evidencia,
`stale-evidence` es esperado: el hash anterior ya no prueba el contenido actual.
Revisa los registros y renueva su evidencia tras comprobar esos documentos.
El brief excluye afirmaciones desfasadas; conserva restricciones desfasadas con
`REVISAR VIGENCIA` y esenciales incompletos. Ese aviso no debe borrarse para
hacer desaparecer un diagnóstico correcto.

Últimos cambios distingue informes con su estado e incluye checkpoints o
`Registro actualizado [tipo/estado]` si no hay cambios de código registrados.
Una actualización de memoria no se presenta como código probado.

La instalación local se actualiza a 0.7.1. Para renovar una copia portable en
otro proyecto, ejecuta allí `pctx --root /ruta/proyecto portable`. Reinicia el
servidor MCP que estuviera abierto para cargar el código nuevo. No es necesario
recrear registros ni cambiar el esquema JSON.

Las demás funciones y límites siguen documentados en [USO_0.7.md](USO_0.7.md).
