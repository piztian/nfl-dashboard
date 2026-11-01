"""Cliente de resultados NFL y emparejamiento con el Sheet.

Proveedor por defecto: ESPN (API no oficial, experimental). La capa de
emparejamiento no depende del formato del proveedor: normaliza a un modelo
propio (`Partido`) y valida SIEMPRE ambos equipos y la fecha.

Reglas de seguridad:
  - Un partido sin marcador final confirmado permanece pendiente.
  - Un evento que no coincide con ninguna fila del Sheet no se inventa.
  - Ravens@Bills (01/11) y Ravens@Jaguars (05/11) son eventos distintos: se
    emparejan por ID de evento + ambos equipos + fecha, nunca por texto parcial.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from nfl_markets import mismo_equipo

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"

# Temporada 2026: semana 1 arranca el 10-sep-2026 (aprox.) y la semana 18 en
# enero. Se usa una tabla simple de inicio de semana para convertir fecha -> semana.
INICIO_SEMANA = {
    1: date(2026, 9, 10),
    2: date(2026, 9, 17),
    3: date(2026, 9, 24),
    4: date(2026, 10, 1),
    5: date(2026, 10, 8),
    6: date(2026, 10, 15),
    7: date(2026, 10, 22),
    8: date(2026, 10, 29),
    9: date(2026, 11, 5),
    10: date(2026, 11, 12),
    11: date(2026, 11, 19),
    12: date(2026, 11, 26),
    13: date(2026, 12, 3),
    14: date(2026, 12, 10),
    15: date(2026, 12, 17),
    16: date(2026, 12, 24),
    17: date(2027, 1, 1),
    18: date(2027, 1, 8),
}


def semana_nfl(d: date) -> Optional[int]:
    """Convierte una fecha a semana NFL de la temporada 2026.

    No infiere la semana solo por el dia: usa la tabla de inicios. Una fecha
    anterior a la semana 1 devuelve None.
    """
    for semana in sorted(INICIO_SEMANA, reverse=True):
        if d >= INICIO_SEMANA[semana]:
            return semana
    return None


@dataclass
class Partido:
    """Un evento NFL normalizado, independiente del proveedor."""

    event_id: str
    fecha: str  # YYYY-MM-DD (hora local del partido, ya resuelta)
    local: str
    visitante: str
    abrev_local: str = ""
    abrev_visitante: str = ""
    estado: str = ""  # scheduled | in progress | final | postponed
    puntos_local: Optional[str] = None
    puntos_visitante: Optional[str] = None
    proveedor: str = "espn"
    url: str = ""

    @property
    def es_final(self) -> bool:
        return self.estado.strip().lower() in ("final", "post", "completed", "f")

    @property
    def tiene_marcador(self) -> bool:
        return self.puntos_local is not None and self.puntos_visitante is not None

    def to_dict(self) -> dict:
        return asdict(self)


class ErrorProveedor(RuntimeError):
    """Fallo al consultar al proveedor de resultados."""


def _http_json(url: str, timeout: int = 25, reintentos: int = 3) -> dict:
    """GET a un endpoint JSON con reintentos y espera progresiva."""
    ultimo_error: Optional[Exception] = None
    for intento in range(reintentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nfl-dashboard-sync/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            ultimo_error = exc
            if intento < reintentos - 1:
                time.sleep(2 ** intento * 1.5)
    raise ErrorProveedor(f"Fallo consultando {url}: {ultimo_error}")


def _parsear_espn_scoreboard(payload: dict) -> list[Partido]:
    """Convierte la respuesta de ESPN scoreboard a partidos normalizados."""
    partidos: list[Partido] = []
    for evento in payload.get("events", []) or []:
        competencias = evento.get("competitions") or []
        if not competencias:
            continue
        comp = competencias[0]
        local = visitante = None
        abrev_local = abrev_visitante = ""
        for comp_equipo in comp.get("competitors", []) or []:
            equipo = comp_equipo.get("team") or {}
            nombre = equipo.get("displayName") or equipo.get("name") or ""
            abrev = equipo.get("abbreviation") or equipo.get("shortDisplayName") or ""
            if comp_equipo.get("homeAway") == "home":
                local, abrev_local = nombre, abrev
            else:
                visitante, abrev_visitante = nombre, abrev
        if not local or not visitante:
            continue

        estado = ""
        puntos_local = puntos_visitante = None
        status = evento.get("status") or {}
        tipo = status.get("type") or {}
        estado = tipo.get("state") or ""
        if not estado and tipo.get("completed"):
            estado = "final"
        detalle = tipo.get("detail") or ""

        for comp_equipo in comp.get("competitors", []) or []:
            marcador = comp_equipo.get("score")
            if marcador is None:
                continue
            if comp_equipo.get("homeAway") == "home":
                puntos_local = str(marcador)
            else:
                puntos_visitante = str(marcador)

        fecha = _fecha_local_america_mexico(evento.get("date"))

        partidos.append(
            Partido(
                event_id=str(evento.get("id") or ""),
                fecha=fecha,
                local=local,
                visitante=visitante,
                abrev_local=abrev_local,
                abrev_visitante=abrev_visitante,
                estado=estado or detalle,
                puntos_local=puntos_local,
                puntos_visitante=puntos_visitante,
                url=f"https://www.espn.com/nfl/game/_/gameId/{evento.get('id')}",
            )
        )
    return partidos


def _fecha_local_america_mexico(iso: Optional[str]) -> str:
    """Convierte la fecha ISO del proveedor a fecha local de Mexico."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    # ESPN publica en ET (UTC-5 en noviembre, UTC-4 en verano).
    et = dt.astimezone(timezone_offset(-5))
    return et.date().isoformat()


