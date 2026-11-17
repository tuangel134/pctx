# PCTX 0.6 — coordinación de trabajo entre IAs

Objetivo: repartir metas y tareas sin duplicar trabajo entre sesiones que cooperan
sobre la misma raíz, con reservas temporales y checkpoints breves.

- [x] Reservas JSON de tarea y rutas con bloqueo atómico y conflictos por subárbol.
- [x] Sesiones, renovación con revisión esperada, caducidad y liberación con traspaso.
- [x] Ocupación visible en checklist/contexto sin alterar contadores de revisión.
- [x] CLI/MCP y panel: adquirir, ver, renovar, liberar y consultar historial.
- [x] Recuperación segura: no revivir reservas al restaurar respaldos.
- [x] Validación integrada, paquete limpio, instalación y documentación de resultados.
- [x] Cerrar tareas, evidencia y handoff sin declarar probados clientes externos.

Se mantiene la traza global bajo un coordinador; trabajadores paralelos usan
contexto de solo lectura y checkpoints de reserva. No se invocan ni contratan IAs.
Uso y límites: [COORDINACION_0.6.md](COORDINACION_0.6.md).
