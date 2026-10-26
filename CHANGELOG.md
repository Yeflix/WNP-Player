# Cambios

## 1.1.0 — 2026-10-26

### Nuevo
- **Iniciar con Windows** en Configuración y en el asistente de bienvenida. Activado por defecto en instalaciones nuevas.
- El diálogo «Acerca de» muestra la versión y el desarrollador (YefriDev).
- Validación de `config.json` al cargar: los valores inválidos vuelven a su valor por defecto y los rangos se recortan.

### Corregido
- Panel lateral en estilo compacto: ahora se ven el título y el artista.
- Íconos con huecos donde se cruzaban trazos (silencio, altavoz, corazón, nota).
- Manchas rojizas en las esquinas de la carátula; ahora tiene un borde de acento.
- CSV de anuncios: los textos que empiezan por `=`, `+`, `-` o `@` ya no se interpretan como fórmulas en Excel.

### Cambiado
- Asistente de bienvenida rehecho: textos en español neutro, sin menciones obsoletas, con la firma del desarrollador.
- Dependencias verificadas con las últimas versiones (PyQt6 6.11.0, pywnp 2.0.2, aiohttp 3.14.5).
- Código modernizado (`X | None`) y limpieza de importaciones sin uso.

### Al actualizar desde 1.0
- Tu configuración, historial y estadísticas se conservan (viven en `%LOCALAPPDATA%\WNPPlayer`).
- **«Iniciar con Windows» queda desactivado** para quien ya usaba la 1.0; actívalo en Configuración si lo quieres.

## 1.0.0
- Primera versión pública.
