"""
herramientas.py — Las "manos" del agente 🔧
===========================================
Cada herramienta tiene 2 partes:
  1. La FUNCIÓN de Python que hace el trabajo.
  2. El ESQUEMA (JSON) que le explica al LLM qué hace y qué parámetros recibe.
El LLM nunca ejecuta código: solo PIDE "llama consultar_precios con X".
Nosotros ejecutamos y le devolvemos el resultado.

S3: los precios son REALES (DANE · SIPSA-Insumos), MENSUALES y por municipio:
  - consultar_precios          → últimos 12 meses del departamento (o de un municipio)
  - analizar_tendencia         → pendiente de los últimos 6 meses + mismo mes del año anterior
  - consultar_regiones_vecinas → último precio en los departamentos vecinos (más barato primero)
  - calcular_costo_compra      → N bultos al último precio real
  - consultar_trm              → API pública de datos.gov.co (dólar oficial)
  - enviar_alerta              → API de bots de Telegram

Contrato de TODAS las herramientas: siempre devuelven un dict y NUNCA lanzan
excepciones. Si algo falla devuelven:
    {"error": "<mensaje claro en español>", "tipo_error": "sin_datos|red|config|validacion"}
Así el LLM puede explicar qué pasó y seguir con lo que sí tiene.
"""
import json
import sqlite3

import requests

from agente import config
from agente.catalogo import (NOMBRES_CORTOS, PRESENTACIONES, VECINOS, resolver_departamento,
                             resolver_insumo)
from agente.datos import (BaseDeDatosNoEncontrada, buscar_departamento_de_municipio, buscar_historial,
                          municipios_disponibles, regiones_disponibles, ultimo_periodo_disponible,
                          ultimo_precio_por_departamento)

MESES_CONSULTA = 12  # consultar_precios devuelve solo el último año (menos tokens para el LLM)
MESES_TENDENCIA = 6  # ventana de la pendiente en analizar_tendencia
LIMITE_MENSAJE = 1000  # caracteres máximos de una alerta
FUENTE_TRM = "datos.gov.co · TRM certificada (Superintendencia Financiera)"
NOMBRES_MES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
               "septiembre", "octubre", "noviembre", "diciembre"]


def _error(mensaje: str, tipo: str) -> dict:
    """Forma única de los errores que ve el LLM."""
    return {"error": mensaje, "tipo_error": tipo}


def _pesos(valor: float) -> str:
    """171000 -> '$171.000' (formato colombiano)."""
    return "$" + f"{valor:,.0f}".replace(",", ".")


def _pct(valor: float, signo: bool = False) -> str:
    """2.06 -> '2,1%' (coma decimal, como se escribe en Colombia)."""
    return (f"{valor:+.1f}" if signo else f"{valor:.1f}").replace(".", ",") + "%"


# ---------- Ayudas para trabajar con meses 'AAAA-MM' ----------
def _indice(periodo: str) -> int:
    """'2026-09' -> meses contados desde el año 0. Así restar meses no tiene líos de año."""
    anio, mes = periodo.split("-")
    return int(anio) * 12 + int(mes) - 1


def _periodo(indice: int) -> str:
    """Inverso de _indice: 24320 -> '2026-09'."""
    return f"{indice // 12}-{indice % 12 + 1:02d}"


def _mes_texto(periodo: str) -> str:
    """'2026-09' -> 'septiembre 2026'."""
    return f"{NOMBRES_MES[int(periodo[5:]) - 1]} {periodo[:4]}"


def _vigencia(periodo: str, publicado: str) -> dict:
    """Qué tan viejo es el último dato de un lugar frente al último mes que publicó el DANE."""
    atraso = _indice(publicado) - _indice(periodo)
    return {"meses_de_atraso": atraso, "dato_desactualizado": atraso > config.MESES_DATO_VIGENTE}


