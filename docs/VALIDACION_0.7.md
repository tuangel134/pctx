# Validación local — PCTX 0.7.0

Entrega del 24 de octubre de 2026. Evidencia congelada en
`validation/release-0.7.json`; cierre operativo en `validation/final-0.7.json`.

- 186 pruebas unittest pasan: 141 previas y 45 escenarios nuevos de memoria vigente,
  checks, Git, brief, informes, reservas y silencio. Un test previo de candidatos
  se adapta al archivado automático de una clave de estado; el historial se conserva.
- Reproducción de una nota verificada de hace trece días: lo volátil se expone
  como obsoleto en vivo y el estado reciente se prioriza. Reemplazos explícitos,
  cadenas, claves concurrentes, ciclos, privacidad y lecturas sin escritura pasan.
  Doctor conserva la evidencia histórica archivada sin pedir revisarla como fuente actual.
- Check configurado sin ejecutar permanece sin verificación automática. Ejecución
  explícita: pass/fail/timeout/comando inexistente, salida grande/secretos, cambios
  concurrentes de registro/fuentes y conteos incompatibles se comprueban.
  Un comando puede llamar a PCTX sin quedar bloqueado por el coordinador.
- Una comprobación real de esta entrega se ejecuta con `pctx verify`; su salida
  resumida y conteo observado se conservan en `validation/pctx-verify-0.7.json`.
  No es una simple afirmación escrita por el coordinador.
- Rama@commit se invalida cuando cambia la referencia; cada prueba compara su
  propio commit. Las revisiones de checklist también se invalidan. Las fuentes
  públicas ocultas seguidas por Git participan en los snapshots de una batería.
- Brief de cinco partes con presupuesto completo, rol W4, restricciones globales,
  avisos de omisión y lectura sin alterar la traza global. Los informes no verificados
  conservan su marca `inferred` en el brief. Los roles sin objetivo no se presentan
  como contexto esencial completo.
- Informes: reimportación sin revisiones/duplicados; actualización por sección;
  append de log sin invalidar entradas previas; confirmación humana preservada;
  roles W3/W4 del log compartido conservados. No se ejecutan bloques de comandos.
  Lotes fuera de cobertura se rechazan antes de importar, sin omisión silenciosa.
- Escritura limitada a HECHO-*.md e INTEGRACION-LOG.md sin reserva de código,
  append concurrente y guardia por hash para sobrescribir. Rutas privadas/enlaces,
  secretos/transcripciones y reemplazos de identidad ajena se rechazan.
- Reservas: .delegacion permitida; limpieza vencida conserva checkpoint/historial;
  alias solo si son inequívocos y liberación tardía no altera al sucesor.
  El escaneo no modifica el ciclo de una reserva liberada; un historial con
  metadatos de evidencia desfasada sigue legible sin permitir reactivar la reserva.
- Quiet en CLI/MCP, modo de export manual y exports repetidos con mismos bytes/mtime.
- 57 recorridos Chromium pasan sin errores JavaScript, incluidos generar/copiar
  un brief acotado por rol y avisar si faltan esenciales. Capturas escritorio/móvil
  revisadas, sin desbordamiento horizontal.
- Wheel en venv limpio y zipapp aislado pasan: CLI de decisiones, reemplazos,
  brief, quiet, ejecución de check, informe/importación, export manual, MCP,
  recursos del panel y apagado. Paquetes sin extras semánticos obligatorios.
- Recuperación: once casos pasan sin pérdida silenciosa de esenciales, fugas ni
  diferencias al repetir la consulta. Análisis incremental equivale al completo.
- Benchmark sintético: léxico 7/10 con 6019 tokens aproximados, híbrido local 10/10
  con 7741. El bono de recencia no desplaza coincidencias semánticas fuertes con
  notas recientes poco relevantes. Son mediciones sintéticas, no ahorro universal.

Comandos reproducibles:

```bash
python3 -m unittest discover -s tests -v
NODE_PATH=/ruta/node_modules node tests/ui_smoke.cjs
python3 -m pip wheel --no-deps . --wheel-dir dist
python3 tests/wheel_smoke.py dist/pctx-0.7.0-py3-none-any.whl
python3 benchmarks/recovery.py --output validation/recovery-0.7.json --assert-pass
python3 benchmarks/incremental.py --output validation/incremental-0.7.json
pctx verify --id fact.pctx07.executed-battery
# Revisa la definición y usa su revisión actual antes de volver a ejecutarla.
```

El respaldo anterior al cambio es
`~/pctx-backups/pctx-before-0.7-20261024T213952Z.tar.gz`, SHA-256
`b43422c8e8d0e442f0f56be030541221c126f9a556716d414a00e32ba5022c16`.
Los artefactos congelados 0.3–0.6 se conservan. El código sigue sin inicializar Git.

La validación cubre Linux local, procesos y panel; quedan pendientes sesiones
reales entre clientes/modelos externos y otros sistemas operativos. Los informes
importados son afirmaciones y las reservas requieren cooperación. La función
verify ejecuta el comando que se autorizó, con su alcance; no prueba por sí sola
cualquier afirmación libre de un informe. Uso: [USO_0.7.md](USO_0.7.md).
