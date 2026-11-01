"""Reglas de liquidacion de mercados NFL.

Fuente unica de verdad para decidir el estado de una seleccion (pierna de
parlay) o de un pick independiente, a partir del marcador final del partido.

Reglas implementadas (especificacion OPENCLAW_NFL_2026_IMPLEMENTACION.md):

Moneyline  Se compara el ganador final. Un empate (no posible en NFL con
           overtime, pero el proveedor puede reportarlo) se marca para
           revision manual en lugar de inventar un resultado.

Spread     margen_del_equipo_elegido + spread > 0  -> Ganada
           margen_del_equipo_elegido + spread < 0  -> Perdida
           margen_del_equipo_elegido + spread == 0 -> Push / Anulada
           Ejemplos: Jaguars -10.0 ganar por 10 => push.
                     Ravens +3.0 perder por 3      => push.
                     Raiders +1.5 perder por 1     => gana.

Over/Under total < linea -> el lado Under gana
           total == linea  -> push (solo en lineas enteras, ej. 43.0)
           total > linea  -> el lado Under pierde
           Ejemplos: Under 43.0 con 42 gana / 43 push / 44 pierde.
                     Under 43.5 con 43 gana / 44 pierde.

Reglas transversales:
  - Un partido sin marcador final confirmado permanece "Pendiente".
  - Nunca se convierte un marcador ausente en 0.
  - La prorroga (overtime) esta incluida en el marcador final del proveedor.
  - El estado "Revisión manual" se usa cuando hay discrepancia o falta de
    informacion confiable; nunca se adivina.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

# --- Estados de una seleccion (pierna de parlay) -------------------------
PENDIENTE = "Pendiente"
GANADA = "Ganada"
PERDIDA = "Perdida"
ANULADA = "Anulada"
REVISION = "Revisión manual"

# --- Estados de un pick independiente -------------------------------------
PICK_PENDIENTE = "Pendiente"
PICK_ACERTADO = "Acertado"
PICK_FALLADO = "Fallado"
PICK_ANULADO = "Anulado"
PICK_REVISION = "Revisión manual"

PUSH = "push"


@dataclass(frozen=True)
class Resultado:
    """Resultado de liquidar un mercado contra un marcador final."""

    estado: str
    detalle: str = ""
    push: bool = False

    @property
    def es_push(self) -> bool:
        return self.push


def _to_int(valor: Optional[str]) -> Optional[int]:
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    try:
        return int(float(texto))
    except (TypeError, ValueError):
        return None


def sin_marcador() -> Resultado:
    """Partido sin marcador final confirmado: permanece pendiente."""
    return Resultado(PENDIENTE, "Sin marcador final confirmado")


def resultado_pendiente_por_estado(estado_partido: str) -> Resultado:
    """Clasifica el estado del evento segun el proveedor."""
    estado = (estado_partido or "").strip().lower()
    if estado in ("final", "post", "completed", "f"):
        return Resultado(PENDIENTE, "Marcador final disponible, falta liquidar")
    if estado in ("scheduled", "pre", "in progress", "in_progress", "halftime", "postponed"):
        return Resultado(PENDIENTE, f"Partido en estado '{estado_partido}'")
    return Resultado(REVISION, f"Estado de proveedor desconocido: '{estado_partido}'")


def liquidar_moneyline(
    puntos_equipo: Optional[str],
    puntos_rival: Optional[str],
    lado_equipo: str,
    *,
    hay_prorroga: bool = True,
) -> Resultado:
    """Liquida un mercado Moneyline.

    Args:
        puntos_equipo: puntos finales del equipo elegido.
        puntos_rival: puntos finales del rival.
        lado_equipo: nombre normalizado del equipo elegido.
    """
    a = _to_int(puntos_equipo)
    b = _to_int(puntos_rival)
    if a is None or b is None:
        return sin_marcador()
    if a == b:
        return Resultado(REVISION, f"Empate {a}-{b} en Moneyline; revisar reglas de la casa")
    if a > b:
        return Resultado(GANADA, f"{lado_equipo} {a}-{b}")
    return Resultado(PERDIDA, f"{lado_equipo} pierde {a}-{b}")


def liquidar_spread(
    puntos_equipo: Optional[str],
    puntos_rival: Optional[str],
    spread: float,
    lado_equipo: str,
) -> Resultado:
    """Liquida un mercado de handicap (spread).

    Args:
        spread: handicap del equipo elegido (negativo = favorito).
    """
    a = _to_int(puntos_equipo)
    b = _to_int(puntos_rival)
    if a is None or b is None:
        return sin_marcador()
    margen = a - b
    ajustado = margen + spread
    if ajustado > 0:
        return Resultado(GANADA, f"{lado_equipo} {a}-{b}, spread {spread:+g} cubre")
    if ajustado < 0:
        return Resultado(PERDIDA, f"{lado_equipo} {a}-{b}, spread {spread:+g} no cubre")
    return Resultado(ANULADA, f"{lado_equipo} {a}-{b}, push (spread {spread:+g})", push=True)


def liquidar_total(
    puntos_equipo: Optional[str],
    puntos_rival: Optional[str],
    linea: float,
    lado: str,
) -> Resultado:
    """Liquida un mercado Over/Under de total de puntos.

    Args:
        linea: linea del mercado (p. ej. 43.0 o 43.5).
        lado: "Under" o "Over".
    """
    a = _to_int(puntos_equipo)
    b = _to_int(puntos_rival)
    if a is None or b is None:
        return sin_marcador()
    total = a + b
    lado = (lado or "Under").strip().capitalize()
    if lado not in ("Over", "Under"):
        return Resultado(REVISION, f"Lado Over/Under desconocido: '{lado}'")

    if lado == "Under":
        if total < linea:
            return Resultado(GANADA, f"Total {total} < {linea:g} (Under)")
        if total > linea:
            return Resultado(PERDIDA, f"Total {total} > {linea:g} (Under)")
        return Resultado(ANULADA, f"Total {total} = {linea:g}, push", push=True)

    # Over
    if total > linea:
        return Resultado(GANADA, f"Total {total} > {linea:g} (Over)")
    if total < linea:
        return Resultado(PERDIDA, f"Total {total} < {linea:g} (Over)")
    return Resultado(ANULADA, f"Total {total} = {linea:g}, push", push=True)


# --- Parseo de la columna "Seleccion" del Sheet ----------------------------

_RE_UNDER = re.compile(r"menos\s+de\s+([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_RE_OVER = re.compile(r"mas\s+de\s+([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_RE_UNDER_BARE = re.compile(r"^\s*under\s+([0-9]+(?:\.[0-9]+)?)\s*$", re.IGNORECASE)
_RE_OVER_BARE = re.compile(r"^\s*over\s+([0-9]+(?:\.[0-9]+)?)\s*$", re.IGNORECASE)
_RE_SPREAD = re.compile(r"([+-][0-9]+(?:\.[0-9]+)?)\s*$")


def _sin_acentos(texto: str) -> str:
    """Quita acentos y pasa a minusculas para comparar de forma tolerante."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c)).lower()


