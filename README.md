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

## Actualizar el dashboard (semana a semana)

1. Edita `index.html` localmente (los arrays `ticketData` y `games` al inicio del `<script>`).
2. Sube el cambio:

```bash
cd <ruta-del-repo>
git add index.html
git commit -m "feat: actualizar semana N"
git push origin main
```

3. GitHub Actions publica automáticamente (~20 s). La URL no cambia.

Si prefieres que el agente lo haga, mándale el HTML nuevo y lo publica con este mismo flujo.

### Reiniciar el estado del navegador

Si quieres dejar los resultados en cero (por ejemplo, para una nueva semana), abre la
página en el navegador y usa **Borrar resultados manuales**. También se puede limpiar
desde la consola del navegador:

```js
localStorage.removeItem('nfl-2026-week8-ledger-v2')
```

<!-- trigger test 1793514848 -->
