"""
herramientas.py — Las "manos" del agente 🔧
===========================================
Cada herramienta tiene 2 partes:
  1. La FUNCIÓN de Python que hace el trabajo.
  2. El ESQUEMA (JSON) que le explica al LLM qué hace y qué parámetros recibe.
El LLM nunca ejecuta código: solo PIDE "llama consultar_precios con X".
Nosotros ejecutamos y le devolvemos el resultado.

S2: 4 herramientas que hacen algo REAL:
  - consultar_precios   → consulta la BD SQLite
  - analizar_tendencia  → lee la BD y calcula tendencia + recomendación
  - consultar_trm       → API pública de datos.gov.co (dólar oficial)
  - enviar_alerta       → API de bots de Telegram

Contrato de TODAS las herramientas: siempre devuelven un dict y NUNCA lanzan
excepciones. Si algo falla devuelven:
    {"error": "<mensaje claro en español>", "tipo_error": "sin_datos|red|config|validacion"}
Así el LLM puede explicar qué pasó y seguir con lo que sí tiene.
"""
import json
import sqlite3
from datetime import date

import requests

from agente import config
from agente.datos import (BaseDeDatosNoEncontrada, buscar_historial, insumos_disponibles,
                          regiones_disponibles)

# Umbral de la recomendación: cambio semanal (pendiente / promedio) que consideramos "real"
UMBRAL_PCT_SEMANAL = 1.0
LIMITE_MENSAJE = 1000  # caracteres máximos de una alerta
FUENTE_TRM = "datos.gov.co · TRM certificada (Superintendencia Financiera)"


def _error(mensaje: str, tipo: str) -> dict:
    """Forma única de los errores que ve el LLM."""
    return {"error": mensaje, "tipo_error": tipo}


def _pesos(valor: float) -> str:
    """171000 -> '$171.000' (formato colombiano)."""
    return "$" + f"{valor:,.0f}".replace(",", ".")


def _pct(valor: float, signo: bool = False) -> str:
    """2.06 -> '2,1%' (coma decimal, como se escribe en Colombia)."""
    return (f"{valor:+.1f}" if signo else f"{valor:.1f}").replace(".", ",") + "%"


def _historial_o_error(insumo: str, region: str) -> list[dict] | dict:
    """Busca el historial en la BD. Si no hay datos devuelve un error que incluye
    las alternativas disponibles, para que el LLM pueda sugerirlas."""
    try:
        historial = buscar_historial(config.RUTA_BD, insumo, region)
        if historial:
            return historial
        regiones = regiones_disponibles(config.RUTA_BD, insumo)
        if regiones:
            pista = f"Hay datos de '{insumo}' en: {', '.join(regiones)}."
        else:
            otros = insumos_disponibles(config.RUTA_BD, region) or insumos_disponibles(config.RUTA_BD)
            pista = f"No hay datos de '{insumo}' en ninguna región. Insumos disponibles: {', '.join(otros)}."
        return _error(f"No hay datos de '{insumo}' en '{region}'. {pista}", "sin_datos")
    except BaseDeDatosNoEncontrada as e:
        return _error(str(e), "config")
    except sqlite3.Error as e:
        return _error(f"No se pudo leer la base de datos de precios ({e}). "
                      "Prueba de nuevo con: python scripts/cargar_bd.py", "config")


# ---------- 1. Funciones ----------
def consultar_precios(insumo: str, region: str) -> dict:
    """Devuelve el historial de precios de un insumo en una región (desde SQLite)."""
    historial = _historial_o_error(insumo, region)
    if isinstance(historial, dict):
        return historial
    fuentes = sorted({f["fuente"] for f in historial})
    return {
        "insumo": historial[0]["insumo"],
        "region": historial[0]["region"],
        "unidad": historial[0]["unidad"],
        "fuente": ", ".join(fuentes),
        "es_ejemplo": fuentes == ["ejemplo"],  # True → precios FICTICIOS, hay que decirlo
        "historial": [{"fecha": f["fecha"], "precio_cop": f["precio_cop"]} for f in historial],
    }