def parsear_seleccion(mercado: str, seleccion: str) -> dict:
    """Convierte (Mercado, Seleccion) del Sheet en una apuesta tipada.

    Formatos soportados (los que usa la pestana Selecciones):
      Moneyline + "Bengals"          -> lado = Bengals
      Spread    + "Lions -3.5"       -> spread = -3.5, lado = Lions
      Under     + "Menos de 43.0"   -> linea = 43.0, lado = Under
      Over      + "Mas de 45.5"     -> linea = 45.5, lado = Over
    """
    mercado = (mercado or "").strip()
    seleccion = (seleccion or "").strip()
    base = {"mercado": mercado, "linea": None, "spread": None, "lado": None, "equipo": None}

    m = mercado.lower()
    if m.startswith("moneyline") or m.startswith("ganador"):
        base["lado"] = "moneyline"
        base["equipo"] = seleccion
        return base

    if m.startswith("spread") or m.startswith("hándicap") or m.startswith("handicap"):
        match = _RE_SPREAD.search(seleccion)
        if not match:
            base["lado"] = "spread"
            base["equipo"] = seleccion
            return base
        spread = float(match.group(1))
        base["spread"] = spread
        base["lado"] = "spread"
        base["equipo"] = _RE_SPREAD.sub("", seleccion).strip() or None
        return base

    if m.startswith("under") or m.startswith("over") or m.startswith("total"):
        # Se normalizan acentos para que "Mas de" y "Más de" se interpreten
        # igual (el Sheet alterna entre ambas formas).
        plano = _sin_acentos(seleccion)
        match = (_RE_UNDER.search(plano) or _RE_OVER.search(plano)
                 or _RE_UNDER_BARE.search(plano) or _RE_OVER_BARE.search(plano))
        if match:
            base["linea"] = float(match.group(1))
        base["lado"] = "under" if m.startswith("under") else "over"
        if base["lado"] == "over" and (_RE_UNDER.search(plano) or _RE_UNDER_BARE.search(plano)):
            base["lado"] = "under"
        return base

    # Formato no reconocido: se deja para revision manual, nunca se adivina.
    base["lado"] = "desconocido"
    return base


