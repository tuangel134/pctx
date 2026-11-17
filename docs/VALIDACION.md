# Validación de PCTX 0.2.0

Fecha: 12 de septiembre de 2026. Entorno: Linux, Python 3.14, Chromium headless
mediante Playwright. No se usó un modelo ni una API de pago para estas pruebas.

## Resultados

- `python3 -m unittest discover -s tests -q`: **28 pruebas pasan**.
- `python3 benchmarks/clean_room.py`: **PASS**, paquete de tarea de aproximadamente
  750 tokens, dentro del presupuesto de 1 800, con restricciones, decisiones,
  comandos, arquitectura y tarea activa.
- `node tests/ui_smoke.cjs` con Playwright disponible: **16 recorridos pasan**,
  sin errores de JavaScript. Capturas en `validation/dashboard-desktop.png`,
  `validation/dashboard-mobile.png`, `validation/dashboard-architecture.png`.
- `python3 -m pip wheel --no-deps . --wheel-dir dist`: wheel generado.
- `python3 tests/wheel_smoke.py dist/pctx-0.2.0-py3-none-any.whl`: **PASS**.
  Instala en un venv nuevo, ejecuta CLI/MCP, construye zipapp, sirve los assets
  empaquetados del panel y comprueba el apagado.
- Instalación local: `~/.local/bin/pctx --version` devuelve **pctx 0.2.0**.
- `desktop-file-validate ~/.local/share/applications/pctx.desktop`: sin errores.

## Casos cubiertos

Inicialización con rutas que contienen espacios; comandos y evidencia relativos
de subproyectos; concurrencia de doce procesos conservando historial; readonly
sin modificaciones; errores JSON-RPC y validación de tipos; exportaciones con
presupuesto; exclusión de registros privados; corrupción de tareas sin pérdida
de datos; conservación de notas manuales; registros por ID; recuperación y cierre
con pendientes; Git antes del primer commit; exclusiones `.env` y `.pctxignore`;
rechazo de rutas redirigidas; seguimiento con archivos añadidos/cambiados/borrados;
MCP vigilando sin llamadas adicionales; HTTP sin autorización/origen permitido;
configuraciones fusionadas y respaldo; zipapp con Python aislado de site-packages.

La prueba del panel utiliza clics, formularios y el portapapeles real del
navegador. Incluye selector de carpeta, tarea, conocimiento con evidencia,
vigilancia, actualización, instalación de configuración, prueba de proceso MCP,
copia portable, instrucciones para Master, edición de arquitectura, handoff,
reanudación, diagnóstico, escritorio/móvil y apagado.

## Prueba adicional del MCP Master real

Durante la continuación programada se descubrió y usó el conector real de
Tessarion. Se consultaron permisos, workspaces y esquemas efectivos de herramientas.

- Ruta de host: `pctx --version` devuelve 0.2.0. Se inicializó una carpeta de
  prueba en `validation/master-bridge-Bj8hQg/`, se generó el zipapp y se ejecutaron
  contexto, registro con evidencia de `app.py`, checkpoint y handoff; todas las
  llamadas devolvieron código 0. Una llamada posterior de solo lectura recibió
  el hecho, el handoff y el siguiente paso conservados.
- Ruta aislada: `terminal_execute`, perfil `workspace-write`, ejecutó el zipapp
  dentro de una subcarpeta temporal del workspace autorizado. Leyó contexto,
  escribió un hecho y cerró la tarea con código 0. Esa carpeta de prueba se movió
  después a `validation/master-sandbox-J3uq40/`, conservando la evidencia sin
  dejar la prueba dentro del workspace ajeno al desarrollo de PCTX.
- Se comprobaron además los nombres y esquemas de las herramientas nativas
  `project_context_*`; la guía distingue sus campos camelCase de los del CLI.

No se almacenaron respuestas adjuntas de otras tareas, transcripciones ni tokens
del conector como evidencia de PCTX.

## Lo que estos resultados no demuestran

- Que un modelo dentro de ChatGPT web seleccione las herramientas del Master.
- Que el usuario haya conectado o autorizado ese Master en su cuenta.
- Que todos los IDEs interpreten una configuración igual en todas sus versiones.
- Que Windows/macOS y repositorios enormes funcionen igual que el entorno probado.
- Que el análisis estático comprenda toda la semántica de un proyecto.

La guía de integración indica la ruta local verificada y las condiciones del
cliente remoto. No se publicaron endpoints ni se modificó Tessarion para simular
una integración externa validada.
