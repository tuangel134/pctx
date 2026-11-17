# PCTX 0.7 — memoria vigente y delegación práctica

Objetivo: que los workers reciban contexto corto y actual, con estados y pruebas
comprobables, sin duplicar informes ni ensuciar archivos generados en cada llamada.

- [x] Reemplazos atómicos/lógicos y caducidad de registros volátiles; prioridad a vigencia y recencia.
- [x] Comprobaciones de comandos explícitas, con resultado observado, límite de tiempo y salida acotada.
- [x] Evidencia Git rama@commit con detección en vivo del avance de referencia.
- [x] `pctx brief --budget 800 --role W4`: objetivo, siguiente paso, restricciones, bloqueos y cambios.
- [x] Importación idempotente de HECHO-*.md e INTEGRACION-LOG.md sin ejecutar sus instrucciones.
- [x] Recuperación de reservas vencidas, rutas de delegación ocultas seguras e informes sin reserva.
- [x] Salidas quiet/compactas y generación determinista, con opción de exportar solo bajo demanda.
- [x] Pruebas de regresión, paquete, instalación, respaldo y handoff coherentes.

JSON sigue siendo canónico. No cambiar otros proyectos ni publicar. Los comandos
guardados se ejecutan únicamente con una petición explícita; leer contexto nunca
los ejecuta. Las afirmaciones de informes importados no se convierten en pruebas.
La evidencia de entregas anteriores se conserva inmutable.