def _resolver(insumo: str, region: str, municipio: str | None) -> tuple[str, str, str | None] | dict:
    """Traduce lo que mandó el LLM a nombres oficiales: (producto, departamento, municipio).
    Si en `region` viene un municipio ('Bucaramanga'), busca su departamento."""
    producto = resolver_insumo(insumo)
    if not producto:
        return _error(f"No hay datos de '{insumo}': no está en el catálogo del DANE que usamos. "
                      f"Insumos disponibles: {', '.join(NOMBRES_CORTOS.values())}.", "sin_datos")
    departamento = resolver_departamento(region)
    if not departamento:
        candidatos = buscar_departamento_de_municipio(config.RUTA_BD, region)
        if len(candidatos) != 1:
            return _error(f"'{region}' no es un departamento de Colombia. Usa el departamento en "
                          "`region` (ej: Santander) y, si quieres, el municipio en `municipio`.",
                          "validacion")
        departamento, municipio = candidatos[0][0], municipio or candidatos[0][1]
    return producto, departamento, municipio


def _historial_o_error(insumo: str, region: str, municipio: str | None = None,
                       meses: int = MESES_CONSULTA) -> tuple[list[dict], str] | dict:
    """Historial de los últimos `meses` publicados por el DANE + el último mes publicado.
    Si no hay datos, devuelve un error con las alternativas que SÍ existen (municipios del
    departamento o departamentos con datos recientes), para que el LLM pueda sugerirlas."""
    try:
        nombres = _resolver(insumo, region, municipio)
        if isinstance(nombres, dict):
            return nombres
        producto, departamento, municipio = nombres
        publicado = ultimo_periodo_disponible(config.RUTA_BD)
        if not publicado:
            return _error("La base de precios está vacía. Cárgala con: python scripts/actualizar_sipsa.py",
                          "config")
        desde = _periodo(_indice(publicado) - meses + 1)
        historial = buscar_historial(config.RUTA_BD, producto, departamento, municipio, desde)
        if historial:
            return historial, publicado

        corto = NOMBRES_CORTOS[producto]
        lugar = f"{municipio} ({departamento})" if municipio else departamento
        mensaje = (f"No hay datos de {corto} en {lugar} en los últimos {meses} meses publicados por "
                   f"el DANE (último mes publicado: {_mes_texto(publicado)}).")
        viejo = buscar_historial(config.RUTA_BD, producto, departamento, municipio)
        if viejo:
            mensaje += f" El último dato de {lugar} es de {_mes_texto(viejo[-1]['periodo'])}."
        otros = municipios_disponibles(config.RUTA_BD, departamento, producto) if municipio else []
        if otros:
            mensaje += f" En {departamento} hay datos de {corto} en: {', '.join(otros)}."
        else:
            recientes = regiones_disponibles(config.RUTA_BD, producto, desde)
            mensaje += f" Departamentos con datos de {corto}: {', '.join(recientes) or 'ninguno'}."
        return _error(mensaje, "sin_datos")
    except BaseDeDatosNoEncontrada as e:
        return _error(str(e), "config")
    except sqlite3.Error as e:
        return _error(f"No se pudo leer la base de datos de precios ({e}). "
                      "Actualízala con: python scripts/actualizar_sipsa.py", "config")


def _ubicacion(fila: dict) -> dict:
    """region (+ municipio si la serie es de un municipio)."""
    return {"region": fila["region"], **({"municipio": fila["municipio"]} if "municipio" in fila else {})}


