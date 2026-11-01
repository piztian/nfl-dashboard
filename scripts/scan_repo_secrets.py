#!/usr/bin/env python3
"""Escanea TODO el repo publico en busca de datos privados, no solo el JSON.

El validador del artefacto publicado (validate_public.py) mira un archivo: el
JSON que se sube a Pages. Ese es el hueco real: un repo publico tambien
contiene README, docs, workflows, scripts, .env de ejemplo y notas, y
cualquiera de ellos puede filtrar lo que el JSON sí protege.

Caso real: el ID del spreadsheet se coló en OPERACION.md y en
config/example.env. El validador del JSON pasaba (exit 0) mientras el repo
publico ya exponia el ID y el correo de la cuenta de servicio.

Uso:
    python3 scan_repo_secrets.py                      # escanea el repo actual
    python3 scan_repo_secrets.py --repo ruta/al/repo
    python3 scan_repo_secrets.py --extra-id 1Tjg...   # IDs adicionales a buscar
    python3 scan_repo_secrets.py --allow-readme       # no falla por IDs en .md

Criterio de cierre: exit 0 = sin hallazgos; exit 2 = hay datos privados en
ficheros que se publicarian.

Que NO se escanea (y por que):
  - .git/ : historia; ya esta publicada si el repo es publico.
  - .env real / credenciales: nunca deberian estar en el repo; si aparecen,
    la respuesta es borrarlas del indice, no ignorarlas.
  - binarios y lockfiles: se comparan como texto y solo se reporta si el
    patron aparece en texto plano legible.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Patrones de datos que nunca deben vivir en un repo publico.
PATRONES: dict[str, re.Pattern[str]] = {
    "ID de spreadsheet de Google": re.compile(r"\b1[A-Za-z0-9_-]{40,}\b"),
    "correo electronico": re.compile(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    ),
    "token de GitHub": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "API key de Google": re.compile(r"AIza[0-9A-Za-z\-_]{30,}"),
    "refresh token de OAuth": re.compile(r"1//[0-9A-Za-z_\-]{40,}"),
    "clave privada PEM": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "clave privada JSON": re.compile(r'"private_key"'),
    "CLABE bancaria": re.compile(r"(?<!\d)\d{18}(?!\d)"),
    # Tarjetas: 13-16 digitos, con separadores opcionales. Sin este tope un
    # numero cualquiera de 18+ digitos (un id, un timestamp) se reportaria
    # como tarjeta y el escaner terminaria ignorandose por ruido.
    # El digito verificador Luhn se comprueba aparte (ver _es_luhn): asi un
    # timestamp de 13 digitos no se reporta como tarjeta.
    "numero de tarjeta": re.compile(r"(?<!\d)(?:\d[ -]?){12,15}\d(?!\d)"),
}


def _es_luhn(digitos: str) -> bool:
    """Valida el digito verificador Luhn de un numero de tarjeta."""
    if not digitos.isdigit() or not (13 <= len(digitos) <= 19):
        return False
    total = 0
    paridad = len(digitos) % 2
    for i, ch in enumerate(digitos):
        d = int(ch)
        if i % 2 == paridad:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0

# Extensiones que se inspeccionan como texto.
TEXTUALES = {
    ".md", ".txt", ".json", ".yml", ".yaml", ".py", ".js", ".mjs", ".ts",
    ".html", ".css", ".env", ".example", ".sh", ".toml", ".cfg", ".ini", ".csv",
}

# Rutas cuyo contenido es deliberadamente privado o no publicable.
EXCLUIDOS_DIRECTORIOS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".next"}

# Correos que son de la propia herramienta y no son datos de cliente: no se
# reportan, pero solo si el archivo es del repo (no si es un dump de datos).
CORREOS_IGNORADOS = {
    "actions@github.com",
    "github-actions[bot]@users.noreply.github.com",
    "noreply@github.com",
}

# Ficheros que *definen* los patrones y por eso los contienen de forma
# legitima: un validador que busca '"private_key"' no debe fallarse a si
# mismo. Se omiten, pero solo estos ficheros y no su contenido.
FICHEROS_DE_PATRONES = {
    "validate_public.py",
    "scan_repo_secrets.py",
}

# Directiva por linea para marcar una coincidencia legitima:
#   ...codigo...  # scan:ignore
DIRECTIVA_IGNORAR = re.compile(r"#\s*scan:ignore\b")


def _es_texto(ruta: Path) -> bool:
    if ruta.suffix.lower() in TEXTUALES:
        return True
    # Sin extension (README, LICENSE, Makefile) pero nombre conocido.
    return ruta.name.lower() in {
        "readme", "license", "makefile", "dockerfile", "procfile", ".env",
    }


def _leer(raiz: Path) -> list[Path]:
    """Ficheros versionados (git ls-files) o, si no es repo, todo el arbol."""
    try:
        out = subprocess.run(
            ["git", "-C", str(raiz), "ls-files"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        return [raiz / linea for linea in out.splitlines() if linea]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return [
            p for p in raiz.rglob("*")
            if p.is_file() and not any(d in EXCLUIDOS_DIRECTORIOS for d in p.parts)
        ]


def escanear(
    raiz: Path,
    ids_extra: list[str] | None = None,
    permitir_md: bool = False,
) -> list[tuple[Path, int, str, str]]:
    """Devuelve [(ruta, linea, tipo, fragmento)] con los hallazgos."""
    hallazgos: list[tuple[Path, int, str, str]] = []
    patrones = dict(PATRONES)
    for i, valor in enumerate(ids_extra or []):
        if valor:
            patrones[f"ID de spreadsheet (extra {i+1})"] = re.compile(re.escape(valor))

    for ruta in _leer(raiz):
        if any(d in EXCLUIDOS_DIRECTORIOS for d in ruta.parts):
            continue
        if not ruta.is_file() or not _es_texto(ruta):
            continue
        if ruta.name in FICHEROS_DE_PATRONES:
            continue
        try:
            texto = ruta.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, linea in enumerate(texto.splitlines(), 1):
            if DIRECTIVA_IGNORAR.search(linea):
                continue
            # Un mismo fragmento no debe reportarse por dos patrones
            # (una CLABE de 18 digitos tambien encaja como "tarjeta").
            vistos: set[str] = set()
            for tipo, patron in patrones.items():
                m = patron.search(linea)
                if not m:
                    continue
                frag = m.group(0)
                clave = frag.replace(" ", "").replace("-", "")
                if clave in vistos:
                    continue
                vistos.add(clave)
                if tipo == "correo electronico" and frag.lower() in CORREOS_IGNORADOS:
                    continue
                # Una tarjeta se confirma con Luhn: un timestamp o un id
                # largo no pasan el digito verificador y se descartan.
                if tipo == "numero de tarjeta" and not _es_luhn(clave):
                    continue
                # Un ID de spreadsheet en un .md suele ser documentacion
                # operativa; sigue siendo una fuga si el repo es publico.
                if permitir_md and ruta.suffix.lower() in {".md", ".txt"}:
                    if tipo.startswith("ID de spreadsheet"):
                        continue
                rel = ruta.relative_to(raiz)
                hallazgos.append((rel, n, tipo, frag[:28]))
    return hallazgos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".", help="Raiz del repo a escanear.")
    ap.add_argument("--extra-id", action="append", default=[],
                    help="ID adicional a buscar (p.ej. el spreadsheet_id).")
    ap.add_argument("--allow-readme", action="store_true",
                    help="No reporta IDs de spreadsheet dentro de .md/.txt.")
    args = ap.parse_args()

    raiz = Path(args.repo).resolve()
    if not raiz.is_dir():
        print(f"No existe el directorio: {raiz}")
        return 1

    hallazgos = escanear(raiz, args.extra_id, args.allow_readme)
    if not hallazgos:
        print(f"OK — ningun dato privado encontrado en {raiz}")
        return 0

    print(f"RECHAZADO — {len(hallazgos)} datos privados en archivos publicables:")
    for ruta, linea, tipo, frag in hallazgos:
        print(f"  {ruta}:{linea}  {tipo}: {frag}...")
    print()
    print("Cada hallazgo debe eliminarse del archivo o sustituirse por un")
    print("placeholder. El repo es publico: lo que esta en el arbol es visible.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
