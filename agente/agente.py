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

Sobre los datos: son precios REALES del DANE (SIPSA-Insumos), MENSUALES, por municipio, y se
publican con unas 3 semanas de retraso. No son precios de hoy: SIEMPRE di de qué mes es el
último dato (ej.: "según el DANE, en septiembre de 2026..."). Las regiones son DEPARTAMENTOS;
si el usuario nombra un municipio (ej. Bucaramanga), pásalo en `municipio` con su departamento.

Cómo trabajas:
1. Usa SOLO las herramientas que la pregunta necesita:
   - "¿cuánto vale X?" → consultar_precios.
   - "¿cuánto me cuestan N bultos?" → calcular_costo_compra (no hace falta nada más).
   - "¿compro ya o espero?" → analizar_tendencia (ya trae el precio actual) + consultar_trm.
   Nunca inventes cifras ni hagas cuentas tú: todo número que digas debe salir de una herramienta.
2. Da el precio así: "alrededor de $X (entre $min y $max según el municipio)"; si solo hay un
   municipio, di cuál es en vez del rango. Precios en pesos colombianos ($169.271).
3. Si no hay datos del insumo en la región, o "dato_desactualizado" es true, dilo claro con el
   mes del último dato y usa consultar_regiones_vecinas: ofrece la alternativa vecina más
   barata CON dato reciente ("mas_barato_vigente"). Si en un municipio el dato es viejo y viene
   "referencia_departamento", da también esa cifra reciente del departamento.
4. Para "comprar ya o esperar": entrega la recomendación (comprar ya / esperar / sin apuro) +
   el porqué en meses (tendencia de los últimos 6 meses y comparación con el mismo mes del año
   pasado). Usa la TRM como contexto en una frase: los fertilizantes son importados y si el
   dólar sube su precio tiende a subir después.
5. Lenguaje sencillo para un campesino, corto y concreto.
6. Usa enviar_alerta SOLO si el usuario pide explícitamente que le avisen o le escriban
   por Telegram. La alerta debe ser corta: insumo, región, precio, mes del dato y recomendación.
7. Si una herramienta devuelve "error": NO inventes el dato que faltó. Explica en pocas
   palabras qué falló, sigue con lo que sí tienes y sugiere alternativas (los municipios,
   departamentos o insumos que el error dice que sí existen, o intentar más tarde).
