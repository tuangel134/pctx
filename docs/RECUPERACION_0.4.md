# Recuperación selectiva 0.4

PCTX conserva conocimiento durable fuera de una conversación. Al cambiar de IA,
la nueva sesión lee identidad, restricciones, pendientes y handoff, y busca los
hechos o fragmentos que le faltan. Los JSON y documentos son portables; SQLite y
los vectores se pueden reconstruir. Ningún índice sustituye el contexto completo.

## Uso diario

```bash
pctx --root /ruta/proyecto context --task 'Corregir renovación de sesión' --budget 2000
pctx --root /ruta/proyecto lookup 'autenticación cookie' --budget 1000 --limit 4
pctx --root /ruta/proyecto lookup 'docs/acceso.md' --kind document --offset 0
pctx --root /ruta/proyecto expand 'REFERENCIA_DEVUELTA' --budget 1000
pctx --root /ruta/proyecto neighbors 'record:decision.api' --depth 2 --limit 12
pctx --root /ruta/proyecto index
```

`lookup` devuelve JSON compacto con origen, estado, hash de revisión, líneas,
intervalo de caracteres y razones de selección. Los fragmentos tienen hasta
1200 caracteres; las vistas previas largas se marcan `excerpt` e indican su inicio.
`expand` devuelve el fragmento completo exacto, no todo el archivo. Para recorrer
un documento, consulta su ruta exacta y usa `next_offset`. Si el presupuesto no
permite ningún resultado, aumenta `--budget`; no se devuelve un fragmento cortado
sin advertencia. `truncated` y la cobertura deben revisarse antes de actuar.

El presupuesto (256–100000) cubre el JSON visible de estas herramientas, incluidos
metadatos y escapes. Se estima con caracteres/4; no es el tokenizador ni la factura
de un proveedor. El sobre de transporte MCP, el esquema de herramientas y la
respuesta posterior de la IA tienen costes adicionales. `context --json` sigue
incluyendo un reporte separado cuyo coste no pertenece al texto presupuestado.

Las referencias incluyen revisión y desplazamiento. Un cambio de contenido,
metadatos relevantes o estado invalida la referencia; borrar o excluir una fuente
la vuelve inaccesible. Repite la búsqueda ante `Fragment unavailable`. El estado
`stale-evidence` advierte cambios de evidencia incluso antes del próximo scan.

Un resultado vacío no demuestra que algo no exista. Reformula, consulta por ruta,
explora conexiones o lee la exportación completa. Una respuesta recuperada tampoco
prueba que una afirmación inferida sea verdadera.

## CLI, MCP y panel

MCP expone `pctx_lookup`, `pctx_expand`, `pctx_neighbors` como lecturas, incluso
cuando la conexión permite escribir. `pctx_index` requiere escritura; acepta una
carpeta `model` opcional. `pctx_context` conserva restricciones y campos esenciales
antes de añadir documentos. El reporte muestra referencias documentales y cobertura.

En **Contexto** del panel: consulta, filtro memoria/documentos, presupuesto,
resultados, lectura exacta, conexiones y reconstrucción explícita. El modo
semántico y la carpeta del modelo están en el apartado opcional. Los documentos
se muestran como texto, nunca se ejecutan sus instrucciones ni su HTML.

Las conexiones derivadas unen registros con archivos de evidencia. Las relaciones
explícitas viven en el mismo JSON canónico y conservan historial:

```bash
pctx decision --id decision.api --statement 'Mantener el contrato público' \
  --link affects:file:src/api.py --link supports:record:constraint.compatibilidad
```

MCP `pctx_record_update` acepta:

```json
{"links":[{"relation":"depends_on","target":"record:decision.api"}]}
```

Relaciones: `depends_on`, `supports`, `contradicts`, `replaces`, `affects`.
Son afirmaciones explícitas, no contradicciones o causalidades demostradas.
Las conexiones con objetivos ausentes, privados o excluidos no se exponen.
Las aristas de arquitectura participan cuando sus etiquetas corresponden a
archivos actuales seguros; el mapa de arquitectura conserva sus límites de 0.3.

## Embeddings locales opcionales

El modo predeterminado usa texto y conexiones, sin llamadas de IA. El modo híbrido
combina BM25 y similitud coseno mediante reciprocal rank fusion; mantiene después
la expansión limitada de conexiones. Los vectores se guardan en la misma caché
SQLite y la consulta se codifica solo en RAM. No requiere un servidor vectorial.

```bash
# En tu entorno PCTX, solo si quieres el modo opcional:
# Desde el código fuente de PCTX y dentro de tu entorno:
python -m pip install -e '.[semantic]'
pctx index --model /ruta/modelo-local
pctx lookup '¿Cómo vuelvo a entrar?' --mode hybrid --model /ruta/modelo-local --budget 1600
```

