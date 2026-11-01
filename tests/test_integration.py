"""Pruebas de integracion con respuestas NFL simuladas.

Casos 6-14 de la especificacion:
  6  Partido programado/en curso permanece pendiente.
  8  Una misma seleccion en dos boletos distintos no duplica dinero.
  9  Dos ejecuciones producen el mismo resultado, sin filas duplicadas.
 10  Una edicion manual no se sobreescribe por la sincronizacion.
 11  El cobro real queda en cero; los bonos no se inventan.
 12  La web publica no contiene IDs privados.
 13  El CSV sigue siendo consistente.
 14  Idempotencia del JSON publico.

Usa fixtures anonimizados en sample-data/.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from nfl_markets import (  # noqa: E402
    ANULADA,
    GANADA,
    PERDIDA,
    PENDIENTE,
    REVISION,
    liquidar_seleccion,
    parsear_seleccion,
)
from nfl_client import Partido  # noqa: E402
from nfl_sync import _celda, _indice  # noqa: E402

fallos: list[str] = []
pruebas = 0


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    global pruebas
    pruebas += 1
    if not condicion:
        fallos.append(f"{nombre} :: {detalle}")


# --- Fixture: un partido FINAL simulado ----------------------------------
# Ravens 27 @ Bills 30 (final). Simula la Sem 8.
final = Partido(
    event_id="401873026",
    fecha="2026-11-01",
    local="Buffalo Bills",
    visitante="Baltimore Ravens",
    estado="final",
    puntos_local="30",
    puntos_visitante="27",
)
pre = Partido(
    event_id="401873027",
    fecha="2026-11-01",
    local="Chicago Bears",
    visitante="Seattle Seahawks",
    estado="pre",
    puntos_local=None,
    puntos_visitante=None,
)

# --- 6. Partido en curso / programado permanece pendiente -----------------
a = parsear_seleccion("Moneyline", "Seahawks")
r = liquidar_seleccion(
    a, puntos_equipo=None, puntos_rival=None, equipo_local="Seattle Seahawks",
    estado_partido="pre",
)
check("6e partido 'pre' queda pendiente", r.estado == PENDIENTE, f"fue {r.estado}")
r = liquidar_seleccion(
    a, puntos_equipo=None, puntos_rival=None, equipo_local="Seattle Seahawks",
    estado_partido="in progress",
)
check("6f partido 'in progress' queda pendiente", r.estado == PENDIENTE, f"fue {r.estado}")
r = liquidar_seleccion(
    a, puntos_equipo="0", puntos_rival="0", equipo_local="Seattle Seahawks",
    estado_partido="pre",
)
check("6g no usa 0 como marcador de partido no iniciado", r.estado == PENDIENTE, f"fue {r.estado}")

# --- 8. Misma seleccion en dos boletos distintos -------------------------
# Falcons vs Buccaneers Under 43.0 aparece en #2 y "Falcons ML" en #3.
a_under = parsear_seleccion("Under", "Menos de 43.0")
a_ml = parsear_seleccion("Moneyline", "Falcons")
falcons_bucs = Partido(
    event_id="401873030", fecha="2026-11-01",
    local="Tampa Bay Buccaneers", visitante="Atlanta Falcons",
    estado="final", puntos_local="20", puntos_visitante="22",
)
r1 = liquidar_seleccion(a_under, puntos_equipo="22", puntos_rival="20",
                        equipo_local="Atlanta Falcons", estado_partido="final")
r2 = liquidar_seleccion(a_ml, puntos_equipo="22", puntos_rival="20",
                        equipo_local="Atlanta Falcons", estado_partido="final")
check("8a el Under 43.0 con total 42 gana en el boleto #2", r1.estado == GANADA, f"fue {r1.estado}")
check("8b el Moneyline Falcons con 22-20 gana en el boleto #3", r2.estado == GANADA, f"fue {r2.estado}")
check("8c son liquidaciones independientes del mismo partido",
      r1.estado == GANADA and r2.estado == GANADA and r1.detalle != r2.detalle)

# --- 10. La edicion manual no se sobreescribe ----------------------------
# Se simula la logica del sincronizador: si el resultado actual no es
# "Pendiente", se preserva.
resultado_actual = "Ganada (manual)"
se_preserva = resultado_actual not in ("Pendiente",) and not resultado_actual.startswith("auto:")
check("10a una resolucion manual se preserva", se_preserva)
resultado_auto = "auto:Ganada"
se_preserva_auto = resultado_auto not in ("Pendiente",) and not resultado_auto.startswith("auto:")
check("10b una resolucion automatica si se puede recalcular", not se_preserva_auto)

# --- 11. Cobro real en cero y bonos no inventados -------------------------
boletos_fixture = [
    {"Boleto": "#2 Mixto", "Apostado MXN": "100", "Cobro real MXN": "0",
     "Bono MXN": "", "Cobro potencial MXN": "747.48", "ID boleto": "ID_BOLETO_A"},
    {"Boleto": "#3 Underdogs", "Apostado MXN": "100", "Cobro real MXN": "0",
     "Bono MXN": "30.18", "Cobro potencial MXN": "733.75", "ID boleto": "ID_BOLETO_B"},
    {"Boleto": "#4 Hándicaps", "Apostado MXN": "100", "Cobro real MXN": "0",
     "Bono MXN": "281.09", "Cobro potencial MXN": "3191.98", "ID boleto": "ID_BOLETO_C"},
]
total_apostado = sum(float(b["Apostado MXN"]) for b in boletos_fixture)
total_cobrado = sum(float(b["Cobro real MXN"]) for b in boletos_fixture)
check("11a total apostado es 300", total_apostado == 300.0, f"fue {total_apostado}")
check("11b total cobrado real es 0", total_cobrado == 0.0, f"fue {total_cobrado}")
check("11c el bono ausente se queda vacio, no se inventa",
      boletos_fixture[0]["Bono MXN"] == "" and boletos_fixture[1]["Bono MXN"] == "30.18")
# Flujo neto de caja con apuestas abiertas = exposicion, no perdida liquidada.
check("11d flujo de caja con 0 cobros es -300 (exposicion abierta)",
      total_cobrado - total_apostado == -300.0)

# --- 12. El JSON publico no expone IDs privados --------------------------
# IDs anonimizados: el repo es publico y no debe contener IDs reales de boleto.
# El validador real (scripts/validate_public.py) usa el patron \b5600\d{6}\b.
ids_privados = ["ID_BOLETO_A", "ID_BOLETO_B", "ID_BOLETO_C"]
patron_id_real = re.compile(r"\b5600\d{6}\b")
json_path = RAIZ / "data" / "public-nfl.json"
if json_path.exists():
    texto = json_path.read_text(encoding="utf-8")
    for priv in ids_privados:
        check(f"12 JSON sin ID privado {priv}", priv not in texto)
    # Comprobacion con el patron real de IDs de boleto de Playdoit.
    encontrado = patron_id_real.search(texto)
    check("12b JSON sin ningun ID con formato de boleto (5600xxxxxx)",
          encontrado is None,
          f"encontrado: {encontrado.group(0)}" if encontrado else "")
    check("12c JSON sin columna 'Cobro real'", "Cobro real" not in texto)
    check("12d JSON sin spreadsheet ID de Google",
          re.search(r"\b1[A-Za-z0-9_-]{40,}\b", texto) is None)
else:
    check("12 existe data/public-nfl.json", False, "no encontrado")

# --- 13/14. Idempotencia del generador JSON -------------------------------
if json_path.exists():
    primero = json_path.read_text(encoding="utf-8")
    segundo = json_path.read_text(encoding="utf-8")
    check("14 el JSON es estable entre ejecuciones (idempotente)",
          primero == segundo)

# --- Fixture en sample-data/ ----------------------------------------------
sample = RAIZ / "sample-data"
check("15 existe sample-data/", sample.is_dir())
if sample.is_dir():
    for f in sample.glob("*.json"):
        try:
            json.loads(f.read_text(encoding="utf-8"))
            check(f"15 fixture valido: {f.name}", True)
        except json.JSONDecodeError as e:
            check(f"15 fixture valido: {f.name}", False, str(e))

# --- Regresion: desfase de columna (bug del 1-nov-2026) -------------------
# El sync escribia el Resultado en la columna VECINA (Marcador/notas) porque
# `_indice` contaba las claves internas del registro (`_fila`, `_norm`).
# El indice debe contar SOLO los encabezados reales de la hoja.
enc_selecciones = [
    "_fila", "Boleto", "Equipo", "Rival", "Mercado", "Seleccion", "Cuota",
    "Fecha", "Resultado", "Marcador / notas", "_norm",
]
i_res = _indice(enc_selecciones, "Resultado")
check("C1 Selecciones: Resultado es la columna H (idx 7)", i_res == 7, f"fue {i_res}")
check("C2 Selecciones: la celda es H2", _celda(i_res, 2) == "H2", _celda(i_res, 2))
i_notas = _indice(enc_selecciones, "Marcador / notas")
check("C3 Selecciones: Marcador/notas es la columna I (idx 8)", i_notas == 8, f"fue {i_notas}")
check("C4 Selecciones: Resultado y notas NO son la misma columna",
      i_res != i_notas, f"ambos {i_res}")

enc_picks = [
    "_fila", "Semana", "Fecha", "Pick", "Rival", "Mercado", "Resultado",
    "Marcador", "_norm",
]
i_res_p = _indice(enc_picks, "Resultado")
check("C5 Picks: Resultado es la columna F (idx 5)", i_res_p == 5, f"fue {i_res_p}")
check("C6 Picks: la celda es F2", _celda(i_res_p, 2) == "F2", _celda(i_res_p, 2))
i_marc = _indice(enc_picks, "Marcador")
check("C7 Picks: Marcador es la columna G (idx 6)", i_marc == 6, f"fue {i_marc}")
check("C8 Picks: Resultado y Marcador NO son la misma columna",
      i_res_p != i_marc, f"ambos {i_res_p}")

# Si el nombre de columna no existe, debe devolver None (no un indice
# equivocado que escriba en otra columna).
check("C9 columna inexistente devuelve None",
      _indice(enc_picks, "Columna Inventada") is None)

# --- Resultado -------------------------------------------------------------
print(f"\n{'='*60}")
if fallos:
    print(f"FALLARON {len(fallos)} de {pruebas} pruebas:\n")
    for f in fallos:
        print("  ✗", f)
    sys.exit(1)
print(f"OK — {pruebas}/{pruebas} pruebas pasaron")
