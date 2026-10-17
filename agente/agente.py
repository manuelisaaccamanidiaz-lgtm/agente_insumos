"""
agente.py — El LOOP del agente 🔁
=================================
  pregunta ─► 🧠 LLM piensa ─► ¿pidió herramienta?
                  ▲              │ sí → 🔧 ejecutamos → 👀 le damos el resultado ─┐
                  └──────────────┴────────────────────────────────────────────────┘
                                 │ no → ✅ respuesta final
"""
import json
from datetime import datetime

from agente import config, herramientas

PROMPT_SISTEMA = """Eres un asesor de compras de insumos agrícolas para pequeños productores en Colombia.
Reglas:
- Para hablar de precios usa SIEMPRE la herramienta consultar_precios. Nunca inventes cifras.
- Responde en español sencillo, corto y con los precios en pesos colombianos.
- Si no hay datos, dilo explicitamente.
- Aclara que los datos actuales son de ejemplo."""


def ejecutar_agente(pregunta: str, cliente, modelo: str, max_iter: int = config.MAX_ITERACIONES) -> dict:
    """Corre el loop completo y devuelve la respuesta + el rastro de pasos."""
    mensajes = [
        {"role": "system", "content": PROMPT_SISTEMA},
        {"role": "user", "content": pregunta},
    ]
    rastro = []  # evidencia de qué hizo el agente en cada vuelta

    for vuelta in range(1, max_iter + 1):
        #  1. PENSAR
        resp = cliente.chat.completions.create(
            model=modelo, messages=mensajes, tools=herramientas.ESQUEMAS
        )
        msg = resp.choices[0].message

        #  2a. Sin herramientas → ya tiene la respuesta final
        if not msg.tool_calls:
            rastro.append({"vuelta": vuelta, "tipo": "respuesta"})
            return {"respuesta": msg.content, "rastro": rastro}

        #  2b. Pidió herramientas → guardamos su pedido y las ejecutamos
        mensajes.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            resultado = herramientas.ejecutar(tc.function.name, tc.function.arguments)
            rastro.append({"vuelta": vuelta, "tipo": "herramienta",
                           "nombre": tc.function.name, "argumentos": tc.function.arguments})
            # 3. OBSERVAR: le devolvemos el resultado al LLM
            mensajes.append({"role": "tool", "tool_call_id": tc.id, "content": resultado})

    return {"respuesta": "⚠️ Se alcanzó el límite de vueltas sin respuesta final.", "rastro": rastro}


def guardar_log(pregunta: str, salida: dict) -> str:
    """Guarda la ejecución en logs/ como prueba de que corrió end-to-end."""
    config.CARPETA_LOGS.mkdir(exist_ok=True)
    ruta = config.CARPETA_LOGS / f"ejecucion_{datetime.now():%Y%m%d_%H%M%S}.json"
    ruta.write_text(json.dumps({"pregunta": pregunta, **salida}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return str(ruta)