def _referencia_departamento(ultimo: dict, publicado: str) -> dict:
    """Si el dato de un MUNICIPIO está desactualizado, agrega el último precio de su
    departamento para que el agente tenga una cifra reciente con qué comparar."""
    if "municipio" not in ultimo or not _vigencia(ultimo["periodo"], publicado)["dato_desactualizado"]:
        return {}
    try:
        del_departamento = buscar_historial(config.RUTA_BD, ultimo["insumo"], ultimo["region"],
                                            desde=_periodo(_indice(publicado) - MESES_CONSULTA + 1))
    except (BaseDeDatosNoEncontrada, sqlite3.Error):
        return {}
    if not del_departamento:
        return {}
    fila = del_departamento[-1]
    return {"referencia_departamento": {
        "region": fila["region"], "periodo": fila["periodo"], "precio_cop": fila["precio_cop"],
        "precio_min": fila["precio_min"], "precio_max": fila["precio_max"],
        "n_municipios": fila["n_municipios"], **_vigencia(fila["periodo"], publicado)}}


# ---------- 1. Funciones ----------
def consultar_precios(insumo: str, region: str, municipio: str | None = None) -> dict:
    """Precios MENSUALES de los últimos 12 meses de un insumo en un departamento
    (promedio de sus municipios, con rango min-max) o en un municipio."""
    resultado = _historial_o_error(insumo, region, municipio)
    if isinstance(resultado, dict):
        return resultado
    historial, publicado = resultado
    ultimo = historial[-1]
    return {
        "insumo": ultimo["insumo"],
        **_ubicacion(ultimo),
        "unidad": ultimo["unidad"],
        "ultimo_periodo": ultimo["periodo"],
        "ultimo_mes": _mes_texto(ultimo["periodo"]),
        "precio_actual_cop": ultimo["precio_cop"],
        "precio_min_cop": ultimo["precio_min"],
        "precio_max_cop": ultimo["precio_max"],
        "n_municipios": ultimo["n_municipios"],
        **_vigencia(ultimo["periodo"], publicado),
        **_referencia_departamento(ultimo, publicado),
        "fuente": f"DANE-SIPSA (mes publicado: {_mes_texto(publicado)})",
        "es_ejemplo": any(f["fuente"] == "ejemplo" for f in historial),  # True → precios FICTICIOS
        "historial": [{k: f[k] for k in ("periodo", "precio_cop", "precio_min", "precio_max", "n_municipios")}
                      for f in historial],
    }


def _pendiente(xs: list[float], ys: list[float]) -> float:
    """Regresión lineal simple (mínimos cuadrados) hecha a mano:
    pendiente = Σ(x - x̄)(y - ȳ) / Σ(x - x̄)²"""
    x_media, y_media = sum(xs) / len(xs), sum(ys) / len(ys)
    numerador = sum((x - x_media) * (y - y_media) for x, y in zip(xs, ys))
    denominador = sum((x - x_media) ** 2 for x in xs)
    return numerador / denominador if denominador else 0.0