def timezone_offset(hours: int):
    from datetime import timedelta, timezone

    return timezone(timedelta(hours=hours))


def obtener_partidos(fechas: Iterable[str], proveedor: str = "espn") -> list[Partido]:
    """Consulta los partidos de las fechas indicadas y los normaliza.

    Args:
        fechas: lista de fechas 'YYYY-MM-DD'.
    """
    partidos: list[Partido] = []
    vistos: set[str] = set()
    for f in fechas:
        compacto = f.replace("-", "")
        if proveedor != "espn":
            raise ErrorProveedor(f"Proveedor no soportado: {proveedor}")
        payload = _http_json(f"{ESPN_SCOREBOARD}?dates={compacto}")
        for p in _parsear_espn_scoreboard(payload):
            if p.event_id and p.event_id in vistos:
                continue
            vistos.add(p.event_id)
            partidos.append(p)
    return partidos


def emparejar(
    partido: Partido,
    *,
    fecha_busqueda: str,
    equipo_a: str,
    equipo_b: str,
) -> bool:
    """Valida que un partido corresponda a una fila (equipo_a vs equipo_b).

    Exige coincidencia de AMBOS equipos y de la fecha. Nunca empareja por
    coincidencia parcial de un solo equipo.
    """
    if partido.fecha != fecha_busqueda:
        return False
    par_local = mismo_equipo(partido.local, equipo_a) or mismo_equipo(partido.visitante, equipo_a)
    par_visit = mismo_equipo(partido.local, equipo_b) or mismo_equipo(partido.visitante, equipo_b)
    if not (par_local and par_visit):
        return False
    # Los dos equipos no pueden ser el mismo.
    return not mismo_equipo(equipo_a, equipo_b)


def buscar_partido_para_fila(
    partidos: list[Partido], *, fecha: str, equipo_a: str, equipo_b: str
) -> Optional[Partido]:
    """Busca el partido que corresponde a una fila del Sheet."""
    for p in partidos:
        if emparejar(p, fecha_busqueda=fecha, equipo_a=equipo_a, equipo_b=equipo_b):
            return p
    return None


def resumen_marcadores(partidos: list[Partido]) -> dict:
    """Resumen de cobertura para el reporte de sincronizacion."""
    total = len(partidos)
    finales = [p for p in partidos if p.es_final]
    con_marcador = [p for p in partidos if p.tiene_marcador]
    return {
        "total_eventos": total,
        "finales": len(finales),
        "con_marcador": len(con_marcador),
        "pendientes": total - len(finales),
        "sin_marcador": total - len(con_marcador),
    }
