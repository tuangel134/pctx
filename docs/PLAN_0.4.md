# PCTX 0.4: recuperación unificada para cambiar de IA

Objetivo: buscar memoria y documentación con referencias verificables, relaciones
explícitas y presupuesto de salida, conservando JSON como fuente de verdad.

- [x] Índice SQLite FTS5 reconstruible con fragmentos, hashes, filtros y límites.
- [x] Búsqueda acotada y lectura exacta de fragmentos, sin escribir durante lecturas.
- [x] Grafo de evidencia/relaciones y navegación limitada desde CLI/MCP/panel.
- [x] Integrar hallazgos documentales en contexto sin desplazar restricciones esenciales.
- [x] Evaluar embeddings locales opcionales, sin descargas ni servicios implícitos.
- [x] Benchmark de traspaso de conocimiento, paráfrasis y coste total de resultados.
- [x] Privacidad, cambios/eliminaciones, caché corrupta, concurrencia y regresiones.
- [x] Documentación, wheel/zipapp, instalación local, PCTX y handoff final.

Respaldado el estado 0.3 completo antes de editar código:
`~/pctx-backups/pctx-before-0.4-20261009T202315Z.tar.gz`
SHA-256 `7324c47d638aa2ed9ee5097f1d223118441cc050bb24b8d86ff888d6293ab31f`.
No inicializar Git, publicar ni modificar otros proyectos. Ningún índice sustituye
los JSON, guarda consultas/transcripciones ni revela privados/historiales obsoletos.
La evaluación entre clientes se distingue de un benchmark determinista de traspaso.
