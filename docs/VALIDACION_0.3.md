# Validación local de PCTX 0.3.0

Entrega del 9 de octubre de 2026 en Linux/Python 3.14. Las diez mejoras tienen
implementación y pruebas. La comprobación final de memoria/adaptadores/handoff
queda registrada en `validation/final-0.3.json`. No se validaron sesiones reales
en todos los IDEs, ChatGPT web ni Windows/macOS.

## Resultados reproducibles

- 72 pruebas unittest pasan. Incluyen concurrencia de hilos y procesos, integridad
  de historial, privacidad, restauración fallida y recuperación tras matar el proceso.
- 11 escenarios de recuperación pasan. Con los mismos fixtures v2 y presupuestos,
  los casos con omisiones esenciales sin identificar bajan de 4 a 0; los registros
  irrelevantes incluidos bajan de 276 a 0 respecto al código 0.2 respaldado.
- Con 1 000 registros de ruido, las dos afirmaciones esperadas aparecen en 446
  tokens aproximados dentro de 1 800. Con restricciones demasiado largas o numerosas
  se anuncia incompletitud y el informe identifica los elementos omitidos.
- Clean-room pasa: 653 tokens aproximados y 6 registros seleccionados.
- Chromium/Playwright: 28 recorridos pasan, sin errores JavaScript. Incluyen revisión
  de hashes, confirmación explícita, corrección, historial/restauración, diferencias,
  respaldo privado y previsualización/restauración, además de escritorio/móvil.
- Wheel 0.3.0 instalado en venv limpio: CLI, MCP, nuevas lecturas, diagnóstico,
  migración, respaldo y zipapp aislado pasan; assets del panel y apagado pasan.
  Los bytes de todos los módulos/assets del wheel coinciden con el árbol actual.
- Instalación editable local actualizada a 0.3.0; el wheel 0.2 se conserva.

Estos resultados describen escenarios definidos, no recuperación semántica universal
ni tokens exactos de todos los modelos. El tamaño se estima como caracteres/4.

## Matriz de las diez mejoras

| Mejora | Código compartido | Evidencia principal |
| --- | --- | --- |
| 1. Esenciales y omisiones | `compile.py` | `test_retrieval.py`, recovery v2, UI incompleto |
| 2. Relevancia explicable | `retrieval.py` | Rutas, aliases explícitos y vecino de arquitectura |
| 3. Historial/restauración | `history.py`, `storage.py` | `test_history.py`: integridad, procesos, fallo atómico |
| 4. Revisión de memoria | `review.py` | `test_review.py`: cambios, guardas, candidatos, sustitución |
| 5. Benchmark comparable | `benchmarks/recovery.py` | Baseline 0.2 y candidato 0.3, mismos fixtures/presupuestos |
| 6. Expansión progresiva | CLI/MCP/panel + `retrieval.py` | ID/componente, límites, privacidad y lecturas sin escritura |
| 7. Reanudación con diferencias | `continuity.py`, `tasks.py` | Sin Git, porcelain idéntico, renombre, pendientes y checkpoint |
| 8. Escaneo incremental | `incremental.py`, scan/architecture/service | `test_incremental.py` y benchmark medido |
| 9. Respaldos/formato | `backup.py`, model/storage | `test_backup.py`: corrupción, traversal, migración y corte real |
| 10. Panel/diagnóstico | dashboard/web, `diagnostics.py` | 28 recorridos Chromium, proceso MCP real y zipapp aislado |

## Rendimiento del escaneo

Fixture v1: 160 módulos Python de 96 019 bytes y un manifiesto; mismas entradas
contra el código 0.2 extraído del respaldo inicial y el código 0.3.0. No se restauró
el respaldo sobre el proyecto. Tiempos de una ejecución local:

| Operación | 0.2 | 0.3 | Parsers de módulos ejecutados en 0.3 |
| --- | ---: | ---: | ---: |
| Sin cambios | 0,375 s | 0,062 s | 0; reutiliza 160 |
| Un cambio conservando tamaño/mtime | 0,379 s | 0,058 s | 1; reutiliza 159 |
| Verificación completa | 0,371 s | 0,381 s | 160 |
| Primer análisis | 0,381 s | 0,393 s | 160 |

