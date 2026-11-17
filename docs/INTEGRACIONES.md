# Integración con asistentes, IDEs y MCP Master

PCTX ofrece tres caminos: MCP local para clientes con herramientas, comandos
finitos para un terminal conectado por MCP Master, y archivos Markdown para
cualquier asistente que pueda leerlos. La misma carpeta es la memoria compartida.

## MCP local

Desde el panel, selecciona **Conectar una IA**, el cliente y **Instalar en este
proyecto**. Se añade el servidor `pctx` conservando otros servidores y las reglas
manuales. Si cambia una configuración existente se guarda su versión anterior
en `.project-context/.private/backups/`; cada cliente mantiene una copia anterior.

Equivalente por terminal:

```bash
pctx --root /ruta/al/proyecto integrate --client vscode --write
pctx --root /ruta/al/proyecto integrate --client cursor --write
pctx --root /ruta/al/proyecto integrate --client claude-code --write
pctx --root /ruta/al/proyecto integrate --client generic
```

`--read-only` prepara una conexión que no modifica la memoria. Sin esa opción,
el servidor se inicia con `--allow-write --watch`: permite actualizaciones y
detecta cambios mientras el cliente mantenga el proceso abierto.

| Cliente | Archivo generado | Contenedor |
| --- | --- | --- |
| VS Code | `.vscode/mcp.json` | `servers`, transporte `stdio` |
| Cursor | `.cursor/mcp.json` | `mcpServers` |
| Claude Code | `.mcp.json` | `mcpServers` |
| Otro | Bloque para copiar, sin modificación automática | `mcpServers` |

El comando generado apunta al intérprete y al lanzador reales, con argumentos
separados; funciona aunque las rutas contengan espacios y el IDE no encuentre
`pctx` en PATH. Regenera la configuración si cambias de equipo o mueves el proyecto.

**Comprobar MCP local** inicia un proceso de prueba, realiza `initialize` y
`tools/list`, y lo termina. Esto comprueba PCTX, no demuestra que un cliente
externo haya activado el servidor ni que un modelo elija sus herramientas.

