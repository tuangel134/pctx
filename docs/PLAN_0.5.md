# PCTX 0.5: metas, checklists y revisiones

Objetivo: que una persona o IA distinga qué se quiere conseguir, qué falta,
qué se declaró terminado y qué se comprobó realmente, sin cargar todo el historial.

- [x] Metas/subtareas/bugs/verificaciones persistentes en registros JSON con historial.
- [x] Estados, prioridades, responsables, criterios de aceptación y dependencias.
- [x] Revisiones con contador, resultado, evidencia, criterios cubiertos y reintentos seguros.
- [x] Rechazar cierre con pendientes y exigir evidencia vigente para verificar.
- [x] Dificultad en cinco niveles, motivo, riesgo separado y filtros de trabajo listo para asignar.
- [x] Resumen acotado para IA y navegación paginada de detalles/historial.
- [x] CLI, MCP y panel con casillas, filtros, progreso y revisión detallada.
- [x] Pruebas de privacidad, concurrencia, regresión, UI y paquete limpio.
- [x] Documentar, instalar, poblar el plan de PCTX con estados reales y cerrar handoff.

Conservar JSON canónico, respaldos y versiones previas. No inicializar Git ni
publicar ni modificar otros proyectos. No migrar automáticamente tareas históricas
ni inventar revisiones: las importaciones explícitas conservan su procedencia.

Uso y criterios: [CHECKLISTS_0.5.md](CHECKLISTS_0.5.md). Validación y respaldo previo: [VALIDACION_0.5.md](VALIDACION_0.5.md).

Entrega local comprobada: 120 pruebas, 47 recorridos Chromium y paquetes/instalación 0.5. El plan canónico conserva pendientes de traspaso real entre clientes/modelos; no se declaran probados.