def _pendiente(xs: list[float], ys: list[float]) -> float:
    """Regresión lineal simple (mínimos cuadrados) hecha a mano:
    pendiente = Σ(x - x̄)(y - ȳ) / Σ(x - x̄)²"""
    x_media, y_media = sum(xs) / len(xs), sum(ys) / len(ys)
    numerador = sum((x - x_media) * (y - y_media) for x, y in zip(xs, ys))
    denominador = sum((x - x_media) ** 2 for x in xs)
    return numerador / denominador if denominador else 0.0


def analizar_tendencia(insumo: str, region: str) -> dict:
    """Analiza el historial y recomienda si comprar ya o esperar.

    Reglas de la recomendación (simples a propósito, para poder explicarlas):
      - Se calcula la pendiente en COP por semana (regresión lineal) y se pasa a %
        del precio promedio → "pendiente_pct_semana".
      - pendiente ≤ -1 %/semana → "esperar"    (el precio viene bajando)
      - pendiente ≥ +1 %/semana → "comprar_ya" (el precio viene subiendo)
      - entre -1 % y +1 %       → "neutral"    (precio estable: comprar cuando se necesite)
    """
    historial = _historial_o_error(insumo, region)
    if isinstance(historial, dict):
        return historial
    if len(historial) < 2:
        return _error(f"Solo hay {len(historial)} dato de '{insumo}' en '{region}'; "
                      "se necesitan al menos 2 para ver una tendencia.", "sin_datos")

    try:
        fechas = [date.fromisoformat(f["fecha"]) for f in historial]
    except ValueError:
        return _error("Hay fechas con formato inválido en la base de datos.", "validacion")
    precios = [f["precio_cop"] for f in historial]
    semanas = [(d - fechas[0]).days / 7 for d in fechas]  # eje x en semanas

    promedio = sum(precios) / len(precios)
    pendiente = _pendiente(semanas, precios)
    pendiente_pct = pendiente / promedio * 100
    variacion_total = (precios[-1] - precios[0]) / precios[0] * 100
    variacion_semana = (precios[-1] - precios[-2]) / precios[-2] * 100
    unidad = historial[0]["unidad"]

    if pendiente_pct <= -UMBRAL_PCT_SEMANAL:
        recomendacion = "esperar"
        porque = (f"El precio viene bajando cerca de {_pct(abs(pendiente_pct))} por semana "
                  f"({_pesos(abs(pendiente))} menos por {unidad} cada semana), así que conviene esperar.")
    elif pendiente_pct >= UMBRAL_PCT_SEMANAL:
        recomendacion = "comprar_ya"
        porque = (f"El precio viene subiendo cerca de {_pct(pendiente_pct)} por semana "
                  f"({_pesos(pendiente)} más por {unidad} cada semana), así que conviene comprar ya.")
    else:
        recomendacion = "neutral"
        porque = (f"El precio está casi quieto ({_pct(pendiente_pct, signo=True)} por semana), "
                  "así que no hay apuro: compre cuando lo necesite.")

    return {
        "insumo": historial[0]["insumo"],
        "region": historial[0]["region"],
        "unidad": unidad,
        "n_datos": len(precios),
        "desde": historial[0]["fecha"],
        "hasta": historial[-1]["fecha"],
        "precio_actual_cop": precios[-1],
        "promedio_cop": round(promedio),
        "variacion_total_pct": round(variacion_total, 2),
        "variacion_ultima_semana_pct": round(variacion_semana, 2),
        "pendiente_cop_semana": round(pendiente),
        "pendiente_pct_semana": round(pendiente_pct, 2),
        "recomendacion": recomendacion,
        "porque": porque,
        "es_ejemplo": all(f["fuente"] == "ejemplo" for f in historial),
    }


def _get_con_reintento(url: str, params: dict, reintentos: int = 1) -> requests.Response:
    """GET con timeout y reintento ante timeout / caída de conexión.
    Los errores que quedan se dejan subir para que la herramienta los traduzca."""
    for intento in range(reintentos + 1):
        try:
            return requests.get(url, params=params, timeout=config.TIMEOUT_HTTP)
        except (requests.Timeout, requests.ConnectionError):
            if intento == reintentos:
                raise