8. Si una herramienta dice "es_ejemplo": true, aclara que esos precios son de ejemplo
   (ficticios) y no sirven para decidir una compra real."""


def _llamar_llm(cliente, modelo: str, mensajes: list) -> tuple[object | None, object | None, str | None]:
    """Llama a Grok. Devuelve (mensaje, usage, None) o (None, None, texto del error) sin
    lanzar excepciones. `usage` trae los tokens de la llamada (None si la API no lo manda)."""
    try:
        resp = cliente.chat.completions.create(
            model=modelo, messages=mensajes, tools=herramientas.ESQUEMAS
        )
        return resp.choices[0].message, getattr(resp, "usage", None), None
    except openai.APITimeoutError:
        return None, None, "Grok no respondió a tiempo. Intenta de nuevo en un momento."
    except openai.APIConnectionError:
        return None, None, "No hay conexión con la API de Grok. Revisa tu internet o XAI_BASE_URL en el .env."
    except openai.AuthenticationError:
        return None, None, "Grok rechazó la API key (401). Revisa XAI_API_KEY en el .env."
    except openai.RateLimitError:
        return None, None, "Grok está limitando las peticiones o se acabó el saldo (429). Espera un poco y reintenta."
    except openai.NotFoundError:
        return None, None, f"Grok no encontró el modelo '{modelo}' (404). Revisa GROK_MODEL en el .env."
    except openai.APIStatusError as e:
        detalle = str(getattr(e, "message", "") or "")
        if "api key" in detalle.lower():  # xAI responde 400 (no 401) cuando la clave es incorrecta
            return None, None, "Grok rechazó la API key. Revisa XAI_API_KEY y XAI_BASE_URL en el .env."
        return None, None, f"La API de Grok respondió con error HTTP {e.status_code}: {detalle[:200]}"


# ---------- Tokens y costo por tarea ----------
def _sumar_tokens(uso: dict, usage) -> None:
    """Suma los tokens de una respuesta de Grok. Si una respuesta no trae `usage`, los
    tokens de la tarea quedan en None: un total parcial subestimaría el costo."""
    entrada = getattr(usage, "prompt_tokens", None)
    salida = getattr(usage, "completion_tokens", None)
    if entrada is None or salida is None or uso["tokens_entrada"] is None:
        uso["tokens_entrada"] = uso["tokens_salida"] = None
        return
    uso["tokens_entrada"] += entrada
    uso["tokens_salida"] += salida


def calcular_costo_usd(tokens_entrada: int | None, tokens_salida: int | None,
                       precio_entrada: float | None = None, precio_salida: float | None = None) -> float | None:
    """Costo en USD con los precios por millón de tokens del .env. None si falta un dato."""
    precio_entrada = config.PRECIO_ENTRADA_USD_MILLON if precio_entrada is None else precio_entrada
    precio_salida = config.PRECIO_SALIDA_USD_MILLON if precio_salida is None else precio_salida
    if None in (tokens_entrada, tokens_salida, precio_entrada, precio_salida):
        return None
    return round((tokens_entrada * precio_entrada + tokens_salida * precio_salida) / 1_000_000, 6)


def _cerrar_uso(uso: dict, inicio: float) -> dict:
    """Completa el uso de la tarea: total de tokens, duración y costo."""
    entrada, salida = uso["tokens_entrada"], uso["tokens_salida"]
    return {**uso,
            "tokens_total": None if entrada is None else entrada + salida,
            "duracion_ms": round((time.perf_counter() - inicio) * 1000),
            "costo_usd": calcular_costo_usd(entrada, salida)}


def _miles(valor: float, decimales: int = 0) -> str:
    """4210 -> '4.210', 6.14 (1 decimal) -> '6,1' (formato colombiano)."""
    return f"{valor:,.{decimales}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def formatear_uso(uso: dict) -> str:
    """'🧾 3 llamadas · 4.210 tokens · 6,1 s · $0,0021 USD' (n/d si la API no dio tokens)."""
    llamadas = uso["llamadas_llm"]
    tokens = "tokens n/d" if uso["tokens_total"] is None else f"{_miles(uso['tokens_total'])} tokens"
    costo = uso["costo_usd"]
    costo = "costo sin precio" if costo is None else f"${_miles(costo, 4)} USD"
    return (f"🧾 {llamadas} llamada{'s' if llamadas != 1 else ''} · {tokens} · "
            f"{_miles(uso['duracion_ms'] / 1000, 1)} s · {costo}")


def ejecutar_agente(pregunta: str, cliente, modelo: str, max_iter: int = config.MAX_ITERACIONES) -> dict:
    """Corre el loop completo y devuelve la respuesta + el rastro de pasos + el uso
    (llamadas a Grok, tokens, duración y costo de la tarea)."""
    mensajes = [
        {"role": "system", "content": PROMPT_SISTEMA},
        {"role": "user", "content": pregunta},
    ]
    rastro = []  # evidencia de qué hizo el agente en cada vuelta
    inicio = time.perf_counter()
    uso = {"llamadas_llm": 0, "tokens_entrada": 0, "tokens_salida": 0}

    for vuelta in range(1, max_iter + 1):
        #  1. PENSAR
        uso["llamadas_llm"] += 1
        msg, usage, error_llm = _llamar_llm(cliente, modelo, mensajes)
        if error_llm:
            rastro.append({"vuelta": vuelta, "tipo": "error_llm", "mensaje": error_llm})
            return {"respuesta": f"⚠️ {error_llm}", "rastro": rastro, "error_llm": error_llm,
                    "uso": _cerrar_uso(uso, inicio)}
        _sumar_tokens(uso, usage)

        #  2a. Sin herramientas → ya tiene la respuesta final
        if not msg.tool_calls:
            rastro.append({"vuelta": vuelta, "tipo": "respuesta"})
            return {"respuesta": msg.content, "rastro": rastro, "uso": _cerrar_uso(uso, inicio)}

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

    return {"respuesta": "⚠️ Se alcanzó el límite de vueltas sin respuesta final.", "rastro": rastro,
            "uso": _cerrar_uso(uso, inicio)}


def guardar_log(pregunta: str, salida: dict) -> str:
    """Guarda la ejecución en logs/ como prueba de que corrió end-to-end."""
    config.CARPETA_LOGS.mkdir(exist_ok=True)
    ruta = config.CARPETA_LOGS / f"ejecucion_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    ruta.write_text(json.dumps({"pregunta": pregunta, **salida}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return str(ruta)
