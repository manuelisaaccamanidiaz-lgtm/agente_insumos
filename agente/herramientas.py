"""
herramientas.py — Las "manos" del agente 🔧
===========================================
Cada herramienta tiene 2 partes:
  1. La FUNCIÓN de Python que hace el trabajo.
  2. El ESQUEMA (JSON) que le explica al LLM qué hace y qué parámetros recibe.
El LLM nunca ejecuta código: solo PIDE "llama consultar_precios con X".
Nosotros ejecutamos y le devolvemos el resultado.

S1: una sola herramienta para probar el flujo end-to-end.
(Las 3 herramientas son el entregable de S2.)
"""
import json

from agente import config
from agente.datos import buscar_historial, cargar_precios


# ---------- 1. Funciones ----------
def consultar_precios(insumo: str, region: str) -> dict:
    """Devuelve el historial de precios de un insumo en una región."""
    filas = cargar_precios(config.RUTA_PRECIOS)
    historial = buscar_historial(filas, insumo, region)
    if not historial:
        return {"error": f"No hay datos de '{insumo}' en '{region}'."}
    return {
        "insumo": insumo,
        "region": region,
        "unidad": historial[0]["unidad"],
        "fuente": "datos de ejemplo (CSV)",
        "historial": [{"fecha": f["fecha"], "precio_cop": f["precio_cop"]} for f in historial],
    }


# ---------- 2. Esquemas (lo que "lee" el LLM) ----------
ESQUEMAS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_precios",
            "description": (
                "Obtiene el historial semanal de precios (COP) de un insumo agrícola "
                "en una región de Colombia. Úsala siempre antes de hablar de precios."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "insumo": {"type": "string", "description": "Ej: urea, dap, kcl"},
                    "region": {"type": "string", "description": "Ej: Santander, Boyaca, Meta"},
                },
                "required": ["insumo", "region"],
            },
        },
    }
]

# ---------- 3. Registro: nombre -> función ----------
REGISTRO = {"consultar_precios": consultar_precios}


def ejecutar(nombre: str, argumentos_json: str) -> str:
    """Ejecuta la herramienta que pidió el LLM y devuelve el resultado como texto JSON."""
    if nombre not in REGISTRO:
        return json.dumps({"error": f"Herramienta desconocida: {nombre}"})
    try:
        argumentos = json.loads(argumentos_json or "{}")
        resultado = REGISTRO[nombre](**argumentos)
    except Exception as e:  # el agente no debe morir si el LLM manda algo raro
        resultado = {"error": f"Falló {nombre}: {e}"}
    return json.dumps(resultado, ensure_ascii=False)
