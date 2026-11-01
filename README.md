# NFL Dashboard 2026

Control de pronósticos, parlays y resultados NFL 2026.

**Dashboard público:** https://piztian.github.io/nfl-dashboard/
**Fuente de verdad:** Google Sheets privado (ver `OPERACION.md`)

---

## Qué es

Un tablero de **solo lectura** que muestra:

- Los **13 picks** de la Semana 8 (pronósticos a ganador directo).
- Las **13 selecciones** de los **3 parlays** de Playdoit, con su mercado,
  línea y momio capturado.
- El **resultado** de cada selección y pick, liquidado automáticamente contra
  un proveedor de resultados NFL.
- Los **agregados**: aciertos, fallos, pendientes, boletototal apostado y
  cobro potencial.

## Qué NO es (por diseño)

- **No** muestra IDs de boleto, importes por boleto, cobros reales por boleto
  ni notas de conciliación. Eso vive únicamente en el Sheet privado.
- **No** escribe nada en el Sheet ni en ningún otro sitio. Es de solo lectura.
- **No** coloca apuestas ni inicia sesión en ninguna casa de apuestas.
- **No** inventa resultados ni cobros. Sin marcador final confirmado, todo
  queda `Pendiente`.

---

## Arquitectura

```
Google Sheets PRIVADO  ──►  nfl_sync.py  ──►  data/public-nfl.json  ──►  Pages
   (fuente de verdad)        (sincroniza)      (SANITIZADO)              (este sitio)
```

La sincronización corre en **GitHub Actions**, así que funciona aunque tu
computadora esté apagada. Cada 20 minutos consulta los resultados, los liquida
y publica un JSON sanitizado; el dashboard lo lee.

Detalle completo en [`OPERACION.md`](OPERACION.md).

---

## Estructura

```
index.html                     Dashboard (solo lectura, lee el JSON)
data/public-nfl.json           Datos publicados, sanitizados
scripts/nfl_markets.py         Reglas de liquidacion (Moneyline/Spread/Over-Under)
scripts/nfl_client.py          Cliente del proveedor NFL + emparejamiento
scripts/nfl_sync.py            Orquestador: Sheet -> liquidacion -> JSON
scripts/validate_public.py     Verifica que el JSON no lleve datos privados
tests/test_markets.py          Pruebas de reglas de mercado
tests/test_integration.py      Pruebas de integracion e idempotencia
sample-data/                   Fixtures anonimizados del proveedor
config/example.env             Nombres de variables (sin valores)
.github/workflows/pages.yml    Despliegue del sitio
.github/workflows/nfl-sync.yml Sincronizacion programada
```

## Uso

No requiere build ni dependencias: es HTML, CSS y JS embebidos más un JSON.

**Selector de semana** arriba: filtra por semana NFL. Elige "Todas" para ver
la temporada completa.

**Exportar historial CSV** descarga el historial completo (con BOM, compatible
con Excel en español).

**Actualizar datos** vuelve a pedir el JSON al servidor.

**Imprimir / guardar PDF** abre el diálogo de impresión con estilos de
impresión ya definidos.

---

## Reglas de liquidación

| Mercado | Regla |
|---|---|
| Moneyline | Ganador final. Empate → `Revisión manual`. |
| Spread | `margen + spread > 0` gana · `< 0` pierde · `= 0` push |
| Under 43.0 | 42 o menos gana · 43 push · 44 o más pierde |
| Under 43.5 | 43 o menos gana · 44 o más pierde |
| Over | Regla inversa del Under |

- Un partido sin marcador final confirmado queda `Pendiente`; nunca se rellena
  con ceros.
- La prórroga va incluida.
- El emparejamiento exige **ambos equipos y la fecha**, así que
  Ravens@Bills (01/11) y Ravens@Jaguars (05/11) nunca se confunden.
- Una resolución escrita a mano en el Sheet **nunca** se sobreescribe por el
  sincronizador.

---

## Seguridad

| Dato | Dónde vive |
|---|---|
| ID de boleto de Playdoit | Solo en el Sheet privado |
| Importes y cobros por boleto | Solo en el Sheet privado |
| `Cobro real` (liquidación) | Solo en el Sheet privado, escritura manual |
| Correo, tokens, claves | Secrets de GitHub / archivos locales fuera del repo |
| Nombre del equipo, rival, mercado, momio, resultado | Público (esto sí es apto) |

El pipeline tiene una **barrera automática**: `scripts/validate_public.py`
revisa el JSON contra una lista de patrones prohibidos (IDs de boleto, IDs de
spreadsheet, correos, tokens, claves privadas) y de campos permitidos. Si
detecta algo, el workflow **aborta y no publica**.

---

## Pruebas

```bash
python3 tests/test_markets.py
python3 tests/test_integration.py
python3 scripts/validate_public.py data/public-nfl.json
```

## Proveniente

Marcadores: API pública de ESPN (`site.api.espn.com`), **no oficial y no
garantizada**. El sistema valida contra el Sheet y nunca sobreescribe un dato
existente con información dudosa: en caso de discrepancia marca
`Revisión manual` y avisa.

## Marcador en vivo