def analizar_tendencia(insumo: str, region: str, municipio: str | None = None) -> dict:
    """Analiza los precios MENSUALES y recomienda si comprar ya o esperar.

    Reglas de la recomendación (simples a propósito, para poder explicarlas):
      - Con los últimos 6 meses se calcula la pendiente en COP por mes (regresión lineal;
        el eje x son meses reales, así un mes sin dato no deforma la recta) y se pasa a %
        del precio promedio → "pendiente_pct_mes".
      - pendiente ≤ -2 %/mes → "esperar"    (el precio viene bajando)
      - pendiente ≥ +2 %/mes → "comprar_ya" (el precio viene subiendo)
      - en medio             → "neutral"    (precio estable: comprar cuando se necesite)
      (el 2 % se cambia con UMBRAL_PCT_MENSUAL en el .env)
    Además compara contra el MISMO MES del año anterior, si existe (efecto de temporada).
    """
    resultado = _historial_o_error(insumo, region, municipio, meses=MESES_CONSULTA + 1)
    if isinstance(resultado, dict):
        return resultado
    historial, publicado = resultado
    ultimo = historial[-1]
    recientes = [f for f in historial if _indice(ultimo["periodo"]) - _indice(f["periodo"]) < MESES_TENDENCIA]
    if len(recientes) < 2:
        return _error(f"Solo hay {len(recientes)} mes con datos de {NOMBRES_CORTOS[ultimo['insumo']]} en "
                      f"{ultimo['region']} en los últimos {MESES_TENDENCIA} meses; se necesitan al menos 2 "
                      "para ver una tendencia.", "sin_datos")

    meses = [_indice(f["periodo"]) for f in recientes]
    precios = [f["precio_cop"] for f in recientes]
    promedio = sum(precios) / len(precios)
    pendiente = _pendiente(meses, precios)
    pendiente_pct = pendiente / promedio * 100
    umbral, unidad = config.UMBRAL_PCT_MENSUAL, ultimo["unidad"]
    anterior = recientes[-2]
    variacion_anterior = (precios[-1] - anterior["precio_cop"]) / anterior["precio_cop"] * 100
    hace_un_anio = _periodo(_indice(ultimo["periodo"]) - 12)
    anio_pasado = next((f for f in historial if f["periodo"] == hace_un_anio), None)

    if pendiente_pct <= -umbral:
        recomendacion = "esperar"
        porque = (f"En los últimos {MESES_TENDENCIA} meses el precio viene bajando cerca de "
                  f"{_pct(abs(pendiente_pct))} por mes ({_pesos(abs(pendiente))} menos por {unidad} "
                  "cada mes), así que conviene esperar.")
    elif pendiente_pct >= umbral:
        recomendacion = "comprar_ya"
        porque = (f"En los últimos {MESES_TENDENCIA} meses el precio viene subiendo cerca de "
                  f"{_pct(pendiente_pct)} por mes ({_pesos(pendiente)} más por {unidad} cada mes), "
                  "así que conviene comprar ya.")
    else:
        recomendacion = "neutral"
        porque = (f"En los últimos {MESES_TENDENCIA} meses el precio está casi quieto "
                  f"({_pct(pendiente_pct, signo=True)} por mes), así que no hay apuro: compre cuando lo necesite.")
    variacion_anual = None
    if anio_pasado:
        variacion_anual = (precios[-1] - anio_pasado["precio_cop"]) / anio_pasado["precio_cop"] * 100
        porque += (f" Frente a {_mes_texto(hace_un_anio)} ({_pesos(anio_pasado['precio_cop'])}) está "
                   f"{_pct(variacion_anual, signo=True)}.")

    return {
        "insumo": ultimo["insumo"],
        **_ubicacion(ultimo),
        "unidad": unidad,
        "n_meses": len(recientes),
        "desde": recientes[0]["periodo"],
        "hasta": ultimo["periodo"],
        "precio_actual_cop": precios[-1],
        "precio_min_cop": ultimo["precio_min"],
        "precio_max_cop": ultimo["precio_max"],
        "n_municipios": ultimo["n_municipios"],
        "promedio_6_meses_cop": round(promedio),
        "variacion_6_meses_pct": round((precios[-1] - precios[0]) / precios[0] * 100, 2),
        "variacion_vs_mes_anterior_pct": round(variacion_anterior, 2),
        "mes_anterior_con_dato": anterior["periodo"],
        "pendiente_cop_mes": round(pendiente),
        "pendiente_pct_mes": round(pendiente_pct, 2),
        "precio_mismo_mes_anio_anterior_cop": anio_pasado["precio_cop"] if anio_pasado else None,
        "variacion_anual_pct": round(variacion_anual, 2) if anio_pasado else None,
        "recomendacion": recomendacion,
        "porque": porque,
        **_vigencia(ultimo["periodo"], publicado),
        "fuente": f"DANE-SIPSA (mes publicado: {_mes_texto(publicado)})",
        "es_ejemplo": any(f["fuente"] == "ejemplo" for f in historial),
    }


