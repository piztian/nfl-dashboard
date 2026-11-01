# OPERACION — Control NFL 2026

Como operar el sistema semana a semana, como repararlo y que hacer cuando
algo falla. Complementa al `README.md`.

---

## 1. Arquitectura

```
Google Sheets PRIVADO (fuente de verdad)
   Boletos | Selecciones | Picks | Partidos | Bitacora | Resumen | Guia
        ^
        |  scripts/nfl_sync.py  (escribe resultados + bitacora)
        |
   nfl_client.py  -->  proveedor NFL (ESPN, API publica no oficial)
        |
        v
   scripts/publish (genera) --> data/public-nfl.json  (SANITIZADO)
        |
   GitHub Actions (nfl-sync.yml) --> commit --> Pages
        |
        v
   index.html (dashboard publico, solo lectura)   index.html
```

**Flujo unidireccional:** Sheets -> JSON -> Paginas. El navegador **nunca**
escribe al Sheet. Para cambiar algo (apuesta, cobro real, anotacion) se edita
el Sheet; el siguiente ciclo de sincronizacion lo refleja en el dashboard.

---

## 2. Identidad de Google

| Que | Valor |
|---|---|
| Tipo | Cuenta de servicio (service account) |
| Email | `moltyluk@moltyluk.iam.gserviceaccount.com` |
| Project | `moltyluk` |
| Permiso en el Sheet | Editor, **solo** en este spreadsheet |
| Scopes | `https://www.googleapis.com/auth/spreadsheets` |

La cuenta de servicio **no tiene acceso a ningun otro documento** de Google.
Si se filtra el JSON, el alcance del dano se limita a este Sheet.

### Secrets de GitHub (Settings > Secrets and variables > Actions)

| Nombre | Tipo | Contenido |
|---|---|---|
| `NFL_SPREADSHEET_ID` | Secret | ID del spreadsheet (esta en la URL, entre `/d/` y `/edit`) |
| `NFL_GOOGLE_CREDENTIALS` | Secret | JSON completo de la cuenta de servicio |

Ambos ya estan configurados en el repositorio. **Nunca** se imprimen en logs:
el workflow los escribe en `$RUNNER_TEMP` y el validador aborta la publicacion
si detecta un JSON de credenciales en el artefacto.

---

## 3. Como actualizar (el flujo normal)

1. Terminan los partidos del domingo.
2. GitHub Actions corre cada 20 minutos y actualiza solo si hay cambios.
3. El dashboard se actualiza en ~20 s tras el commit.
4. Para forzar una actualizacion inmediata: **Actions > Sincronizar resultados NFL >
   Run workflow**.

### Si el resultado no aparece

```bash
cd ~/clawd/repos/nfl-dashboard
git pull
export NFL_SPREADSHEET_ID="<id-del-spreadsheet>"
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.openclaw/workspace/google-credentials.json"
python3 scripts/nfl_sync.py --dry-run   # 1. ver que propone, sin escribir
python3 scripts/nfl_sync.py             # 2. aplicar de verdad
python3 scripts/validate_public.py data/public-nfl.json
```

El `--dry-run` **nunca** escribe en el Sheet. Siempre empieza por ahi.

---

## 4. Anadir una semana nueva

1. En el Sheet, agrega las filas a `Picks` (columnas: Semana, Fecha, Pick,
   Rival, Mercado, Resultado, Marcador). La `Semana` va en numero.
2. Agrega las selecciones nuevas a `Selecciones`, con el `Boleto` al que
   pertenecen (texto libre, pero debe ser consistente).
3. Para un boleto nuevo, agrega la fila a `Boletos`:
   `Boleto | Fecha | Casa | Apostado MXN | Momio | Cobro potencial MXN |
   Bono MXN | ID boleto | Estado | Cobro real MXN | Notas`.
   El `ID boleto` **no se publica** (queda solo en el Sheet).
4. Corre el sincronizador en dry-run y revisa el reporte.
5. Aplica y publica.

La tabla de inicio de semana NFL 2026 esta en `scripts/nfl_client.py`
(`INICIO_SEMANA`). Al pasar de temporada, actualiza esa tabla.

---

## 5. Reglas de liquidacion implementadas