def consultar_trm() -> dict:
    """TRM (dólar oficial) de los últimos 7 registros desde datos.gov.co.
    Nota: un registro puede cubrir varios días (el del viernes vale todo el fin de semana)."""
    try:
        resp = _get_con_reintento(config.url_trm(),
                                  {"$order": "vigenciadesde DESC", "$limit": 7})
        resp.raise_for_status()
        registros = resp.json()
        historial = [
            {"fecha": r["vigenciadesde"][:10], "valor": float(r["valor"])}
            for r in registros
        ]
    except requests.Timeout:
        return _error(f"La API de la TRM no respondió en {config.TIMEOUT_HTTP:.0f} s "
                      "(se intentó 2 veces).", "red")
    except requests.ConnectionError:
        return _error("No hubo conexión con la API de la TRM (datos.gov.co). "
                      "Revisa el internet o intenta más tarde.", "red")
    except requests.HTTPError as e:
        return _error(f"La API de la TRM respondió con error HTTP {getattr(e.response, 'status_code', '?')}.", "red")
    except requests.RequestException:
        return _error("Falló la petición a la API de la TRM.", "red")
    except (ValueError, KeyError, TypeError):  # JSON inválido o con otros campos
        return _error("La API de la TRM devolvió datos con un formato inesperado.", "red")
    if not historial:
        return _error("La API de la TRM no devolvió registros.", "red")

    actual, antigua = historial[0]["valor"], historial[-1]["valor"]
    variacion = (actual - antigua) / antigua * 100
    return {
        "trm_actual": actual,
        "fecha": historial[0]["fecha"],
        "variacion_semana_pct": round(variacion, 2),
        "tendencia_dolar": "subiendo" if variacion > 0.5 else "bajando" if variacion < -0.5 else "estable",
        "historial": historial,  # del más reciente al más viejo
        "fuente": FUENTE_TRM,
    }