El ahorro viene de reutilizar análisis estático, no de omitir verificación de hashes.
El primer análisis y el completo no mejoran en este fixture; la caché tiene coste.
El grafo incremental coincide con el completo. Los tiempos no son umbrales de CI.

Se invalidan parsers por contenido, exclusiones/configuración y versión del parser.
`scan --full` ignora la caché. Una caché ilegible o con checksum incorrecto se
reconstruye. La vigilancia agrupa cambios hasta un intervalo estable, conserva la
unión de rutas y no avanza el checkpoint explícito. Límites: 10 000 archivos por
defecto, 48 subproyectos, lectura de importaciones acotada y mapa de 64 nodos/120
aristas. Informes de scan/architecture contienen cobertura, procesados y reutilizados;
contexto y doctor muestran cobertura parcial. El panel muestra truncamiento de archivos.

## Comandos

Desde `/ruta/al/proyecto`:

```bash
python3 -m unittest discover -s tests -q
python3 benchmarks/clean_room.py
python3 benchmarks/recovery.py --output validation/recovery-candidate-0.3.json --assert-pass
python3 benchmarks/incremental.py --output validation/incremental-candidate-0.3.json
NODE_PATH=/ruta/node_modules node tests/ui_smoke.cjs
python3 -m pip wheel --no-deps . --wheel-dir dist
python3 tests/wheel_smoke.py dist/pctx-0.3.0-py3-none-any.whl
```

Los benchmarks admiten `PCTX_BENCHMARK_COMPILER_ROOT` para seleccionar la carpeta
que contiene otro paquete `pctx/`. El baseline proviene solo del código Python del
respaldo inicial verificado. `recovery.py` sin `--assert-pass` mide aunque haya fallos.

```bash
pctx --root /ruta/al/proyecto context --task "corregir src/auth.py" --budget 1800 --read-only --json
pctx --root /ruta/al/proyecto search "autenticación y sesión" --json
pctx --root /ruta/al/proyecto read --id decision.api
pctx --root /ruta/al/proyecto read --component src/audio --limit 20
pctx --root /ruta/al/proyecto history --id decision.api --revision 1 --compare 2
pctx --root /ruta/al/proyecto history --id decision.api --restore 1 --expected-revision 2
pctx --root /ruta/al/proyecto review
pctx --root /ruta/al/proyecto review --id decision.api --action correct --statement "Afirmación corregida" --expected-revision 3
pctx --root /ruta/al/proyecto review --id decision.old --action supersede --replacement-id decision.api --expected-revision 1
pctx --root /ruta/al/proyecto differences
pctx --root /ruta/al/proyecto handoff verify --json
pctx --root /ruta/al/proyecto scan --full --json
pctx --root /ruta/al/proyecto diagnose
pctx --root /ruta/al/proyecto diagnose --write-mode
```

`--read-only` no escanea ni inicia tareas. El JSON incluye contexto y reporte;
el presupuesto cubre el texto, no el reporte pedido aparte. En MCP, contexto entrega
metadatos compactos, `pctx_context_report` entrega selección/omisiones y `pctx_read`
amplía. El reporte usa memoria actual: el panel advierte si cambió desde el paquete.
La explicación es lexical y estructural, con aliases limitados, sin modelo semántico.

Revisión e historial exigen la revisión esperada para rechazar cambios concurrentes.
Corregir/restaurar conserva versiones y queda inferido. Confirmar actualiza hashes
solo tras una acción explícita de CLI/panel, rechaza evidencia ausente/privada/insegura
y registra confirmación humana. MCP permite corregir/sustituir, no confirmar como
humano. `claim_key` agrupa afirmaciones distintas del mismo ámbito; la similitud es
solo un candidato, nunca una contradicción demostrada. La cola pagina y anuncia
límites del análisis. Sustituir escribe un enlace durable hacia el reemplazo sin
modificar dos registros; el enlace inverso se deriva de la fuente.