| Mercado | Regla |
|---|---|
| Moneyline | Compara ganador final. Empate -> Revision manual. |
| Spread | `margen + spread > 0` gana; `< 0` pierde; `= 0` push. |
| Under 43.0 | 42 o menos gana, 43 push, 44 o mas pierde. |
| Under 43.5 | 43 o menos gana, 44 o mas pierde. |
| Over | Regla inversa del Under. |

- Un partido **sin marcador final** queda `Pendiente`. Nunca se rellena con 0.
- La prorroga va incluida (el marcador del proveedor ya la incluye).
- Un partido que no coincide con ninguna fila **no se crea**.
- El emparejamiento exige **ambos equipos y la fecha**. Por eso
  Ravens@Bills (01/11) y Ravens@Jaguars (05/11) nunca se confunden.

---

## 6. Politica de edicion manual

- El sincronizador **nunca** sobreescribe un resultado que no sea `Pendiente`.
- Si escribes un resultado a mano en la columna `Resultado`, se preserva y se
  registra el aviso en el log del run.
- Para marcar un resultado automatico como firme, escribe el estado tal cual
  (`Ganada`, `Perdida`, `Anulada (push)`, `Acertado`, `Fallado`).
- `Cobro real MXN` **solo** lo escribes tu, con la conciliacion real de Playdoit.
  El sistema no lo inventa ni lo calcula.
- `Bono MXN` es informacion del boleto: si esta vacio, se queda vacio.

---

## 7. Que hacer cuando falla

| Sintoma | Causa probable | Que hacer |
|---|---|---|
| `403 ... does not have permission` | La cuenta de servicio perdio el permiso del Sheet | Reautorizar: agregar `moltyluk@moltyluk.iam.gserviceaccount.com` como Editor del Sheet |
| `404` al cargar `data/public-nfl.json` | El sync no ha corrido o fallo | Correr el sync manualmente (seccion 3) |
| `RECHAZADO: ... contiene datos privados` | El generador metio algo prohibido | **No publicar.** Revisar `scripts/validate_public.py` y el origen del dato |
| Marcadores que no llegan | El proveedor cambio su formato | Revisar `nfl_client._parsear_espn_scoreboard` con `sample-data/` |
| El proveedor esta caido | ESPN es API publica, no garantizada | El sync reintenta 3 veces; si persiste, no cambia estados: deja todo `Pendiente` |
| Un partido quedo con resultado raro | Discrepancia | Se marca `Revision manual`; revisalo y corrigelo a mano en el Sheet |

### Principio de seguridad

Ante cualquier duda del proveedor, el sistema **no cambia estados
existentes**: marca `Revision manual`, deja el dato anterior y avisa. Es
preferible un dato viejo correcto a un dato nuevo inventado.

---

## 8. Rollback

- **Datos del dashboard:** `git revert <commit>` en `data/public-nfl.json`, o
  restaura el commit anterior del archivo.
- **Dashboard anterior (pre-refactor):**
  `git show <commit-previo>:index.html > index.html` y push.
- **Backup local del `index.html`:** `~/clawd/backups/nfl-2026-11-01/index.html.pre-faseA`
- **Backup del Sheet:** la pestana `Bitacora` registra cada escritura con
  timestamp, accion, filas afectadas y motivo. Para revertir una liquidacion
  automatica, edita la celda en el Sheet y deja que el siguiente sync lo respete.

---

## 9. Pruebas

```bash
cd ~/clawd/repos/nfl-dashboard
python3 tests/test_markets.py       # reglas de mercado (casos 1-7)
python3 tests/test_integration.py   # integracion e idempotencia (casos 6-14)
python3 scripts/validate_public.py data/public-nfl.json
```

Las pruebas corren **dentro** del workflow antes de cada sincronizacion. Si
fallan, no se publica nada.

---

## 10. Limites conocidos

- **Proveedor no oficial.** ESPN no garantiza disponibilidad ni estabilidad de
  formato. Si cae, el sistema deja todo en `Pendiente` (no inventa).
- **GitHub Actions no es tiempo real.** Las ejecuciones programadas pueden
  retrasarse varios minutos.
- **Sin sincronizacion entre dispositivos.** El dashboard es de solo lectura y
  refleja el Sheet; no hay estado local que sincronizar.
- **Vista publica sin autenticacion.** Los detalles privados (IDs de boleto,
  cobros reales por boleto) solo se ven en el Sheet. Una app autenticada es
  Fase 2 y requiere autorizacion aparte.
