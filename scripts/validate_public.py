"""Verifica que el JSON publico no contenga datos privados.

Es la ultima barrera antes de publicar en un repositorio publico. Si algo
falla, el workflow de sincronizacion aborta y NO se publica nada.

Uso:
    python3 scripts/validate_public.py data/public-nfl.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Patrones de datos que NUNCA deben aparecer en el artefacto publico.
PATRONES_PROHIBIDOS = {
    "ID de boleto de Playdoit": re.compile(r"\b5600\d{6}\b"),
    "ID de spreadsheet de Google": re.compile(r"\b1[A-Za-z0-9_-]{40,}\b"),
    "correo electronico": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "columna 'Cobro real'": re.compile(r"Cobro real", re.IGNORECASE),
    "columna 'ID boleto'": re.compile(r"ID boleto", re.IGNORECASE),
    "token de GitHub": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "clave privada JSON": re.compile(r'"private_key"'),
    "API key de Google": re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    "refresh token de OAuth": re.compile(r"1//[0-9A-Za-z_\-]{40,}"),
}

# Campos permitidos por bloque.
CAMPOS_PERMITIDOS = {
    "boletos_publicos": {"etiqueta", "estado"},
    "selecciones": {
        "semana", "fecha", "equipo", "rival", "mercado", "seleccion",
        "cuota_capturada", "resultado", "marcador", "boleto",
    },
    "picks": {"semana", "fecha", "pick", "rival", "resultado", "marcador"},
}


def validar(ruta: Path) -> list[str]:
    problemas: list[str] = []
    if not ruta.exists():
        return [f"No existe el archivo {ruta}"]

    texto = ruta.read_text(encoding="utf-8")
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as exc:
        return [f"El JSON no es valido: {exc}"]

    for nombre, patron in PATRONES_PROHIBIDOS.items():
        if patron.search(texto):
            match = patron.search(texto)
            problemas.append(f"Contiene {nombre}: {match.group(0)[:24]}...")

    for bloque, permitidos in CAMPOS_PERMITIDOS.items():
        for item in datos.get(bloque, []) or []:
            extras = set(item.keys()) - permitidos
            if extras:
                problemas.append(f"Campos no permitidos en {bloque}: {sorted(extras)}")

    # El resumen publico solo puede llevar agregados.
    resumen = datos.get("resumen_publico", {}) or {}
    permitidos_resumen = {
        "boletos_confirmados", "apostado_total_mxn", "cobro_potencial_total_mxn",
        "cobro_real_total_mxn", "selecciones", "picks",
    }
    extras = set(resumen.keys()) - permitidos_resumen
    if extras:
        problemas.append(f"Campos no permitidos en resumen_publico: {sorted(extras)}")

    # Coherencia de conteos.
    if datos.get("selecciones") and datos.get("picks"):
        if len(datos["selecciones"]) != len(datos["picks"]):
            # No es un error fatal (pueden diferir en semanas futuras), pero se avisa.
            problemas.append(
                f"Conteos distintos: {len(datos['selecciones'])} selecciones vs "
                f"{len(datos['picks'])} picks"
            )

    return problemas


def main() -> int:
    ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "data" / "public-nfl.json"
    problemas = validar(ruta)
    if problemas:
        print("RECHAZADO: el artefacto publico contiene datos privados o campos no permitidos:")
        for p in problemas:
            print("  -", p)
        return 2
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    print(
        f"OK — {ruta} validado: {len(datos.get('selecciones', []))} selecciones, "
        f"{len(datos.get('picks', []))} picks, "
        f"{len(datos.get('boletos_publicos', []))} boletos (sin importes por boleto)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
