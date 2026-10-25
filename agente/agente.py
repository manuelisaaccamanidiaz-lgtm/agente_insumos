"""
agente.py — El LOOP del agente 🔁
=================================
  pregunta ─► 🧠 LLM piensa ─► ¿pidió herramienta?
                  ▲              │ sí → 🔧 ejecutamos → 👀 le damos el resultado ─┐
                  └──────────────┴────────────────────────────────────────────────┘
                                 │ no → ✅ respuesta final
"""
import json
import time
from datetime import datetime

import openai

from agente import config, herramientas

PROMPT_SISTEMA = """Eres un asesor de compras de insumos agrícolas para pequeños productores en Colombia.
Tienes 4 herramientas: consultar_precios, analizar_tendencia, consultar_trm y enviar_alerta.

Cómo trabajas:
1. Antes de recomendar, usa consultar_precios y analizar_tendencia para el insumo y la región.
   Nunca inventes cifras: todo número que digas debe salir de una herramienta.
2. Usa consultar_trm como contexto: los fertilizantes son importados, y si el dólar sube
   su precio tiende a subir después. Menciónalo en una frase, sin tecnicismos.
3. Entrega SIEMPRE: la recomendación (comprar ya / esperar / sin apuro) + el porqué,
   en lenguaje sencillo para un campesino, corto y con precios en pesos colombianos.
4. Usa enviar_alerta SOLO si el usuario pide explícitamente que le avisen o le escriban
   por Telegram. La alerta debe ser corta: insumo, región, precio actual y recomendación.
5. Si una herramienta devuelve "error": NO inventes el dato que faltó. Explica en pocas
   palabras qué falló, sigue con lo que sí tienes y sugiere alternativas (por ejemplo,
   las regiones o insumos que el error dice que sí existen, o intentar más tarde).
6. Si una herramienta dice "es_ejemplo": true, aclara que esos precios son de ejemplo
   (ficticios) y no sirven todavía para decidir una compra real."""


def _llamar_llm(cliente, modelo: str, mensajes: list) -> tuple[object | None, str | None]:
    """Llama a Grok. Devuelve (mensaje, None) o (None, texto del error) sin lanzar excepciones."""
    try:
        resp = cliente.chat.completions.create(
            model=modelo, messages=mensajes, tools=herramientas.ESQUEMAS
        )
        return resp.choices[0].message, None
    except openai.APITimeoutError:
        return None, "Grok no respondió a tiempo. Intenta de nuevo en un momento."
    except openai.APIConnectionError:
        return None, "No hay conexión con la API de Grok. Revisa tu internet o XAI_BASE_URL en el .env."
    except openai.AuthenticationError:
        return None, "Grok rechazó la API key (401). Revisa XAI_API_KEY en el .env."
    except openai.RateLimitError:
        return None, "Grok está limitando las peticiones o se acabó el saldo (429). Espera un poco y reintenta."
    except openai.NotFoundError:
        return None, f"Grok no encontró el modelo '{modelo}' (404). Revisa GROK_MODEL en el .env."
    except openai.APIStatusError as e:
        detalle = str(getattr(e, "message", "") or "")
        if "api key" in detalle.lower():  # xAI responde 400 (no 401) cuando la clave es incorrecta
            return None, "Grok rechazó la API key. Revisa XAI_API_KEY y XAI_BASE_URL en el .env."
        return None, f"La API de Grok respondió con error HTTP {e.status_code}: {detalle[:200]}"


def ejecutar_agente(pregunta: str, cliente, modelo: str, max_iter: int = config.MAX_ITERACIONES) -> dict:
    """Corre el loop completo y devuelve la respuesta + el rastro de pasos."""
    mensajes = [
        {"role": "system", "content": PROMPT_SISTEMA},
        {"role": "user", "content": pregunta},
    ]
    rastro = []  # evidencia de qué hizo el agente en cada vuelta

    for vuelta in range(1, max_iter + 1):
        #  1. PENSAR
        msg, error_llm = _llamar_llm(cliente, modelo, mensajes)
        if error_llm:
            rastro.append({"vuelta": vuelta, "tipo": "error_llm", "mensaje": error_llm})
            return {"respuesta": f"⚠️ {error_llm}", "rastro": rastro, "error_llm": error_llm}

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
            inicio = time.perf_counter()
            resultado = herramientas.ejecutar(tc.function.name, tc.function.arguments)
            duracion_ms = round((time.perf_counter() - inicio) * 1000)
            dato = json.loads(resultado)
            paso = {"vuelta": vuelta, "tipo": "herramienta",
                    "nombre": tc.function.name, "argumentos": tc.function.arguments,
                    "exito": "error" not in dato, "duracion_ms": duracion_ms}
            if not paso["exito"]:
                paso.update(tipo_error=dato.get("tipo_error"), error=dato["error"])
            rastro.append(paso)
            # 3. OBSERVAR: le devolvemos el resultado al LLM (también si fue un error)
            mensajes.append({"role": "tool", "tool_call_id": tc.id, "content": resultado})

    return {"respuesta": "⚠️ Se alcanzó el límite de vueltas sin respuesta final.", "rastro": rastro}


def guardar_log(pregunta: str, salida: dict) -> str:
    """Guarda la ejecución en logs/ como prueba de que corrió end-to-end."""
    config.CARPETA_LOGS.mkdir(exist_ok=True)
    ruta = config.CARPETA_LOGS / f"ejecucion_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    ruta.write_text(json.dumps({"pregunta": pregunta, **salida}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return str(ruta)
