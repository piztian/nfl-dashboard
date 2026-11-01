#!/usr/bin/env python3
"""Espera a que termine un partido y reporta el estado de un boleto.

Uso:
    python3 scripts/esperar_boleto.py

Espera a que termine el partido de Patriots y reporta el estado del #2.

El boleto #2 Mixto tiene 5 piernas:
  - Bengals Moneyline  (ya final, ganada)
  - Jaguars Moneyline  (ya final, ganada)
  - Falcons Under 43.0 (ya final, ganada)
  - Rams Moneyline    (en juego)
  - Patriots Under 43.5 (en juego)  <- este es el que dispara el aviso

Espera a que Patriots quede en estado final y calcula el estado real con las
funciones del backend (scripts/nfl_markets.py), no con una reimplementacion.
"""
import json
import os
import sys
import time
import urllib.request

RAIZ = "/Users/cristianbarajas/clawd/repos/nfl-dashboard"
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

from nfl_markets import (  # noqa: E402
    parsear_seleccion,
    liquidar_moneyline,
    liquidar_spread,
    liquidar_total,
    _resolver_lado,
    normalizar_equipo,
)
from nfl_client import _parsear_espn_scoreboard  # noqa: E402

URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
MAX_INTENTOS = 200  # 200 * 20 s = ~66 min
ESPERA = 20
PATRIOTS = ("New England Patriots", "Miami Dolphins")


def obtener():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    payload = json.loads(urllib.request.urlopen(req, timeout=25).read())
    return _parsear_espn_scoreboard(payload)


def buscar(partidos, away, home):
    return next(
        (
            x
            for x in partidos
            if normalizar_equipo(x.local) == normalizar_equipo(home)
            and normalizar_equipo(x.visitante) == normalizar_equipo(away)
        ),
        None,
    )


def liquidar(sel, partidos):
    apuesta = parsear_seleccion(sel["mercado"], sel["seleccion"])
    lado = apuesta.get("lado")
    e = normalizar_equipo(sel["equipo"])
    r = normalizar_equipo(sel["rival"])
    p = next(
        (
            x
            for x in partidos
            if (normalizar_equipo(x.local) == e and normalizar_equipo(x.visitante) == r)
            or (normalizar_equipo(x.local) == r and normalizar_equipo(x.visitante) == e)
        ),
        None,
    )
    if p is None:
        return "SIN PARTIDO", ""
    if not p.tiene_marcador:
        return "SIN EMPEZAR", ""
    pl, pv = p.puntos_local, p.puntos_visitante
    if lado == "moneyline":
        nombre, pe, pr = _resolver_lado(apuesta.get("equipo"), p.local, pl, pv)
        res = liquidar_moneyline(pe, pr, nombre)
    elif lado == "spread":
        nombre, pe, pr = _resolver_lado(apuesta.get("equipo"), p.local, pl, pv)
        res = liquidar_spread(pe, pr, apuesta["spread"], nombre)
    else:
        res = liquidar_total(pl, pv, apuesta["linea"], "Under" if lado == "under" else "Over")
    estado = {"Ganada": "GANADA", "Perdida": "PERDIDA", "Anulada": "PUSH"}.get(
        res.estado, res.estado
    )
    return estado, f"{p.visitante} {pv} - {pl} {p.local}"


def main():
    intentos = 0
    partidos = []
    while intentos < MAX_INTENTOS:
        intentos += 1
        try:
            partidos = obtener()
        except Exception as e:  # noqa: BLE001
            print(f"[{intentos}] error consultando proveedor: {e}", flush=True)
            time.sleep(ESPERA)
            continue

        p = buscar(partidos, *PATRIOTS)
        if p is None:
            print(f"[{intentos}] partido de Patriots no encontrado", flush=True)
        elif p.es_final:
            print(f"[{intentos}] FINAL: {p.visitante} {p.puntos_visitante} - {p.puntos_local} {p.local}", flush=True)
            break
        else:
            print(f"[{intentos}] esperando: {p.estado} ({p.puntos_visitante}-{p.puntos_local}) {p.estado}", flush=True)
        time.sleep(ESPERA)
    else:
        print("TIMEOUT: el partido no termino a tiempo", flush=True)
        sys.exit(2)

    data = json.load(open(os.path.join(RAIZ, "data", "public-nfl.json")))
    print("\n=== BOLETO #2 MIXTO ===", flush=True)
    g = pe = pe_ = 0
    for s in data["selecciones"]:
        if s.get("boleto") != "#2 Mixto":
            continue
        estado, detalle = liquidar(s, partidos)
        if estado == "GANADA":
            g += 1
        elif estado == "PERDIDA":
            pe += 1
        else:
            pe_ += 1
        print(
            f"  {estado:12s} {s['equipo']:10s} {s['mercado']:10s} {s['seleccion']:16s} | {detalle}",
            flush=True,
        )
    print(f"\n  RESUMEN: {g} ganadas, {pe} perdidas, {pe_} pendientes", flush=True)

    # Estado del partido de Rams (la otra pierna viva del #2)
    r = buscar(partidos, "Los Angeles Chargers", "Los Angeles Rams")
    if r:
        estado_r = "FINAL" if r.es_final else r.estado
        print(f"\n  Rams: {r.visitante} {r.puntos_visitante} - {r.puntos_local} {r.local} [{estado_r}]", flush=True)

    print("LISTO_PARA_MANDAR", flush=True)


if __name__ == "__main__":
    main()