def enviar_alerta(mensaje: str, chat_id: str | None = None) -> dict:
    """Envía un mensaje por Telegram con el bot configurado en .env.
    No se reintenta: si el envío llegó pero la respuesta se perdió, el productor
    recibiría la alerta dos veces."""
    if not isinstance(mensaje, str) or not mensaje.strip():
        return _error("El mensaje de la alerta está vacío.", "validacion")
    if len(mensaje) > LIMITE_MENSAJE:
        return _error(f"El mensaje tiene {len(mensaje)} caracteres; el máximo es {LIMITE_MENSAJE}. "
                      "Resúmelo.", "validacion")
    token, destino = config.TELEGRAM_BOT_TOKEN, chat_id or config.TELEGRAM_CHAT_ID
    if not token or not destino:
        faltan = [n for n, v in {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": destino}.items() if not v]
        return _error(f"Telegram no está configurado: falta {', '.join(faltan)} en el .env.", "config")

    # ⚠️ Los mensajes de error NUNCA incluyen la URL: lleva el token del bot.
    try:
        resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                             json={"chat_id": destino, "text": mensaje.strip()},
                             timeout=config.TIMEOUT_HTTP)
        datos = resp.json()
    except requests.Timeout:
        return _error(f"Telegram no respondió en {config.TIMEOUT_HTTP:.0f} s; la alerta pudo no llegar.", "red")
    except requests.RequestException:
        return _error("No hubo conexión con Telegram; la alerta no se envió.", "red")
    except ValueError:
        return _error(f"Telegram respondió algo inesperado (HTTP {resp.status_code}).", "red")

    if not isinstance(datos, dict) or not datos.get("ok"):
        descripcion = datos.get("description", "sin detalle") if isinstance(datos, dict) else "sin detalle"
        codigo = datos.get("error_code") if isinstance(datos, dict) else None
        # 401: token malo · 400/403/404: chat_id malo o el usuario no ha hablado con el bot
        tipo = "config" if codigo in (400, 401, 403, 404) else "red"
        return _error(f"Telegram rechazó la alerta: {descripcion}.", tipo)
    return {"enviado": True, "chat_id": str(destino),
            "message_id": datos.get("result", {}).get("message_id")}

def calcular_costo_compra(insumo: str, region: str, bultos: int)->dict:
    """costo total  de comprar N bultos al ultimo precio registrado"""
    if not isinstance(bultos, int) or bultos <= 0:
        return _error("la cantidad de bultos debe ser mayor a 0","validacion")

    historial = _historial_o_error(insumo, region)
    if isinstance(historial, dict):
        return historial

    precio = historial[-1]["precio_cop"]
    return {
        "insumo": historial[0]["insumo"],
        "region": historial[0]["region"],
        "bultos": bultos,
        "precio_unitario_cop": precio,
        "total_cop": precio * bultos,
        "es_ejemplo": all(f["fuente"] == "ejemplo" for f in historial)
    }

# ---------- 2. Esquemas (lo que "lee" el LLM) ----------
_PARAMS_INSUMO_REGION = {
    "type": "object",
    "properties": {
        "insumo": {"type": "string", "description": "Ej: urea, dap, kcl"},
        "region": {"type": "string", "description": "Ej: Santander, Boyaca, Meta"},
    },
    "required": ["insumo", "region"],
}

ESQUEMAS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_precios",
            "description": (
                "Obtiene el historial semanal de precios (COP) de un insumo agrícola "
                "en una región de Colombia. Úsala siempre antes de hablar de precios. "
                "Si no hay datos, el error trae las regiones o insumos que sí existen."
            ),
            "parameters": _PARAMS_INSUMO_REGION,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analizar_tendencia",
            "description": (
                "Analiza el historial de precios de un insumo en una región: variación total, "
                "variación de la última semana, promedio, pendiente semanal y una recomendación "
                "'comprar_ya', 'esperar' o 'neutral' con su porqué. Úsala antes de recomendar."
            ),
            "parameters": _PARAMS_INSUMO_REGION,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_trm",
            "description": (
                "Consulta la TRM (dólar oficial en Colombia) de los últimos días en datos.gov.co: "
                "valor actual y variación de la semana. Los fertilizantes son importados, así que "
                "un dólar al alza suele empujar sus precios hacia arriba."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enviar_alerta",
            "description": (
                "Envía un mensaje de alerta por Telegram al productor. Úsala SOLO si el usuario "
                "pide explícitamente que le avisen o le escriban por Telegram."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mensaje": {"type": "string",
                                "description": "Texto corto y claro (máx. 1000 caracteres)."},
                    "chat_id": {"type": "string",
                                "description": "Opcional. Déjalo vacío para usar el chat configurado."},
                },
                "required": ["mensaje"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calcular_costo_compra",
            "description": (
                "calcula cuanto cuestan N bultos de un insumo en una region al precio actual. "
                "Usalo cuando pregunten cuanto van a gastar en total"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_PARAMS_INSUMO_REGION["properties"],
                    "bultos" : {"type": "integer", "description": "numero de bultos a comprar(mayor a 0)"}, 
                },
                "required" : ["insumo", "region", "bultos"],
            }
        }
    },
]

# ---------- 3. Registro: nombre -> función ----------
REGISTRO = {
    "consultar_precios": consultar_precios,
    "analizar_tendencia": analizar_tendencia,
    "consultar_trm": consultar_trm,
    "enviar_alerta": enviar_alerta,
    "calcular_costo_compra": calcular_costo_compra,
}


def ejecutar(nombre: str, argumentos_json: str) -> str:
    """Ejecuta la herramienta que pidió el LLM y devuelve el resultado como texto JSON."""
    if nombre not in REGISTRO:
        return json.dumps(_error(f"Herramienta desconocida: {nombre}", "validacion"), ensure_ascii=False)
    try:
        argumentos = json.loads(argumentos_json or "{}")
        resultado = REGISTRO[nombre](**argumentos)
    except (json.JSONDecodeError, TypeError) as e:  # el LLM mandó argumentos mal formados
        resultado = _error(f"Argumentos inválidos para {nombre}: {e}", "validacion")
    except Exception as e:  # último seguro: el agente no debe morir nunca
        resultado = _error(f"Falló {nombre} inesperadamente: {e}", "validacion")
    return json.dumps(resultado, ensure_ascii=False)
