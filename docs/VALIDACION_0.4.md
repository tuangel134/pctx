# Validación PCTX 0.4.0 — 9 de octubre de 2026

La recuperación unificada está implementada y comprobada localmente. Los JSON
siguen usando esquema 1 y siendo canónicos; índices y vectores son reconstruibles.
La entrega 0.3 y su respaldo se conservan. Evidencia inmutable de esta entrega:
`validation/release-0.4.json`. El cierre integrado queda en `validation/final-0.4.json`.

## Comparación reproducible

Mismos registros/documentos sintéticos y mismo digest de fixture para tres modos.
Se comprueba si la respuesta esperada está disponible en la salida recibida por
la siguiente sesión, y que restricciones esenciales estén presentes. No usa un
LLM para inventar una respuesta ni prueba un cambio real entre clientes de IA.

| Modo | Respuestas recuperables | Tokens estimados, diez casos | Mediana por caso |
| --- | ---: | ---: | ---: |
| 0.3 búsqueda de registros | 2/10 | 9918 | 0.022 s |
| 0.4 texto y grafo | 7/10 | 6007 | 0.045 s |
| 0.4 híbrida local | 10/10 | 7727 | 0.943 s |

Texto y grafo consumieron 39.4 % menos que la búsqueda 0.3 en estos fixtures,
y el modo híbrido 22.1 % menos, con mayor cobertura. Las coberturas son distintas:
esto no es una garantía de ahorro general ni una comparación de precisión de IAs.
La versión 0.3 puede recuperar documentos mediante lectura manual; una política
sintética que carga toda la memoria pública y todos los documentos ante un fallo
consumió 53816 tokens. Esa política se identifica por separado, no se atribuye a
todo uso de 0.3 ni se usa para anunciar un ahorro universal.

El coste incluye consulta, contexto de tarea de 512 tokens, JSON visible completo
y hasta dos lecturas adicionales cuando la respuesta no aparece en la vista previa.
No cuenta pesos del modelo, instalación, esquemas/transportes del proveedor ni
respuesta posterior de la IA. Estimación caracteres/4, no tokenización comercial.

Las siete consultas léxicas obligatorias cubren documento, alias español, evidencia,
relación sin vocabulario compartido, detalle profundo y memoria larga. Las tres
paráfrasis adicionales requieren la opción semántica en este conjunto. El modelo
multilingüe ONNX CPU recupera 10/10, conserva todas las restricciones esenciales y
no devuelve marcadores privados ni sustituidos. Codificación limitada a 128 tokens:
14 de 84 fragmentos truncaron su entrada semántica; FTS conserva el texto completo.
Datos exactos y tiempos por escenario: `validation/knowledge-*.json`.

## Matriz de comprobaciones

- 92 pruebas unitarias/integración pasan: las 72 de 0.3 y 20 nuevas de recuperación.
- Índices ausentes, corruptos, alterados, obsoletos y eliminados; lectura sin escritura,
  invalidación de referencias, exclusión de privados/historial/secretos/conversaciones,
  symlinks, salida con escapes JSON, paginación y límites.
- Grafo de evidencia/relaciones, dos saltos y presupuesto; objetivos privados ausentes;
  extensiones JSON con historial, preservación al actualizar y validación de enlaces.
- Cambios de evidencia visibles antes de scan; documentos después de esenciales;
  construcción concurrente y reemplazo atómico del índice.
- Modo híbrido exige modelo explícito, identidad y vectores completos; no cambia
  silenciosamente a texto cuando falla. Un rebuild fallido conserva el índice anterior.
- 34 recorridos reales en Chromium sin errores JavaScript, incluyendo las cinco
  acciones nuevas, referencia borrada y diseño de búsqueda en escritorio/móvil.
  Capturas revisadas en `validation/lookup-*-0.4.png`.
- 11 escenarios anteriores de recuperación pasan sin esenciales omitidos sin aviso.
  Benchmark incremental: resultados equivalentes a verificación completa, con
  reutilización de parsers y detección por hash pese a conservar tamaño/mtime.
- Wheel en entorno limpio sin extras: CLI, lectura MCP, nuevas herramientas,
  assets, proceso gráfico y zipapp con `-I` pasan. Ausencia de modelo falla claramente.
- Instalación local 0.4.0 y extras semánticos aislados comprobados. Diagnósticos MCP
  lectura/escritura hacen llamada local real, validan identidad/versión y cierran procesos.
- Wheel y zipapp contienen exactamente los módulos y assets actuales, comprobados
  byte por byte. Los modelos no se incluyen en los paquetes ni respaldos canónicos.

## Reproducir

Desde `/ruta/al/proyecto`:

```bash
python3 -m unittest discover -s tests -v
python3 benchmarks/clean_room.py
python3 benchmarks/recovery.py --output validation/recovery-candidate-0.4.json --assert-pass
python3 benchmarks/incremental.py --output validation/incremental-candidate-0.4.json
python3 benchmarks/knowledge.py --mode lexical --output validation/knowledge-lexical-0.4.json
python3 benchmarks/knowledge.py --mode hybrid \
  --model ~/.cache/pctx/models/multilingual-minilm-qint8 \
  --output validation/knowledge-hybrid-0.4.json
NODE_PATH=/ruta/node_modules node tests/ui_smoke.cjs
python3 -m pip wheel --no-deps . --wheel-dir dist
python3 tests/wheel_smoke.py dist/pctx-0.4.0-py3-none-any.whl
```

El baseline 0.3 se extrajo únicamente del paquete `pctx/` del respaldo previo,
con SHA-256 verificado, en `validation/baseline03` (excluido del proyecto escaneado):

```bash
PCTX_BENCHMARK_COMPILER_ROOT=validation/baseline03 python3 benchmarks/knowledge.py \
  --mode legacy --output validation/knowledge-baseline-0.3.json
```

No sobrescribir `validation/release-0.4.json` si cambia código o evidencia;
crear una nueva entrega y actualizar explícitamente los hechos que dependan de ella.

## Artefactos y límites

Wheel: `dist/pctx-0.4.0-py3-none-any.whl`.
SHA-256 `3281b1c4ef79b54eaa2d16b312941c747b8714b0ce75b429e54b7cd2fff6e9f1`.
Zipapp: `.project-context/.runtime/pctx.pyz` (0.4.0).
Instalación local: `~/.local/bin/pctx`; extras dentro de `~/.local/share/pctx/venv`.

MCP/CLI y panel local están probados. Cursor/Claude/Gemini/otros IDEs, ChatGPT web,
Windows/macOS y sesiones efectivas entre modelos externos continúan sin comprobar.
El benchmark es de recuperación sintética, no una promesa de memoria perfecta.
No se publicaron cambios ni se modificaron otros proyectos.

Uso, filtros de privacidad, contrato ONNX, fuentes técnicas y límites de cobertura:
[recuperación 0.4](RECUPERACION_0.4.md).
