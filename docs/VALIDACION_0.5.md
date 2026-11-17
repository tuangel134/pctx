# Validación local PCTX 0.5.0 — 11 de octubre de 2026

Metas/checklists y clasificación del trabajo están implementados en CLI, MCP y
panel local. Los JSON e historiales siguen siendo canónicos; índices y vectores
siguen siendo reconstruibles. La entrega anterior y el respaldo inicial se conservan.
Evidencia inmutable: `validation/release-0.5.json`. Cierre local:
`validation/final-0.5.json`. Uso y límites: [checklists](CHECKLISTS_0.5.md).

## Comprobaciones

- 120 pruebas unitarias/integración pasan: 92 anteriores y 28 nuevas del checklist.
- Metas/subtareas/bugs, dependencias, ciclos combinados, niveles de jerarquía,
  padre con pendientes y dependencia cancelada que no satisface un requisito.
- Hecho separado de verificado; criterios completos, evidencia vigente, cambios,
  borrado, symlinks, reapertura y edición/reversión que invalidan comprobaciones.
- Contador incrementado exclusivamente por revisiones registradas; resultados
  fallidos/bloqueados/no concluyentes conservados en historial; reintentos idempotentes
  aun después de otros eventos; un ID repetido con otro resultado se rechaza.
- Dificultad explícita en cinco niveles más sin clasificar, motivo obligatorio,
  riesgo independiente y filtros que excluyen trabajo asignado/en curso o padres.
- Escritores simultáneos en hilos **y procesos**: solo uno puede asignar la revisión
  disponible; rechazo del segundo sin sobrescritura. Lecturas MCP no escriben.
- Privacidad, claves/rutas inseguras, IDs reservados, corrupción del contador con
  historial rehasheado y roundtrip de respaldo que conserva dificultad y revisiones.
- Una cadena de 1100 dependencias se consulta sin recursión de Python ni desbordamiento.
- Cobertura parcial de criterios visible sin permitir verificación completa prematura.
- JSON completo acotado, detalle omitido explícitamente si no cabe, historial largo
  paginado, contexto con esenciales primero y omisión visible del resumen del plan.
- Descripción y criterios actuales recuperables por búsqueda progresiva;
  referencias antiguas invalidadas y texto anterior ausente de resultados.
- 47 recorridos Chromium pasan sin errores JavaScript: los 34 anteriores y 13 nuevos
  de creación, dificultad/riesgo, disponibilidad, casillas, rechazo de cierre,
  revisión fallida/aprobada, verificación, historial, edición, texto seguro y móvil.
  Capturas `validation/checklists-*-0.5.png` revisadas; sin desbordamiento horizontal.
- Wheel en venv limpio sin extras semánticos y zipapp con Python `-I`: CLI, MCP,
  herramientas de plan, otros flujos anteriores, recursos del panel y apagado pasan.
- Instalación local 0.5.0; los 34 módulos/recursos coinciden byte por byte en wheel
  y zipapp con la fuente validada. Modelo semántico opcional permanece fuera del paquete.
- Clean-room pasa, once escenarios de recuperación pasan y la regresión incremental
  sigue siendo equivalente al análisis completo. Diagnósticos MCP locales de lectura
  y escritura verifican identidad/versión/permisos y cierre del proceso.
- Fixture de conocimiento conserva 7/10 respuestas léxicas con 6007 tokens estimados
  y 10/10 híbridas locales con 7727; no cambió frente a 0.4. No demuestra ahorro
  universal ni capacidad real de modelos externos. Estimación caracteres/4.

## Reproducir

```bash
python3 -m unittest discover -s tests -v
python3 benchmarks/clean_room.py
python3 benchmarks/recovery.py --output validation/recovery-candidate-0.5.json --assert-pass
python3 benchmarks/incremental.py --output validation/incremental-candidate-0.5.json
python3 benchmarks/knowledge.py --mode lexical --output validation/knowledge-lexical-0.5.json
python3 benchmarks/knowledge.py --mode hybrid \
  --model ~/.cache/pctx/models/multilingual-minilm-qint8 \
  --output validation/knowledge-hybrid-0.5.json
NODE_PATH=/ruta/node_modules node tests/ui_smoke.cjs
python3 -m pip wheel --no-deps . --wheel-dir dist
python3 tests/wheel_smoke.py dist/pctx-0.5.0-py3-none-any.whl
```

No sobrescribas el manifiesto `release-0.5.json` después de cambiar fuente o pruebas.
Genera una nueva revisión de entrega y actualiza sus evidencias explícitamente.

## Artefactos y límites

Wheel `dist/pctx-0.5.0-py3-none-any.whl`, SHA-256
`928f69d6a89254ac441acb6666349cf5564870f31ec6b17a5cb14154198fba8e`.
Zipapp `.project-context/.runtime/pctx.pyz`; instalación `~/.local/bin/pctx`.
Respaldo anterior completo:
`~/pctx-backups/pctx-before-0.5-20261011T203751Z.tar.gz`, SHA-256
`86eabb32d5bf343ef53f41d3333f15693317c1ac0d64c3bfcfdb8f37f5ed2345`.

El checklist de este proyecto registra comprobaciones reales y conserva pendientes
para sesiones externas. No se importaron tareas antiguas como verificadas ni se
inventaron bugs o auditorías. Los revisores son declarados: los tests locales no
constituyen una revisión humana independiente ni pruebas ejecutadas por otra IA.

Clientes IDE/chat externos, cambio efectivo entre modelos y Windows/macOS siguen
pendientes de comprobación. La dificultad guía asignación manual; no garantiza
capacidad por precio. No se publicaron cambios ni se modificaron otros proyectos.