def liquidar_seleccion(
    apuesta: dict,
    *,
    puntos_equipo: Optional[str],
    puntos_rival: Optional[str],
    equipo_local: Optional[str] = None,
    estado_partido: str = "final",
) -> Resultado:
    """Liquida una seleccion de la pestana Selecciones.

    Args:
        apuesta: salida de parsear_seleccion.
        puntos_equipo: puntos del equipo local del partido.
        puntos_rival: puntos del equipo visitante.
        equipo_local: nombre del equipo local (para resolver el lado).
    """
    lado = apuesta.get("lado")
    if lado in (None, "desconocido"):
        return Resultado(REVISION, "Mercado o seleccion no reconocida")

    # Solo se liquida si el proveedor reporta final. Cualquier otro estado
    # (scheduled, in progress, postponed) permanece pendiente.
    estado = resultado_pendiente_por_estado(estado_partido)
    proveedor_reporta_final = estado.estado == PENDIENTE and "falta liquidar" in estado.detalle
    if not proveedor_reporta_final:
        return estado

    if lado == "moneyline":
        equipo = apuesta.get("equipo")
        return _liquidar_moneyline_por_lado(
            equipo, equipo_local, puntos_local=puntos_equipo, puntos_visitante=puntos_rival
        )

    if lado == "spread":
        equipo = apuesta.get("equipo")
        lado_equipo, pe, pr = _resolver_lado(equipo, equipo_local, puntos_equipo, puntos_rival)
        if lado_equipo is None:
            return Resultado(REVISION, "No se pudo resolver el equipo elegido del spread")
        if apuesta.get("spread") is None:
            return Resultado(REVISION, "No se pudo interpretar el spread de la seleccion")
        return liquidar_spread(pe, pr, apuesta["spread"], lado_equipo)

    # over/under: los puntos son la suma, no importan los lados
    if apuesta.get("linea") is None:
        return Resultado(REVISION, "No se pudo interpretar la linea del total")
    total_lado = "Under" if lado == "under" else "Over"
    return liquidar_total(puntos_equipo, puntos_rival, apuesta["linea"], total_lado)


def _resolver_lado(
    equipo: Optional[str],
    equipo_local: Optional[str],
    puntos_local: Optional[str],
    puntos_visitante: Optional[str],
):
    """Resuelve si el equipo elegido es local o visitante.

    Returns:
        (nombre_equipo, puntos_del_equipo, puntos_del_rival)
    """
    if not equipo or not equipo_local:
        return None, None, None
    eq = normalizar_equipo(equipo)
    loc = normalizar_equipo(equipo_local)
    if eq == loc:
        return equipo, puntos_local, puntos_visitante
    return equipo, puntos_visitante, puntos_local


def _liquidar_moneyline_por_lado(
    equipo: Optional[str],
    equipo_local: Optional[str],
    *,
    puntos_local: Optional[str],
    puntos_visitante: Optional[str],
) -> Resultado:
    if not equipo or not equipo_local:
        return Resultado(REVISION, "No se pudo resolver el equipo elegido del Moneyline")
    nombre, pe, pr = _resolver_lado(equipo, equipo_local, puntos_local, puntos_visitante)
    return liquidar_moneyline(pe, pr, nombre)


# --- Normalizacion de alias de equipos -------------------------------------

_ALIAS = {
    "jac": "jax",
    "jaguars": "jax",
    "jacksonville": "jax",
    "wsh": "was",
    "washington": "was",
    "commanders": "was",
    "lv": "lv",
    "raiders": "lv",
    "oakland": "lv",
    "la": "lar",
    "rams": "lar",
    "los angeles rams": "lar",
    "chargers": "lac",
    "los angeles chargers": "lac",
    "49ers": "sf",
    "san francisco": "sf",
    "tb": "tb",
    "buccaneers": "tb",
    "bucs": "tb",
    "kc": "kc",
    "chiefs": "kc",
    "gb": "gb",
    "packers": "gb",
    "tb buccaneers": "tb",
    "new england": "ne",
    "patriots": "ne",
    "nyj": "nyj",
    "jets": "nyj",
    "nfl": "",
}