El modelo debe existir antes de ejecutar PCTX. No hay descargas, cuentas, proveedores
ni sustituciones implícitas. Un modelo ausente, índice obsoleto/incompleto, hash
diferente o vector inválido causa un error explícito. Reconstruye indicando el
modelo después de cambiar fuentes. Un refresh que encuentra el índice sin cambios
conserva los vectores; si las fuentes cambiaron reconstruye texto, y la opción
híbrida requiere indexar de nuevo con el modelo.

Contrato admitido: tokenizer JSON de Hugging Face, ONNX con entradas int64
`input_ids`, `attention_mask` y opcional `token_type_ids`, salida de embeddings
por token, media ponderada por máscara y normalización. No ejecuta código Python
del modelo. Cada carpeta incluye:

```json
{"schema":1,"model":"model.onnx","tokenizer":"tokenizer.json","pooling":"attention-mean","max_length":128,"output":"last_hidden_state","pad_id":1,"pad_token":"<pad>"}
```

El archivo se llama `pctx-embedding.json`. Ajusta padding, salida y longitud al
contrato real de tu modelo; este ejemplo corresponde al modelo evaluado. Otros
contratos/prefijos especializados requieren un adaptador adicional. Los archivos
son locales relativos a esa carpeta; no se admiten rutas externas ni symlinks.
El hash incluye configuración, ONNX y tokenizer completos, no la ruta absoluta.

En este equipo se preparó explícitamente para evaluar:
`~/.cache/pctx/models/multilingual-minilm-qint8`, con
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, ONNX qint8,
384 dimensiones. El modelo ocupa 118412398 bytes y el tokenizer 9081518 bytes;
identidad y SHA-256 en `validation/semantic-model-0.4.json`. Las dependencias
opcionales están instaladas en el entorno local de PCTX, no en Python del sistema.

`max_length` limita la entrada del encoder. El reporte de indexación anuncia
`truncated_inputs`; la búsqueda de texto conserva todos los fragmentos aunque
un embedding omita su final. El benchmark tuvo 14 entradas truncadas de 84;
no se afirma cobertura semántica completa ni precisión universal. La opción local
consume CPU/RAM y tarda más que FTS5; conviene para paráfrasis y otro idioma.

## Privacidad, cobertura y recuperación

Se indexan registros públicos/internos activos y documentos UTF-8 `.md`, `.rst`,
`.adoc`, `.txt`. Se excluyen privados, sustituidos, historiales, `.project-context`,
salidas generadas, dependencias, symlinks y las reglas `.gitignore`/`.pctxignore`.
También se excluyen rutas con nombres privados, secretos, credenciales, chats,
conversaciones, transcripciones o logs, y documentos con secretos detectables o varios mensajes de roles de conversación.
El detector es conservador, no una garantía para documentos mal clasificados;
usa `.pctxignore` para cualquier material que no deba entrar.

Límites: 10000 archivos descubiertos, documentos de hasta 256 KiB, 8 MiB de texto,
10000 fuentes de texto y 12000 fragmentos. Las exclusiones y límites se reportan
como cantidades sin revelar los nombres privados. Las rutas seguras de código
pueden ser nodos del grafo; su cuerpo no se indexa en esta versión. No se guardan
conversaciones, consultas reales ni embeddings de consultas.

`.project-context/.cache/knowledge.sqlite3` es reconstruible, con permisos 0600
y reemplazo atómico bajo el bloqueo del proyecto. Las lecturas comprueban el
inventario y los términos actuales; nunca devuelven texto desde la caché.
`ephemeral:missing`, `ephemeral:stale` y `ephemeral:corrupt` indican un índice
FTS temporal en RAM. Esto no modifica archivos ni simula que el índice persistente
esté sano. Las lecturas híbridas exigen un índice vectorial persistente vigente.
Los respaldos de memoria excluyen la caché y los modelos; después de restaurar,
puedes reconstruir ambos. El JSON canónico sigue usando esquema 1.

## Fuentes técnicas consultadas

- [SQLite FTS5 y BM25](https://www.sqlite.org/fts5.html).
- [Búsqueda semántica de Sentence Transformers](https://www.sbert.net/examples/sentence_transformer/applications/semantic-search/README.html).
- [Fusión de búsquedas mediante RRF](https://qdrant.tech/documentation/search/hybrid-queries/).
- [GraphRAG: proceso de indexación](https://microsoft.github.io/graphrag/index/overview/).
- [Modelo multilingüe evaluado](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/tree/e8f8c211226b894fcb81acc59f3b34ba3efd5f42).

Se eligió un grafo explícito y SQLite local para conservar portabilidad y evitar
un proceso obligatorio de extracción con LLM. Un servidor vectorial o GraphRAG
completo queda fuera de esta entrega; su conveniencia requeriría medir escala
y consultas adicionales, no asumir que reduce tokens por sí solo.