def consultar_regiones_vecinas(insumo: str, region: str) -> dict:
    """Último precio disponible del insumo en cada departamento VECINO que tenga datos,
    del más barato al más caro. Sirve cuando en la región no hay datos (o son viejos)."""
    producto = resolver_insumo(insumo)
    if not producto:
        return _error(f"No hay datos de '{insumo}': no está en el catálogo del DANE que usamos. "
                      f"Insumos disponibles: {', '.join(NOMBRES_CORTOS.values())}.", "sin_datos")
    departamento = resolver_departamento(region)
    if not departamento:
        return _error(f"'{region}' no es un departamento de Colombia (ej: Santander, Boyacá, Meta).",
                      "validacion")
    vecinos = VECINOS[departamento]
    if not vecinos:
        return _error(f"{departamento} no tiene departamentos vecinos por tierra.", "sin_datos")
    corto = NOMBRES_CORTOS[producto]
    try:
        publicado = ultimo_periodo_disponible(config.RUTA_BD)
        opciones = ultimo_precio_por_departamento(config.RUTA_BD, producto, vecinos)
        propio = ultimo_precio_por_departamento(config.RUTA_BD, producto, [departamento])
        if not opciones:
            otros = regiones_disponibles(config.RUTA_BD, producto)
            return _error(f"Ningún vecino de {departamento} ({', '.join(vecinos)}) tiene datos de {corto}. "
                          f"Departamentos con datos de {corto}: {', '.join(otros) or 'ninguno'}.", "sin_datos")
    except BaseDeDatosNoEncontrada as e:
        return _error(str(e), "config")
    except sqlite3.Error as e:
        return _error(f"No se pudo leer la base de datos de precios ({e}). "
                      "Actualízala con: python scripts/actualizar_sipsa.py", "config")

    # Primero los vecinos con dato vigente (del más barato al más caro) y al final los de
    # dato viejo: un precio de hace un año "más barato" engañaría al productor.
    vigentes = sorted(({**o, **_vigencia(o["periodo"], publicado)} for o in opciones),
                      key=lambda o: (o["dato_desactualizado"], o["precio_cop"]))
    con_datos = {o["region"] for o in opciones}
    return {
        "insumo": producto,
        "region": departamento,
        "unidad": f"bulto de {PRESENTACIONES[producto]}",
        "precio_en_la_region": ({**propio[0], **_vigencia(propio[0]["periodo"], publicado)}
                                if propio else None),
        "mas_barato_vigente": next((o for o in vigentes if not o["dato_desactualizado"]), None),
        "vecinos": vigentes,
        "vecinos_sin_datos": [v for v in vecinos if v not in con_datos],
        "fuente": f"DANE-SIPSA (mes publicado: {_mes_texto(publicado)})",
        "es_ejemplo": False,
    }


