"""Pruebas de reglas de mercado (casos 1-7 de la especificacion).

Ejecutar con:  python3 -m pytest tests/ -v
o sin pytest:   python3 tests/test_markets.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from nfl_markets import (  # noqa: E402
    ANULADA,
    GANADA,
    PERDIDA,
    PENDIENTE,
    REVISION,
    liquidar_moneyline,
    liquidar_spread,
    liquidar_total,
    parsear_seleccion,
    mismo_equipo,
)

fallos: list[str] = []
pruebas = 0


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    global pruebas
    pruebas += 1
    if not condicion:
        fallos.append(f"{nombre} :: {detalle}")


# --- 1. Under 43.0 -------------------------------------------------------
r = liquidar_total("21", "21", 43.0, "Under")
check("1a Under 43.0 con 42 gana", r.estado == GANADA, f"fue {r.estado}")
r = liquidar_total("21", "22", 43.0, "Under")
check("1b Under 43.0 con 43 push", r.estado == ANULADA and r.push, f"fue {r.estado} push={r.push}")
r = liquidar_total("22", "22", 43.0, "Under")
check("1c Under 43.0 con 44 pierde", r.estado == PERDIDA, f"fue {r.estado}")

# --- 2. Under 43.5 -------------------------------------------------------
r = liquidar_total("21", "22", 43.5, "Under")
check("2a Under 43.5 con 43 gana", r.estado == GANADA, f"fue {r.estado}")
r = liquidar_total("22", "22", 43.5, "Under")
check("2b Under 43.5 con 44 pierde", r.estado == PERDIDA, f"fue {r.estado}")

# --- 3. Jaguars -10.0 ----------------------------------------------------
r = liquidar_spread("24", "15", -10.0, "Jaguars")
check("3a Jaguars -10 ganando por 9 pierde", r.estado == PERDIDA, f"fue {r.estado}")
r = liquidar_spread("25", "15", -10.0, "Jaguars")
check("3b Jaguars -10 ganando por 10 push", r.estado == ANULADA and r.push, f"fue {r.estado}")
r = liquidar_spread("26", "15", -10.0, "Jaguars")
check("3c Jaguars -10 ganando por 11 gana", r.estado == GANADA, f"fue {r.estado}")

# --- 4. Raiders +1.5 -----------------------------------------------------
r = liquidar_spread("10", "11", 1.5, "Raiders")
check("4a Raiders +1.5 perdiendo por 1 gana", r.estado == GANADA, f"fue {r.estado}")
r = liquidar_spread("10", "12", 1.5, "Raiders")
check("4b Raiders +1.5 perdiendo por 2 pierde", r.estado == PERDIDA, f"fue {r.estado}")

# --- 5. Ravens +3.0 ------------------------------------------------------
r = liquidar_spread("20", "23", 3.0, "Ravens")
check("5a Ravens +3.0 perdiendo por 3 push", r.estado == ANULADA and r.push, f"fue {r.estado}")
r = liquidar_spread("20", "24", 3.0, "Ravens")
check("5b Ravens +3.0 perdiendo por 4 pierde", r.estado == PERDIDA, f"fue {r.estado}")

# --- 6. Sin marcador final -> pendiente, nunca 0 -------------------------
r = liquidar_total(None, None, 43.0, "Under")
check("6a sin marcador queda pendiente", r.estado == PENDIENTE, f"fue {r.estado}")
r = liquidar_total("", "", 43.0, "Under")
check("6b marcador vacio queda pendiente", r.estado == PENDIENTE, f"fue {r.estado}")
r = liquidar_spread(None, "15", -10.0, "Jaguars")
check("6c spread sin marcador queda pendiente", r.estado == PENDIENTE, f"fue {r.estado}")
r = liquidar_moneyline(None, None, "Bengals")
check("6d moneyline sin marcador queda pendiente", r.estado == PENDIENTE, f"fue {r.estado}")

# --- 7. Ravens@Bills (01/11) != Ravens@Jaguars (05/11) -------------------
from nfl_client import Partido, buscar_partido_para_fila, emparejar  # noqa: E402

bill = Partido(
    event_id="401873026",
    fecha="2026-11-01",
    local="Buffalo Bills",
    visitante="Baltimore Ravens",
    estado="final",
    puntos_local="30",
    puntos_visitante="27",
)
jagu = Partido(
    event_id="401874999",
    fecha="2026-11-05",
    local="Jacksonville Jaguars",
    visitante="Baltimore Ravens",
    estado="scheduled",
    puntos_local=None,
    puntos_visitante=None,
)
emp_jagu = buscar_partido_para_fila([bill, jagu], fecha="2026-11-05", equipo_a="Ravens", equipo_b="Jaguars")
emp_bill = buscar_partido_para_fila([bill, jagu], fecha="2026-11-01", equipo_a="Ravens", equipo_b="Bills")
check(
    "7a la fila Ravens-Jaguars 05/11 NO resuelve al evento Ravens-Bills",
    (emp_jagu is None) or emp_jagu.event_id != "401873026",
    f"fue {emp_jagu}",
)
check(
    "7b Ravens-Jaguars 05/11 SI casa con su fila",
    emp_jagu is not None and emp_jagu.event_id == "401874999",
    f"fue {emp_jagu}",
)
check(
    "7c Ravens-Bills 01/11 SI casa con su fila",
    emp_bill is not None and emp_bill.event_id == "401873026",
    f"fue {emp_bill}",
)
check(
    "7d la fecha manda: mismo par de equipos en otra fecha no empareja",
    not emparejar(bill, fecha_busqueda="2026-11-05", equipo_a="Ravens", equipo_b="Bills"),
)

# --- Parseo de la columna Seleccion ---------------------------------------
a = parsear_seleccion("Moneyline", "Bengals")
check("P1 moneyline", a["lado"] == "moneyline" and a["equipo"] == "Bengals", str(a))
a = parsear_seleccion("Spread", "Lions -3.5")
check("P2 spread", a["lado"] == "spread" and a["spread"] == -3.5 and a["equipo"] == "Lions", str(a))
a = parsear_seleccion("Spread", "Jaguars -10.0")
check("P3 spread -10.0", a["spread"] == -10.0, str(a))
a = parsear_seleccion("Spread", "Raiders +1.5")
check("P4 spread +1.5", a["spread"] == 1.5 and a["equipo"] == "Raiders", str(a))
a = parsear_seleccion("Spread", "Ravens +3.0")
check("P5 spread +3.0", a["spread"] == 3.0, str(a))
a = parsear_seleccion("Under", "Menos de 43.0")
check("P6 under 43.0", a["lado"] == "under" and a["linea"] == 43.0, str(a))
a = parsear_seleccion("Under", "Menos de 43.5")
check("P7 under 43.5", a["lado"] == "under" and a["linea"] == 43.5, str(a))
a = parsear_seleccion("Under", "Menos de 43")
check("P8 under entero 43", a["linea"] == 43.0, str(a))

# --- Alias de equipos -----------------------------------------------------
check("A1 JAC/JAX", mismo_equipo("Jaguars", "JAX"))
check("A2 WSH/WAS", mismo_equipo("Commanders", "Washington"))
check("A3 LV", mismo_equipo("Raiders", "LV"))
check("A4 no confunde Bills con Jaguars", not mismo_equipo("Bills", "Jaguars"))
check("A5 no confunde Ravens con Jaguars", not mismo_equipo("Ravens", "Jaguars"))

# --- Resultado principal -------------------------------------------------
print(f"\n{'='*60}")
if fallos:
    print(f"FALLARON {len(fallos)} de {pruebas} pruebas:\n")
    for f in fallos:
        print("  ✗", f)
    sys.exit(1)
print(f"OK — {pruebas}/{pruebas} pruebas pasaron")