Las revisiones viven en `_pctx_history`, dentro del mismo JSON atómico, con digest,
fecha, origen y snapshots sin recursión. Las exportaciones normales excluyen el
historial. Los legacy sin historial siguen legibles; su primer cambio conserva el
valor anterior. Los cambios público/privado de un ID se rechazan en ambas direcciones;
`migrate` no reclasifica ni publica datos. No mezclar escritores antiguos y nuevos.

Los snapshots de checkpoint/handoff guardan hashes portables independientes de la
caché de scan. Comparar no avanza el baseline; muestra archivos y memoria cambiados,
evidencia afectada, rama/HEAD y renombres candidatos por hash único idéntico.
Un handoff legacy sin snapshot de contenido se declara no verificable. Una cobertura
parcial tampoco se declara igual. Los archivos generados/privados están excluidos.

## Respaldos, migración y recuperación

```bash
pctx --root /ruta/al/proyecto backup create --output /ruta/externa/memoria.zip
pctx --root /ruta/al/proyecto backup restore /ruta/externa/memoria.zip
# Inspeccionar el reporte anterior; usar el digest expected_state exacto:
pctx --root /ruta/al/proyecto backup restore /ruta/externa/memoria.zip --apply --expected-state DIGEST
pctx --root /ruta/al/proyecto migrate
pctx --root /ruta/al/proyecto migrate --apply --expected-state DIGEST
# Solo tras una restauración interrumpida:
pctx --root /ruta/al/proyecto backup recover
```

Sin `--output`, el respaldo va a `~/pctx-backups/`, con nombre único. Incluye memoria
canónica y privada, evidencia, work y archive; excluye cachés, runtime, bloqueo y
vistas Markdown de la raíz. No es un respaldo del código fuente. El respaldo inicial
completo del proyecto sigue separado. Los ZIP locales tienen permisos 0600 y no están
cifrados; no son exportaciones públicas. La previsualización oculta nombres privados.

Antes de escribir se valida integridad, identidad, esquemas, historiales y rutas;
se rechazan enlaces, traversal, entradas duplicadas y formatos futuros. Límite del
respaldo: 20 000 archivos/256 MiB descomprimidos. Se crea otro respaldo antes de
aplicar. El journal/staging privado conserva la imagen anterior bajo el bloqueo
existente; lectores y escritores rechazan un estado parcialmente aplicado.
`backup recover` revierte una transacción preparada o termina la limpieza de un
commit completado. Las pruebas matan un proceso tras reemplazos parciales y comprueban
la recuperación exacta. Las vistas/cachés se regeneran al aplicar desde CLI/panel.

El esquema principal permanece en 1: no se incrementa por la versión del producto.
`migrate` inicializa historiales opcionales con previsualización, guarda y respaldo;
se probó con registros 0.2 sin historial. No intenta convertir futuros esquemas.
Una corrupción de memoria se conserva para revisión, nunca se reinicializa en silencio.

## Artefactos y límites

Wheel: `dist/pctx-0.3.0-py3-none-any.whl`, SHA-256
`7eb8ee8fa04fc897fd7fb077801502d746fb8a6727541a16e56446ae1055eea5`.
Reportes en `validation/`: unittest, recovery baseline/candidato, incremental
baseline/candidato, UI, wheel smoke, instalación y final integrado. Esa carpeta
está excluida del escaneo para no convertir resultados rutinarios en conocimiento.

El diagnóstico inicia un proceso finito, hace handshake/listado/llamada de estado,
comprueba identidad/versión/modo y cierra el proceso. El modo lectura prueba rechazo
de escritura; el modo escribible verifica su catálogo mediante llamadas de lectura.
Un ejecutable ausente o timeout devuelve fallo sin repetir su salida potencialmente
sensible. El zipapp aislado usa su propio archivo para el proceso de diagnóstico.
Esto valida PCTX local, no la selección de herramientas de un cliente externo.
