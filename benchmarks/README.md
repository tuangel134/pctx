# Clean-room benchmark

Ejecuta:

```bash
python3 benchmarks/clean_room.py
```

El benchmark crea un proyecto temporal, lo escanea, registra una restricción,
una decisión y una nota no relacionada. Después compila únicamente el contexto
de una tarea de autenticación y verifica que contiene lo necesario, excluye
ruido de otra área y no filtra secretos.