def calcular_costo_compra(insumo: str, region: str, bultos: int, municipio: str | None = None) -> dict:
    """Costo total de comprar N bultos al último precio real (promedio del departamento,
    o del municipio si se indica), con el rango según el municipio."""
    if isinstance(bultos, bool) or not isinstance(bultos, int) or bultos <= 0:
        return _error("La cantidad de bultos debe ser un número entero mayor a 0.", "validacion")
    resultado = _historial_o_error(insumo, region, municipio)
    if isinstance(resultado, dict):
        return resultado
    historial, publicado = resultado
    ultimo = historial[-1]
    referencia = _referencia_departamento(ultimo, publicado)
    if referencia:  # el total también al precio reciente del departamento: el LLM no multiplica
        ref = referencia["referencia_departamento"]
        ref.update(total_cop=ref["precio_cop"] * bultos, total_min_cop=ref["precio_min"] * bultos,
                   total_max_cop=ref["precio_max"] * bultos)
    return {
        "insumo": ultimo["insumo"],
        **_ubicacion(ultimo),
        "unidad": ultimo["unidad"],
        "bultos": bultos,
        "periodo_precio": ultimo["periodo"],
        "precio_unitario_cop": ultimo["precio_cop"],
        "total_cop": ultimo["precio_cop"] * bultos,
        "total_min_cop": ultimo["precio_min"] * bultos,
        "total_max_cop": ultimo["precio_max"] * bultos,
        "n_municipios": ultimo["n_municipios"],
        **_vigencia(ultimo["periodo"], publicado),
        **referencia,
        "fuente": f"DANE-SIPSA (mes publicado: {_mes_texto(publicado)})",
        "es_ejemplo": any(f["fuente"] == "ejemplo" for f in historial),
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


# ---------- 2. Esquemas (lo que "lee" el LLM) ----------
_PROPIEDADES_LUGAR = {
    "insumo": {"type": "string", "description": "Ej: urea, dap, kcl, 15-15-15, 10-20-20"},
    "region": {"type": "string", "description": "DEPARTAMENTO de Colombia. Ej: Santander, Boyacá, Meta"},
    "municipio": {"type": "string",
                  "description": "Opcional. Municipio dentro del departamento (ej: Bucaramanga). "
                                 "Úsalo solo si el usuario nombra un municipio."},
}

_PARAMS_INSUMO_REGION = {
    "type": "object",
    "properties": _PROPIEDADES_LUGAR,
    "required": ["insumo", "region"],
}

ESQUEMAS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_precios",
            "description": (
                "Precios REALES del DANE (SIPSA) de un insumo agrícola en un departamento de Colombia "
                "(o en un municipio): últimos 12 meses, mensuales. Trae el último mes con dato, el "
                "precio promedio entre municipios, el rango min-max y si el dato está desactualizado. "
                "Si no hay datos, el error trae los municipios o departamentos que sí tienen."
            ),
            "parameters": _PARAMS_INSUMO_REGION,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analizar_tendencia",
            "description": (
                "Analiza la tendencia MENSUAL del precio de un insumo en un departamento: pendiente "
                "de los últimos 6 meses (% por mes), variación contra el mes anterior y contra el "
                "mismo mes del año pasado, y una recomendación 'comprar_ya', 'esperar' o 'neutral' "
                "con su porqué. Úsala cuando pregunten si comprar ahora o esperar."
            ),
            "parameters": _PARAMS_INSUMO_REGION,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_regiones_vecinas",
            "description": (
                "Último precio disponible de un insumo en los departamentos VECINOS de una región, "
                "del más barato al más caro. Úsala cuando en la región no hay datos o el dato está "
                "desactualizado, para ofrecer la alternativa más cercana y barata."
            ),
            "parameters": {
                "type": "object",
                "properties": {k: _PROPIEDADES_LUGAR[k] for k in ("insumo", "region")},
                "required": ["insumo", "region"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calcular_costo_compra",
            "description": (
                "Calcula cuánto cuestan N bultos de un insumo en un departamento (o municipio) al "
                "último precio real del DANE, con el rango según el municipio. Úsala cuando "
                "pregunten cuánto van a gastar en total."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_PROPIEDADES_LUGAR,
                    "bultos": {"type": "integer", "description": "Número de bultos a comprar (mayor a 0)"},
                },
                "required": ["insumo", "region", "bultos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_trm",
            "description": (
                "Consulta la TRM (dólar oficial en Colombia) de los últimos días en datos.gov.co: "
                "valor actual y variación de la semana. Los fertilizantes son importados, así que "
                "un dólar al alza suele empujar sus precios hacia arriba. Úsala solo para decidir "
                "si comprar ahora o esperar, no para preguntas de cuánto cuesta algo."
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
]

# ---------- 3. Registro: nombre -> función ----------
REGISTRO = {
    "consultar_precios": consultar_precios,
    "analizar_tendencia": analizar_tendencia,
    "consultar_regiones_vecinas": consultar_regiones_vecinas,
    "calcular_costo_compra": calcular_costo_compra,
    "consultar_trm": consultar_trm,
    "enviar_alerta": enviar_alerta,
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
