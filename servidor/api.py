"""
api.py — API web de Abona (FastAPI) 🌐
=====================================
Es otra "puerta de entrada" al MISMO agente, como main.py y app.py: no cambia su lógica.
Usa la voz de Abona (agente/voz_abona.py) solo dentro de este proceso.

Rutas:
    GET  /                 la interfaz (web/index.html)
    POST /api/preguntar    {"pregunta": "..."} → respuesta, herramientas usadas y costo
    GET  /api/estado       último mes publicado por el DANE, modelo e insumos disponibles
    GET  /api/carga        progreso de la corrida de la S4, leído de bitacora/ (solo lectura)

Uso:
    python -m servidor     (abre http://127.0.0.1:8000)
"""
import csv
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agente import config, datos
from agente.agente import ejecutar_agente, guardar_log
from agente.voz_abona import activar_voz_abona

RAIZ = Path(__file__).resolve().parent.parent
WEB = RAIZ / "web"
BITACORA = RAIZ / "bitacora" / "s4_bitacora.csv"
COLA = RAIZ / "data" / "cola_s4.jsonl"

activar_voz_abona()
app = FastAPI(title="Abona", docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=WEB), name="static")

_cliente, _candado = None, threading.Lock()


def _obtener_cliente():
    """Crea el cliente de Grok una sola vez. Si falta configuración, responde 503 con el motivo."""
    global _cliente
    with _candado:
        if _cliente is None:
            from agente.llm import crear_cliente
            try:
                _cliente = crear_cliente()
            except SystemExit as e:  # validar_config() avisa así cuando falta algo en el .env
                raise HTTPException(503, str(e).strip()) from None
    return _cliente


class Pregunta(BaseModel):
    pregunta: str = Field(min_length=2, max_length=500)


@app.get("/", include_in_schema=False)
def inicio():
    return FileResponse(WEB / "index.html")


@app.post("/api/preguntar")
def preguntar(cuerpo: Pregunta):
    pregunta = cuerpo.pregunta.strip()
    salida = ejecutar_agente(pregunta, _obtener_cliente(), config.GROK_MODEL)
    guardar_log(pregunta, salida)
    return {
        "respuesta": salida.get("respuesta") or "",
        "error": salida.get("error_llm"),
        "herramientas": [
            {"nombre": p["nombre"], "exito": p["exito"], "duracion_ms": p["duracion_ms"],
             "tipo_error": p.get("tipo_error")}
            for p in salida.get("rastro", []) if p.get("tipo") == "herramienta"
        ],
        "uso": salida.get("uso") or {},
    }


@app.get("/api/estado")
def estado():
    try:
        periodo = datos.ultimo_periodo_disponible(config.RUTA_BD)
        insumos = datos.insumos_disponibles(config.RUTA_BD)
    except Exception:  # BD sin crear: la interfaz lo muestra sin romperse
        periodo, insumos = None, []
    return {"periodo": periodo, "insumos": len(insumos), "modelo": config.GROK_MODEL or None}


@app.get("/api/carga")
def carga():
    """Resumen de la bitácora de la S4. Solo LEE el archivo; no interfiere con la corrida."""
    if not BITACORA.exists():
        return {"disponible": False}
    try:
        with open(BITACORA, encoding="utf-8-sig", newline="") as f:
            filas = list(csv.DictReader(f))
    except OSError:
        return {"disponible": False}
    total_cola = sum(1 for linea in open(COLA, encoding="utf-8") if linea.strip()) if COLA.exists() else None
    exitos = sum(1 for f in filas if f.get("exito") == "True")
    costo = sum(float(f["costo_usd"]) for f in filas if f.get("costo_usd"))
    return {
        "disponible": True, "tareas": len(filas), "total": total_cola, "exitos": exitos,
        "costo_usd": round(costo, 4), "inicio": filas[0]["inicio"] if filas else None,
        "ultima": filas[-1]["fin"] if filas else None,
    }