# Abreviaturas oficiales por equipo (clave canonica).
_ABREV = {
    "ARI": "ari", "ATL": "atl", "BAL": "bal", "BUF": "buf", "CAR": "car",
    "CHI": "chi", "CIN": "cin", "CLE": "cle", "DAL": "dal", "DEN": "den",
    "DET": "det", "GB": "gb", "HOU": "hou", "IND": "ind", "JAX": "jax",
    "KC": "kc", "LV": "lv", "LAC": "lac", "LAR": "lar", "MIA": "mia",
    "MIN": "min", "NE": "ne", "NO": "no", "NYG": "nyg", "NYJ": "nyj",
    "PHI": "phi", "PIT": "pit", "SEA": "sea", "SF": "sf", "TB": "tb",
    "TEN": "ten", "WAS": "was",
}

# Apodos que el Sheet o el proveedor pueden usar -> abreviatura canonica.
_APODOS = {
    "jaguars": "jax", "jacksonville": "jax", "jac": "jax",
    "bills": "buf", "buffalo": "buf",
    "ravens": "bal", "baltimore": "bal",
    "colts": "ind", "indianapolis": "ind",
    "bengals": "cin", "cincinnati": "cin",
    "titans": "ten", "tennessee": "ten",
    "rams": "lar", "los angeles rams": "lar",
    "chargers": "lac", "los angeles chargers": "lac",
    "falcons": "atl", "buccaneers": "tb", "bucs": "tb",
    "patriots": "ne", "dolphins": "mia",
    "raiders": "lv",
    "lions": "det", "vikings": "min",
    "steelers": "pit", "browns": "cle",
    "chiefs": "kc", "broncos": "den",
    "cowboys": "dal", "cardinals": "ari",
    "commanders": "was", "washington": "was", "redskins": "was",
    "eagles": "phi",
    "seahawks": "sea", "bears": "chi",
    "jets": "nyj", "giants": "nyg",
    "texans": "hou",
    # Nombres con numero: la normalizacion elimina los digitos, asi que se
    # resuelve el nombre completo ("San Francisco 49ers" -> "san francisco").
    "49ers": "sf", "forty niners": "sf",
    "san francisco": "sf", "san francisco ers": "sf",
}


def normalizar_equipo(nombre: Optional[str]) -> str:
    """Normaliza un nombre de equipo a su abreviatura canonica.

    Maneja nombres largos ("Baltimore Ravens"), abreviaturas ("BAL") y
    apodos ("Jaguars" -> "jax"), de modo que dos referencias al mismo
    equipo siempre produzcan la misma clave.

    Los digitos se eliminan ANTES de resolver, por lo que "49ers" queda como
    "ers": los nombres con numero se resuelven por su forma completa
    ("San Francisco 49ers" -> "san francisco" -> "sf").
    """
    if not nombre:
        return ""
    texto = str(nombre).strip().lower()
    # Conserva los digitos para casos como "49ers" hasta resolver el alias.
    crudo = re.sub(r"\s+", " ", texto).strip()
    if crudo in _ABREV:
        return _ABREV[crudo]
    if crudo in _APODOS:
        return _APODOS[crudo]
    texto = re.sub(r"[^a-z ]+", " ", crudo)
    texto = re.sub(r"\s+", " ", texto).strip()
    if not texto:
        return ""
    if texto in _ABREV:
        return _ABREV[texto]
    if texto in _APODOS:
        return _APODOS[texto]
    # Multi-palabra: intentar el ultimo token ("Baltimore Ravens" -> "ravens").
    partes = texto.split()
    if len(partes) > 1:
        ultimo = partes[-1]
        if ultimo in _APODOS:
            return _APODOS[ultimo]
        if ultimo in _ABREV:
            return _ABREV[ultimo]
        # "san francisco" (tras quitar digitos de "49ers")
        if len(partes) >= 2 and " ".join(partes[-2:]) in _APODOS:
            return _APODOS[" ".join(partes[-2:])]
    return texto


def mismo_equipo(a: Optional[str], b: Optional[str]) -> bool:
    """Compara dos equipos por alias normalizado."""
    na, nb = normalizar_equipo(a), normalizar_equipo(b)
    if not na or not nb:
        return False
    return na == nb
