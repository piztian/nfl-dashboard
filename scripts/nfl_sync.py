"""Sincronizador: NFL -> Google Sheets -> JSON publico sanitizado.

Flujo:
  1. Lee el Sheet (pestanas Boletos, Selecciones, Picks) con encabezados
     validos, nunca por indice magico.
  2. Consulta los partidos de las fechas necesarias al proveedor.
  3. Liquida cada seleccion y cada pick con las reglas de mercado.
  4. Propone (dry run) o escribe los cambios, respetando la edicion manual.
  5. Genera `data/public-nfl.json` con una lista EXPLICITA de campos
     permitidos: nunca IDs de boleto, ni montos por boleto, ni datos privados.

Idempotencia: correr dos veces produce el mismo resultado y no duplica filas.
Edicion manual: un resultado manual existente nunca se sobreescribe por el
sincronizador; se registra en Bitacora.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nfl_markets import (  # noqa: E402
    ANULADA,
    GANADA,
    PERDIDA,
    PENDIENTE,
    REVISION,
    liquidar_seleccion,
    parsear_seleccion,
)
import nfl_client  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
SPREADSHEET_ID = os.environ.get("NFL_SPREADSHEET_ID", "")
HOJAS = {"boletos": "Boletos", "selecciones": "Selecciones", "picks": "Picks"}
ESTADO_MANUAL = "manual"
ESTADO_AUTOMATICO = "auto"


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------
@dataclass
class Cambio:
    """Un cambio propuesto o aplicado a una celda del Sheet."""

    hoja: str
    celda: str
    etiqueta: str
    valor_anterior: str
    valor_nuevo: str
    motivo: str

    def a_dict(self) -> dict:
        return {
            "hoja": self.hoja,
            "celda": self.celda,
            "etiqueta": self.etiqueta,
            "anterior": self.valor_anterior,
            "nuevo": self.valor_nuevo,
            "motivo": self.motivo,
        }


@dataclass
class Reporte:
    cambios: list[Cambio] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    cobertura: dict = field(default_factory=dict)
    resumen: dict = field(default_factory=dict)

    def agregar(self, cambio: Cambio) -> None:
        self.cambios.append(cambio)

    def a_dict(self) -> dict:
        return {
            "cambios": [c.a_dict() for c in self.cambios],
            "avisos": self.avisos,
            "errores": self.errores,
            "cobertura": self.cobertura,
            "resumen": self.resumen,
        }


# --------------------------------------------------------------------------
# Acceso al Sheet
# --------------------------------------------------------------------------
class SheetsClient:
    """Envoltura minima sobre la API de Google Sheets."""

    def __init__(self, spreadsheet_id: str, credentials_path: Optional[str] = None):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        if not spreadsheet_id:
            raise SystemExit(
                "Falta NFL_SPREADSHEET_ID. Ver config/example.env y OPERACION.md."
            )
        cred_path = credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not cred_path:
            raise SystemExit(
                "Falta GOOGLE_APPLICATION_CREDENTIALS (ruta al JSON de la cuenta de servicio)."
            )
        info = json.loads(Path(cred_path).read_text())
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        self.service = build("sheets", "v4", credentials=creds)
        self.spreadsheet_id = spreadsheet_id

    def leer(self, rango: str) -> list[list[str]]:
        valores = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=rango)
            .execute()
            .get("values", [])
        )
        return [[str(c) for c in fila] for fila in valores]

    def escribir(self, rango: str, valores: list[list[str]], hoja_nombre: str = "") -> None:
        body = {"values": valores}
        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=rango,
            valueInputOption="RAW",
            body=body,
        ).execute()
        if hoja_nombre:
            self.registrar_bitacora(
                hoja_nombre, "escritura", len(valores), f"rango {rango}", ""
            )

    def anexar(self, hoja: str, fila: list[str]) -> None:
        self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{hoja}'!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [fila]},
        ).execute()

    def registrar_bitacora(
        self, hoja: str, accion: str, filas: int, detalle: str, error: str
    ) -> None:
        """Anota la bitacora. Nunca rompe la sincronizacion si la bitacora falla."""
        marca = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            self.anexar(
                "Bitácora",
                [marca, accion, hoja, str(filas), detalle[:180], error[:180], "nfl-sync"],
            )
        except Exception:  # pragma: no cover - la bitacora es best-effort
            pass


# --------------------------------------------------------------------------
# Lectura con encabezados validos
# --------------------------------------------------------------------------
def _norm(texto: str) -> str:
    """Normaliza un encabezado para compararlo sin acentos ni mayusculas."""
    import unicodedata

    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.strip().lower()


def _indice(encabezados: list[str], nombre: str) -> Optional[int]:
    """Devuelve el indice 0-based REAL de la columna dentro de la hoja.

    Ojo: los encabezados NO pueden incluir las claves internas del registro
    (`_fila`, `_norm`). Si se pasan, el indice queda corrido y el sync
    escribe el resultado en la columna vecina (bug del 1-nov-2026).
    """
    objetivo = _norm(nombre)
    # El indice debe contar SOLO los encabezados reales de la hoja: las
    # claves internas del registro (`_fila`, `_norm`) no son columnas y
    # desplazan el conteo.
    i = 0
    for h in encabezados:
        if h.startswith("_"):
            continue
        if _norm(h) == objetivo:
            return i
        i += 1
    return None


def _celda(columna: int, fila: int) -> str:
    """Convierte (indice de columna 0-based, fila 1-based) a referencia A1."""
    letras = ""
    n = columna + 1
    while n:
        n, resto = divmod(n - 1, 26)
        letras = chr(65 + resto) + letras
    return f"{letras}{fila}"


def leer_tabla(cliente: SheetsClient, hoja: str) -> list[dict]:
    """Lee una pestana usando su encabezado real (nunca indices magicos)."""
    filas = cliente.leer(f"'{hoja}'!A1:Z200")
    if not filas:
        return []
    encabezados = filas[0]
    registros = []
    for numero, fila in enumerate(filas[1:], start=2):
        if not any(str(c).strip() for c in fila):
            continue
        reg = {"_fila": numero}
        for i, h in enumerate(encabezados):
            reg[h.strip()] = fila[i] if i < len(fila) else ""
        # Acceso insensible a acentos: "Selección" == "Seleccion".
        reg["_norm"] = {_norm(k): v for k, v in reg.items() if not k.startswith("_")}
        registros.append(reg)
    return registros


def _get(reg: dict, nombre: str, default: str = "") -> str:
    """Lee un campo del registro sin distinguir acentos ni mayusculas."""
    v = reg.get("_norm", {}).get(_norm(nombre))
    return v if v is not None else default


# --------------------------------------------------------------------------
# Motor de sincronizacion
# --------------------------------------------------------------------------
class Sincronizador:
    def __init__(self, cliente: SheetsClient, proveedor: str = "espn"):
        self.cliente = cliente
        self.proveedor = proveedor
        self.reporte = Reporte()

    # -- Selecciones -----------------------------------------------------
    def procesar_selecciones(self, partidos: list[nfl_client.Partido]) -> list[list[str]]:
        registros = leer_tabla(self.cliente, HOJAS["selecciones"])
        if not registros:
            self.reporte.avisos.append("Pestana Selecciones vacia")
            return []

        col_resultado = _indice(list(registros[0].keys()), "Resultado")
        if col_resultado is None:
            raise SystemExit("No se encontro la columna 'Resultado' en Selecciones")
        col_notas = _indice(list(registros[0].keys()), "Marcador / notas")

        a_actualizar: list[list[str]] = []
        for reg in registros:
            fecha = _get(reg, "Fecha").strip()
            equipo = _get(reg, "Equipo").strip()
            rival = _get(reg, "Rival").strip()
            mercado = _get(reg, "Mercado").strip()
            seleccion = _get(reg, "Seleccion").strip()
            resultado_actual = _get(reg, "Resultado").strip()
            notas = _get(reg, "Marcador / notas")

            etiqueta = f"{equipo} vs {rival} · {mercado} {seleccion}".strip()
            celda = _celda(col_resultado, reg["_fila"])

            # Regla 11 / politica de edicion manual: si el resultado ya fue
            # escrito a mano (no "Pendiente" ni auto), no se toca.
            if resultado_actual and resultado_actual not in ("Pendiente",) and not resultado_actual.startswith("auto:"):
                self.reporte.avisos.append(
                    f"Resolucion manual preservada en {celda} ({etiqueta}): '{resultado_actual}'"
                )
                continue

            partido = nfl_client.buscar_partido_para_fila(
                partidos, fecha=fecha, equipo_a=equipo, equipo_b=rival
            )
            if partido is None:
                self.reporte.avisos.append(
                    f"Sin evento del proveedor para {etiqueta} ({fecha}); permanece pendiente"
                )
                continue

            apuesta = parsear_seleccion(mercado, seleccion)
            if apuesta.get("lado") == "desconocido":
                self.reporte.avisos.append(
                    f"Revision manual: mercado no reconocido en {etiqueta}"
                )
                self.reporte.agregar(
                    Cambio(HOJAS["selecciones"], celda, etiqueta, resultado_actual, REVISION,
                           "Mercado o seleccion no reconocida")
                )
                a_actualizar.append([REVISION])
                continue

            # Para resolver local/visitante correctamente hay que saber cual
            # de los dos equipos del Sheet es el local del evento.
            local_del_evento = partido.local if nfl_client.mismo_equipo(partido.local, equipo) else partido.visitante
            puntos_local, puntos_visitante = (
                (partido.puntos_local, partido.puntos_visitante)
                if nfl_client.mismo_equipo(partido.local, equipo)
                else (partido.puntos_visitante, partido.puntos_local)
            )

            res = liquidar_seleccion(
                apuesta,
                puntos_equipo=puntos_local,
                puntos_rival=puntos_visitante,
                equipo_local=local_del_evento,
                estado_partido=partido.estado,
            )

            if res.estado == PENDIENTE:
                self.reporte.avisos.append(
                    f"{etiqueta}: partido en estado '{partido.estado}', permanece pendiente"
                )
                continue

            nuevo = res.estado
            if res.estado == REVISION:
                nuevo = REVISION
            else:
                nuevo = f"{res.estado}" if not res.push else "Anulada (push)"

            if nuevo != resultado_actual:
                self.reporte.agregar(
                    Cambio(HOJAS["selecciones"], celda, etiqueta, resultado_actual, nuevo,
                           f"{partido.event_id} · {partido.local} {puntos_local} - {puntos_visitante} {partido.visitante} · {res.detalle}")
                )
                a_actualizar.append([nuevo])

        return a_actualizar

    # -- Picks ------------------------------------------------------------
    def procesar_picks(self, partidos: list[nfl_client.Partido]) -> list[list[str]]:
        registros = leer_tabla(self.cliente, HOJAS["picks"])
        if not registros:
            self.reporte.avisos.append("Pestana Picks vacia")
            return []

        col_resultado = _indice(list(registros[0].keys()), "Resultado")
        if col_resultado is None:
            raise SystemExit("No se encontro la columna 'Resultado' en Picks")
        col_marcador = _indice(list(registros[0].keys()), "Marcador")

        a_actualizar: list[list[str]] = []
        for reg in registros:
            fecha = _get(reg, "Fecha").strip()
            pick = _get(reg, "Pick").strip()
            rival = _get(reg, "Rival").strip()
            resultado_actual = _get(reg, "Resultado").strip()
            marcador_actual = _get(reg, "Marcador").strip()

            etiqueta = f"{pick} vs {rival}"
            celda = _celda(col_resultado, reg["_fila"])

            if resultado_actual and resultado_actual != "Pendiente" and not resultado_actual.startswith("auto:"):
                self.reporte.avisos.append(
                    f"Resolucion manual preservada en {celda} ({etiqueta}): '{resultado_actual}'"
                )
                continue

            partido = nfl_client.buscar_partido_para_fila(
                partidos, fecha=fecha, equipo_a=pick, equipo_b=rival
            )
            if partido is None:
                self.reporte.avisos.append(
                    f"Sin evento del proveedor para {etiqueta} ({fecha}); permanece pendiente"
                )
                continue
            if not partido.es_final:
                self.reporte.avisos.append(
                    f"{etiqueta}: estado '{partido.estado}', permanece pendiente"
                )
                continue
            if not partido.tiene_marcador:
                self.reporte.avisos.append(f"{etiqueta}: sin marcador final, permanece pendiente")
                continue

            puntos_pick, puntos_rival = (
                (partido.puntos_local, partido.puntos_visitante)
                if nfl_client.mismo_equipo(partido.local, pick)
                else (partido.puntos_visitante, partido.puntos_local)
            )
            try:
                if int(puntos_pick) > int(puntos_rival):
                    nuevo = "Acertado"
                elif int(puntos_pick) < int(puntos_rival):
                    nuevo = "Fallado"
                else:
                    nuevo = "Revisión manual"
            except (TypeError, ValueError):
                nuevo = "Revisión manual"

            if nuevo != resultado_actual:
                self.reporte.agregar(
                    Cambio(HOJAS["picks"], celda, etiqueta, resultado_actual, nuevo,
                           f"{partido.event_id} · {partido.local} {partido.puntos_local} - {partido.puntos_visitante} {partido.visitante}")
                )
                a_actualizar.append([nuevo])

        return a_actualizar

    # -- Fechas necesarias ------------------------------------------------
    def fechas_a_consultar(self) -> list[str]:
        fechas: set[str] = set()
        for hoja, campo in ((HOJAS["selecciones"], "Fecha"), (HOJAS["picks"], "Fecha")):
            for reg in leer_tabla(self.cliente, hoja):
                f = _get(reg, campo).strip()
                if f:
                    fechas.add(f)
        return sorted(fechas)


# --------------------------------------------------------------------------
# JSON publico sanitizado
# --------------------------------------------------------------------------
CAMPOS_PUBLICOS_BOLETO = {"etiqueta", "estado"}
CAMPOS_PUBLICOS_SELECCION = {
    "semana", "fecha", "equipo", "rival", "mercado", "seleccion",
    "cuota_capturada", "resultado", "marcador", "boleto",
}
CAMPOS_PUBLICOS_PICK = {
    "semana", "fecha", "pick", "rival", "resultado", "marcador",
}


def _fecha(texto: str):
    """Convierte 'YYYY-MM-DD' a date; devuelve hoy si no se puede."""
    from datetime import date

    try:
        y, m, d = (int(x) for x in str(texto).split("-"))
        return date(y, m, d)
    except (ValueError, TypeError):
        return date.today()


def generar_json_publico(cliente: SheetsClient, destino: Path) -> dict:
    """Genera el JSON publico con lista explicita de campos permitidos.

    NO incluye: ID de boleto, ID de Sheets, correo, notas internas, cokros
    reales, importes por boleto, ni la bitacora.
    """
    boletos = leer_tabla(cliente, HOJAS["boletos"])
    selecciones = leer_tabla(cliente, HOJAS["selecciones"])
    picks = leer_tabla(cliente, HOJAS["picks"])

    def num(valor: str):
        try:
            return float(str(valor).replace(",", "").replace("$", "").strip())
        except (TypeError, ValueError):
            return 0.0

    datos = {
        "generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": "espn",
        "temporada": 2026,
        "boletos_publicos": [],
        "selecciones": [],
        "picks": [],
    }

    for b in boletos:
        # Sin importes por boleto: el spec prohibe exponer detalle financiero
        # por boleto en la vista publica. El total apostado si se publica.
        datos["boletos_publicos"].append(
            {
                "etiqueta": _get(b, "Boleto"),
                "estado": _get(b, "Estado"),
            }
        )

    for s in selecciones:
        fecha = _get(s, "Fecha")
        datos["selecciones"].append(
            {
                "semana": _get(s, "Semana") or str(nfl_client.semana_nfl(_fecha(fecha)) or ""),
                "fecha": fecha,
                "equipo": _get(s, "Equipo"),
                "rival": _get(s, "Rival"),
                "mercado": _get(s, "Mercado"),
                "seleccion": _get(s, "Seleccion"),
                "cuota_capturada": _get(s, "Cuota"),
                "resultado": _get(s, "Resultado"),
                "marcador": _get(s, "Marcador / notas"),
                "boleto": _get(s, "Boleto"),
            }
        )

    for p in picks:
        datos["picks"].append(
            {
                "semana": _get(p, "Semana"),
                "fecha": _get(p, "Fecha"),
                "pick": _get(p, "Pick"),
                "rival": _get(p, "Rival"),
                "resultado": _get(p, "Resultado"),
                "marcador": _get(p, "Marcador"),
            }
        )

    # Agregados: sin desglose por boleto. El detalle financiero por boleto
    # permanece privado en el Sheet.
    datos["resumen_publico"] = {
        "boletos_confirmados": len(boletos),
        "apostado_total_mxn": sum(num(_get(b, "Apostado MXN", "0")) for b in boletos),
        "cobro_potencial_total_mxn": sum(
            num(_get(b, "Cobro potencial MXN", "0")) for b in boletos
        ),
        "cobro_real_total_mxn": sum(num(_get(b, "Cobro real MXN", "0")) for b in boletos),
        "selecciones": len(selecciones),
        "picks": len(picks),
    }

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return datos


def validar_json_publico(datos: dict, ids_privados: list[str]) -> list[str]:
    """Verifica que el JSON no contenga datos privados."""
    problemas: list[str] = []
    texto = json.dumps(datos, ensure_ascii=False)
    for priv in ids_privados:
        if priv and priv in texto:
            problemas.append(f"El JSON publico contiene el dato privado: {priv}")
    if "Cobro real" in texto:
        problemas.append("El JSON publico contiene la columna 'Cobro real'")
    permitidos = set(CAMPOS_PUBLICOS_BOLETO) | set(CAMPOS_PUBLICOS_SELECCION) | set(CAMPOS_PUBLICOS_PICK)
    permitidos |= {
        "generado_en", "fuente", "temporada", "boletos_publicos", "selecciones",
        "picks", "resumen_publico",
    }
    for bloque, campos in (
        ("boletos_publicos", CAMPOS_PUBLICOS_BOLETO),
        ("selecciones", CAMPOS_PUBLICOS_SELECCION),
        ("picks", CAMPOS_PUBLICOS_PICK),
    ):
        for item in datos.get(bloque, []):
            extra = set(item.keys()) - campos
            if extra:
                problemas.append(f"Campos no permitidos en {bloque}: {sorted(extra)}")
    return problemas


# --------------------------------------------------------------------------
# Orquestacion
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Sincroniza resultados NFL a Sheets y genera JSON publico.")
    ap.add_argument("--dry-run", action="store_true", help="No escribe en el Sheet; solo reporta.")
    ap.add_argument("--json-out", default=str(RAIZ / "data" / "public-nfl.json"))
    ap.add_argument("--proveedor", default="espn")
    ap.add_argument("--solo-json", action="store_true", help="No consulta al proveedor; solo regenera el JSON.")
    args = ap.parse_args()

    cliente = SheetsClient(
        os.environ.get("NFL_SPREADSHEET_ID", ""),
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
    )
    sync = Sincronizador(cliente, proveedor=args.proveedor)

    if not args.solo_json:
        fechas = sync.fechas_a_consultar()
        print(f"Fechas a consultar: {fechas}")
        partidos = nfl_client.obtener_partidos(fechas, proveedor=args.proveedor)
        sync.reporte.cobertura = nfl_client.resumen_marcadores(partidos)
        print(f"Eventos obtenidos: {len(partidos)} -> {sync.reporte.cobertura}")

        cambios_sel = sync.procesar_selecciones(partidos)
        cambios_pick = sync.procesar_picks(partidos)
        print(f"Cambios propuestos: {len(sync.reporte.cambios)}")

        if not args.dry_run:
            # Se aplican celda por celda para no tocar filas que no cambian.
            for cambio in sync.reporte.cambios:
                cliente.escribir(
                    f"'{cambio.hoja}'!{cambio.celda}",
                    [[cambio.valor_nuevo]],
                    hoja_nombre=cambio.hoja,
                )
            cliente.registrar_bitacora(
                "Sincronización",
                "sincronizacion",
                len(sync.reporte.cambios),
                f"proveedor={args.proveedor} dry_run={args.dry_run}",
                "",
            )
            print(f"Aplicados {len(sync.reporte.cambios)} cambios en Sheets.")
        else:
            print("DRY RUN: no se escribio nada en el Sheet.")

    ids_privados = [_get(b, "ID boleto") for b in leer_tabla(cliente, HOJAS["boletos"])]
    ids_privados.append(cliente.spreadsheet_id)
    destino = Path(args.json_out)
    datos = generar_json_publico(cliente, destino)
    problemas = validar_json_publico(datos, ids_privados)
    if problemas:
        print("RECHAZADO: el JSON publico contiene datos privados:")
        for p in problemas:
            print("  -", p)
        return 2
    print(f"JSON publico escrito y validado: {destino}")

    reporte = sync.reporte.a_dict()
    print(f"\n--- RESUMEN ---")
    print(f"cambios: {len(reporte['cambios'])} | avisos: {len(reporte['avisos'])} | errores: {len(reporte['errores'])}")
    for a in reporte["avisos"][:12]:
        print("  aviso:", a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