La forma de gestionar servidores en VS Code está en su
[referencia oficial](https://code.visualstudio.com/docs/agents/reference/mcp-configuration).
Las configuraciones se validan localmente; las interfaces y permisos propios de
otros productos deben revisarse en el cliente usado.

## Ciclo de herramientas

1. `pctx_context`: carga memoria para la tarea; en escritura deja la tarea
   registrada y actualiza hechos derivados.
2. `pctx_task_update`: conserva avances, pendientes, bloqueos y archivos cambiados.
3. `pctx_record_update`: registra conocimiento con evidencia; usa un `id` estable
   si estás revisando el mismo hecho. Los registros quedan como inferidos.
4. `pctx_architecture_update`: registra conexiones que no se deducen estáticamente.
5. `pctx_finish`: refresca memoria, guarda handoff y cierra la sesión.
6. `pctx_task_resume`: recupera una tarea no terminada por ID o la más reciente.

Lecturas adicionales: `pctx_search`, `pctx_status`. Escrituras auxiliares:
`pctx_refresh`, `pctx_handoff_save`.

Recursos disponibles: `pctx://project/context`, `pctx://project/architecture` y
`pctx://project/tasks`. Prompt: `pctx_workflow`, con argumento `task`.

PCTX publica instrucciones y reglas para sugerir este ciclo. No puede obligar a
un modelo externo a llamar herramientas ni atravesar permisos del cliente.

## ChatGPT web mediante MCP Master de Tessarion

El código local inspeccionado en Tessarion MasterMCP Lite expone:

- `forja_list_workspaces`: proyectos autorizados.
- `forja_list_workspace_tools`: herramientas disponibles para un `workspaceId`.
- `forja_call_workspace_tool`: invoca una herramienta con `workspaceId`, `tool`
  y `arguments`.

La herramienta de terminal y su esquema se deben descubrir con la segunda
llamada. `terminal_execute` puede estar aislado al workspace; el terminal de host
es una capacidad separada. No supongas que el Python o PCTX del host es accesible
desde el terminal aislado.

El catálogo real consultado también ofrece `project_context_bootstrap`,
`project_context_task_update`, `project_context_record`,
`project_context_architecture_update` y `project_context_finish`: son las
herramientas de memoria nativa de Tessarion. Si el workspace corresponde al
proyecto que quieres trabajar, puedes pedir que use directamente ese ciclo.
`bootstrap` es lectura: la tarea se registra mediante `task_update` antes de
editar. Sus campos se llaman `nextActions` y `changedFiles`; no copies sin
adaptar los nombres `next_actions` y `changed_files` del CLI independiente.
Escoge un solo motor escritor por carpeta. El gateway puede adjuntar contexto de
su workspace a todas las respuestas; si operas en otra raíz con terminal de host,
no confundas ese contexto adjunto con el del proyecto elegido.

Para ese caso, en el panel pulsa **Preparar PCTX portable para MCP Master** y
después **Copiar instrucciones para la IA**. Esto construye
`.project-context/.runtime/pctx.pyz`: una copia del programa dentro del proyecto.
Solo requiere que el entorno de ejecución tenga Python 3.10 o posterior. No
necesita instalar paquetes ni acceder al directorio donde desarrollamos PCTX.

La copia portable tiene la versión existente al generarla. Vuelve a prepararla
tras actualizar PCTX. Si el sandbox monta el proyecto en otra ruta, ChatGPT debe
usar la ruta que ve dentro de ese entorno.

Ejemplo de instrucciones que puedes darle a ChatGPT:

> Usa PCTX como memoria persistente del proyecto. Descubre el workspace y las
> herramientas disponibles del MCP Master. Si aparecen herramientas pctx_*,
> carga pctx_context antes de editar, guarda checkpoints y termina con pctx_finish.
> Si solo hay terminal, ejecuta PCTX portable mediante comandos finitos. Conserva
> decisiones y hechos con evidencia, tareas y pendientes; no guardes el chat.
> Antes de cerrar, actualiza la memoria y comprueba que se haya guardado.

Comandos finitos desde el terminal del proyecto:

```bash
python3 .project-context/.runtime/pctx.pyz --root . context --task "Corregir el login" --budget 8000
python3 .project-context/.runtime/pctx.pyz --root . task update --next-action "Ejecutar pruebas de acceso"
python3 .project-context/.runtime/pctx.pyz --root . call pctx_record_update --allow-write --args '{"id":"decision.auth","type":"decision","statement":"La sesión usa cookies HttpOnly","evidence":["src/auth.py"]}'
python3 .project-context/.runtime/pctx.pyz --root . call pctx_finish --allow-write --args '{"objective":"Login corregido","next_actions":["Validar en staging"],"blockers":[]}'
```

No lances `mcp serve` dentro de una herramienta de terminal que espera un comando
finito: ese servidor espera mensajes por entrada estándar. Usa `call`, `context`
y `task`, que terminan y devuelven resultados.

La conexión entre ChatGPT web y MCP Master debe existir previamente. La
[documentación oficial de OpenAI](https://developers.openai.com/plugins/deploy/connect-chatgpt)
describe conexiones mediante endpoint HTTPS o Secure MCP Tunnel, con disponibilidad
dependiente de cuenta y políticas. El panel HTTP de PCTX es una interfaz local;
no es ese endpoint MCP. No se ha publicado ningún servidor ni abierto un túnel
como parte de esta implementación.

El 12 de septiembre de 2026 se probó el gateway real de Tessarion: mediante
`host_terminal_execute` se ejecutaron contexto, registro con evidencia,
checkpoint, cierre y lectura posterior de la memoria en una carpeta de prueba.
También se ejecutó el zipapp con `terminal_execute` bajo el perfil
`workspace-write`, leyendo contexto, guardando un registro y cerrando la tarea.
Todas esas llamadas terminaron con código 0. La selección automática de esas
herramientas desde una conversación en ChatGPT web sigue siendo una comprobación
distinta de este ensayo del gateway desde Codex.

## Clientes sin MCP

```bash
pctx --root /ruta/al/proyecto adapters sync --targets agents,claude,gemini,copilot,cursor,windsurf,cline,aider
```

Esto crea bloques administrados en los archivos propios de cada herramienta.
Cursor recibe una regla `alwaysApply`. Si `.clinerules` ya es una carpeta, PCTX
crea su regla dentro y no intenta reemplazar la carpeta.

Si una IA puede leer y ejecutar comandos, puede mantener PCTX con la CLI. Si
solo puede leer, podrá comprender la exportación que le adjuntes, pero no guardar
actualizaciones por sí sola. «Compatible» significa ofrecer una vía de acceso
que el cliente soporte, no afirmar que cualquier IA dispone de esas capacidades.

## Diagnóstico local y herramientas 0.3

`pctx --root /ruta/al/proyecto diagnose` inicia un proceso finito de la versión
actual, realiza initialize/listado/llamada de estado, verifica identidad y comprueba
que una escritura se rechaza en modo lectura. `--write-mode` verifica el catálogo
escribible mediante llamadas de lectura; no inventa una sesión de un IDE. El proceso
se cierra y un timeout o ejecutable fallido devuelve `ok: false` y salida no cero.
El diagnóstico portable vuelve a invocar su propio zipapp aislado.

Lecturas nuevas: `pctx_read`, `pctx_context_report`, `pctx_history`,
`pctx_review_queue`, `pctx_differences`. En conexiones escribibles siguen siendo
lecturas y no regeneran adaptadores. Escrituras nuevas: `pctx_record_restore` y
`pctx_record_review` (corregir/sustituir, con revisión esperada). Confirmar como
humano se reserva para CLI/panel. `claim_key` permite agrupar candidatos a conflicto;
no prueba por sí sola cuál afirmación es cierta. Respaldos y migraciones se ejecutan
desde CLI/panel, con previsualización para sustituciones.


## Recuperación selectiva 0.4

Después de `pctx_context`, usa `pctx_lookup` para buscar solo lo que falta,
`pctx_expand` para un fragmento vigente y `pctx_neighbors` para conexiones.
`pctx_index` requiere escritura y reconstruye el índice local; un modelo opcional
se indica por carpeta existente, sin descarga automática. Las tres lecturas no
actualizan tareas, archivos ni adaptadores. Vocabulario, cobertura, presupuestos,
modelo evaluado y ejemplos: [recuperación 0.4](RECUPERACION_0.4.md).
Estas herramientas se validaron localmente; la conexión y el uso efectivo por
clientes externos deben comprobarse en esos clientes.
