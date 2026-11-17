# Validación local — PCTX 0.6.0

Entrega de coordinación cooperativa sobre una raíz compartida. La evidencia
local se guarda en `validation/release-0.6.json`; el cierre en `validation/final-0.6.json`.

- 141 pruebas unittest pasan, incluidas 20 de coordinación. Dos procesos Python
  reales compiten por la misma ruta: solo uno gana. Una carrera entre renovaciones
  también tiene un solo ganador con la revisión esperada.
- Solapamiento exacto, carpetas/descendientes, mayúsculas conservadoras, metas/hijos,
  rutas hermanas, responsables, dependencias y tareas cerradas comprobados.
- Renovación, duración conservada, liberación con traspaso, vencimiento sin
  escritura y rechazo del trabajador anterior tras una nueva reserva comprobados.
- Retroceso de reloj antes del último heartbeat retiene la reserva; se rechaza
  renovar y se permite liberar explícitamente. No se promete sincronización
  entre relojes o sistemas de archivos de equipos distintos.
- Respaldar y restaurar libera reservas antiguas con historial y conserva el
  archivo original. Corrupción del ciclo de vida con hashes recalculados se detecta.
- Privacidad y alias inseguros rechazados; APIs genéricas no sobrescriben reservas.
- Reservar/renovar/liberar no sobrescribe la tarea global del coordinador,
  no suma revisiones de checklist ni invalida evidencias por un heartbeat.
  Una renovación vacía conserva el último checkpoint útil. El índice de búsqueda
  conserva su fingerprint y estado fresco durante renovaciones.
- Lecturas MCP sin escritura, consultas con presupuesto de JSON completo,
  paginación de historial, contexto acotado y consulta compartida CLI/MCP pasan.
- 55 recorridos Chromium pasan sin errores JavaScript: 47 anteriores y ocho
  recorridos de reserva, ocupación visible, identidad equivocada, conflicto,
  checkpoint, historial/texto seguro, móvil y liberación. Capturas de coordinación
  escritorio/móvil revisadas; sin desbordamiento horizontal.
- Wheel en venv limpio y zipapp con Python `-I` pasan: adquisición desde portable,
  consulta MCP desde wheel, liberación, flujos anteriores, recursos UI y apagado.
- Once escenarios de recuperación pasan; análisis incremental equivalente a
  completo; clean-room pasa. Fixture de búsqueda sin regresión: léxico 7/10
  y 6007 tokens aproximados; híbrido local 10/10 y 7727. Son mediciones sintéticas,
  no ahorro universal ni prueba de una sesión real entre proveedores.
- Instalación local 0.6.0, diagnósticos MCP de lectura/escritura y recursos del
  wheel/zipapp comparados con la fuente. Extras ONNX existentes preservados.

Comandos principales:

```bash
python3 -m unittest discover -s tests -v
NODE_PATH=/ruta/node_modules node tests/ui_smoke.cjs
python3 -m pip wheel --no-deps . --wheel-dir dist
python3 tests/wheel_smoke.py dist/pctx-0.6.0-py3-none-any.whl
python3 benchmarks/recovery.py --output validation/recovery-0.6.json --assert-pass
python3 benchmarks/incremental.py --output validation/incremental-0.6.json
python3 benchmarks/clean_room.py
```

Se conserva `~/pctx-backups/pctx-before-coordination-20261012T054340Z.tar.gz`
como respaldo anterior a los cambios, además de las entregas 0.3/0.4/0.5.
No se inicializó Git ni se publicaron cambios ni se modificaron otros proyectos.
Las sesiones reales entre varios clientes/modelos, equipos distintos y
Windows/macOS siguen pendientes. Las reservas requieren cooperación; no bloquean
ediciones externas ni autentican al trabajador. Uso: [COORDINACION_0.6.md](COORDINACION_0.6.md).
