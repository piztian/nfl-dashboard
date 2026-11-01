# NFL Dashboard 2026

Dashboard personal de pronósticos, parlays y estadísticas NFL 2026.

## Contenido

- 13 picks originales de la Semana 8 (quiniela).
- 3 parlays confirmados de Playdoit ($300 MXN apostados).
- Seguimiento de aciertos, fallos y selecciones anuladas.
- Cálculo de resultados financieros por boleto.
- Exportación de historial en CSV.

## Uso

Abrir `index.html` en cualquier navegador. No requiere build ni dependencias.

### Controles

| Botón | Acción |
|---|---|
| Exportar historial CSV | Descarga el historial completo en CSV (con BOM, compatible con Excel en español). |
| Copiar resumen | Copia un resumen textual de los boletos al portapapeles. |
| Imprimir / guardar PDF | Abre el diálogo de impresión con estilos de impresión ya definidos. |
| Borrar resultados manuales | Reinicia estados y cobros. Las apuestas y los 13 picks se conservan. |

En cada boleto se marca el resultado de cada selección y luego el estado real del boleto
(abierto, ganado, perdido, devuelto o cobro anticipado) junto con el importe efectivamente
cobrado.

## Persistencia

Los datos se guardan **únicamente en el `localStorage` del navegador actual**.
No se sincronizan entre computadora y celular, y no hay base de datos ni servicios externos.

Para respaldar, usa **Exportar historial CSV**. Si más adelante se quiere sincronización
entre dispositivos, se puede conectar una base de datos como Supabase (requiere
autorización aparte; no se agregan credenciales a este repositorio).

## Estructura

- `index.html` — archivo único: HTML + CSS + JS embebidos, sin dependencias externas.

## Publicación

GitHub Pages, rama `main`, carpeta `/ (root)`.