El tablero muestra el marcador en vivo de los partidos de la jornada. La
consulta se hace **desde el navegador** contra el proveedor publico (ESPN,
que permite CORS abierto): no usa credenciales, no escribe en el Sheet y no
altera ningun resultado ya liquidado.

- Refresco automatico cada 60 segundos mientras la pestana esta visible.
- Se pausa si la pestana queda oculta.
- El boton "Actualizar datos" recarga el JSON publico y el marcador a la vez.

Los resultados **finales** (Ganada / Perdida / Anulada / Acertado / Fallado)
los escribe el sincronizador de GitHub Actions en el Sheet y se publican en
el siguiente ciclo. El marcador en vivo solo complementa la vista; nunca
decide un resultado.

### Actualizar manualmente

- **Solo ver marcadores**: abrir el tablero y pulsar "Actualizar datos".
- **Forzar la sincronizacion del Sheet** (escribe resultados finales):
  GitHub > Actions > "Sincronizar resultados NFL" > Run workflow.
  O desde la terminal:
  `gh workflow run nfl-sync.yml --repo piztian/nfl-dashboard`

## Tema claro / oscuro

El tablero tiene un boton luna/sol en el encabezado (arriba a la derecha) que
alterna entre tema oscuro y claro. La preferencia se guarda en `localStorage`,
asi que se mantiene entre visitas.

El orden de decision al arrancar es: **preferencia guardada > preferencia del
sistema > oscuro**. Si tu sistema esta en modo claro y no has elegido tema
manualmente, el tablero arranca en claro. En cuanto tocas el boton, tu
eleccion manda y queda guardada.

Ojo: `localStorage` es **por navegador y por dispositivo**. El tema que
elijas en la computadora no aparece en el celular ni en otra pestana sin
compartir perfil; cada dispositivo vuelve a arrancar segun su propia
preferencia guardada o la del sistema.

El tema se aplica antes de pintar (script en `<head>`), por eso no hay
destello del tema oscuro al cargar. Los colores pasan por variables CSS, de
modo que el cambio no altera ningun dato ni el Sheet.

## Estado vivo por pierna

Cada pierna de boleto y cada pick de la quiniela muestra un badge con su
estado actual:

- **VA GANANDO** (verde) / **VA PERDIENDO** (rojo) / **PUSH** (ámbar) / **SIN EMPEZAR**
- La cabecera de cada boleto muestra el conteo: "3 GANANDO", "2 PERDIENDO",
  "2 SIN EMPEZAR".
- Bajo el nombre del equipo aparece el marcador y el cuarto en curso.

El cálculo en vivo usa las mismas reglas que el backend
(`scripts/nfl_markets.py`): Moneyline por ganador, Spread como
`margen + spread` (con push exacto) y Over/Under contra el total.

> Es **informativo**. El resultado oficial lo decide el sincronizador de
> GitHub Actions contra el Sheet; el badge solo refleja el marcador de este
> momento.

El tablero se refresca solo cada 60 segundos con la pestaña visible.

## Tipografía y acabado

Escala tipográfica uniforme (~1.18x) sobre 16px de base, con `clamp()` en
los titulares para que escalen con el ancho de pantalla. Los botones y
selectores tienen `min-height` de 46px/44px para targets táctiles, y el
breakpoint móvil (680px) compacta las tarjetas, pone las estadísticas a dos
columnas y los vivos a una sola.

## Bugs corregidos (1-nov-2026)

Dos defectos del sincronizador que dejaron el Sheet contaminado:

1. **Desfase de columna.** `_indice()` contaba las claves internas del
   registro (`_fila`, `_norm`) como si fueran columnas de la hoja, así que el
   índice de `Resultado` quedaba corrido +1 y el veredicto se escribía en la
   columna vecina: `Marcador / notas` en Selecciones y `Marcador` en picks.
   10 de 13 selecciones quedaron con `Revisión manual` en la columna
   equivocada. Ahora `_indice()` cuenta solo los encabezados reales.

2. **Estado `in` no reconocido.** `resultado_pendiente_por_estado()` solo
   aceptaba `in progress` / `in_progress`, pero ESPN devuelve `in`. Ese
   estado caía en `Revisión manual` en vez de `Pendiente`.

Ambos tienen test de regresión (`tests/test_integration.py` y
`tests/test_markets.py`).

## Pestañas y secciones colapsables

El tablero esta dividido en 4 secciones plegables:

| Sección | Contenido |
|---|---|
| 📺 Marcador en vivo | Los 13 partidos de la jornada con su marcador |
| 🎟️ Mis boletos | Los 3 boletos con sus 13 selecciones |
| 📋 Quiniela original | Los 13 picks con su resultado |
| ℹ️ Ayuda | Cómo se usa y cómo se calculan los balances |

- La barra de pestañas es **fija (sticky)** al hacer scroll: siempre
  tienes el acceso rápido a la vista.
- Cada sección se abre y se cierra tocando su encabezado.
- El botón **Desplegar todo / Plegar todo** abre o cierra las cuatro.
- El estado se **guarda en `localStorage`**: la página se abre igual que
  como la dejaste.
- Los encabezados llevan contadores: partidos en vivo, boletos ganados y
  perdidos, y aciertos de la quiniela.
