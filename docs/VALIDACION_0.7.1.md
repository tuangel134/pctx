# Validación local — PCTX 0.7.1

Corrección del informe W7, 24 de octubre de 2026. Evidencia congelada en
`validation/release-0.7.1.json`; cierre en `validation/final-0.7.1.json`.

- La misma fixture JSON reproduce el fallo usando el wheel archivado 0.7.0:
  objetivo, próximo paso, bloqueo y registro next_action desaparecen con W7.
  Con 0.7.1 aparecen los cuatro datos, marcados como globales. La comparación
  se guarda en `validation/reproduction-0.7.1.json`; no usa datos de otro proyecto.
- Pasan 194 pruebas unittest: las 186 anteriores y ocho regresiones sobre tarea
  global, registros sin rol, prioridad de W7, exclusión de W3, roles explícitos,
  handoff vigente/desfasado, presupuestos y lecturas CLI/MCP sin escrituras.
- El caso de REGLAS.md y CONTEXTO-CLAUDE.md editados mantiene tres advertencias
  stale-evidence, muestra la tarea vigente y marca restricciones desfasadas.
  No confirma evidencia cambiada para hacer desaparecer avisos correctos.
- `--ttl 1d`, 24h, 30m, segundos y semanas se guardan como segundos; formato,
  cero y duraciones fuera del límite se rechazan sin modificar registros.
- Un reemplazo al mismo ID explica cómo actualizarlo conservando historial.
  Un destino privado e inexistente dan el mismo diagnóstico accionable; no se
  filtra existencia privada ni se crea un destino ausente.
- Pasan 58 recorridos Chromium sin errores JavaScript, incluido W7 con objetivo
  y siguiente paso globales, aviso de falta de asignación y traza sin cambios.
- Wheel limpio y zipapp aislado prueban el brief W7 y `--ttl 1d`, además de los
  flujos previos CLI/MCP/panel. Los 41 módulos y recursos coinciden con las fuentes.
- Pasan once escenarios de recuperación. No se cambia el motor de embeddings ni
  el ranking; los benchmarks históricos 0.7 se conservan como evidencia histórica.
- PCTX ejecuta la suite mediante un check explícito de 194/194. Se conservan
  conteos observados y hash acotado; el registro depende del snapshot de fuentes.

```bash
python3 -m unittest discover -s tests -v
NODE_PATH=/ruta/node_modules node tests/ui_smoke.cjs
python3 -m pip wheel --no-deps . --wheel-dir dist
python3 tests/wheel_smoke.py dist/pctx-0.7.1-py3-none-any.whl
python3 benchmarks/recovery.py --output validation/recovery-0.7.1.json --assert-pass
pctx verify --id fact.pctx071.executed-battery
```

Respaldo previo: `validation/pre-change-0.7.1.json`. La instalación editable
local conserva extras semánticos y actualiza sus metadatos a 0.7.1. La copia
portable del propio PCTX se reconstruye; las copias de otros proyectos requieren
su propio `pctx --root /ruta/proyecto portable` y reinicio del MCP abierto.

La validación es local en Linux. El parche no recrea registros de Microbastión,
no modifica sus documentos y no valida sesiones entre proveedores externos.
Véase [USO_0.7.1.md](USO_0.7.1.md) para las reglas de contexto global y roles.
