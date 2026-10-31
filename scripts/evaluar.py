"""
evaluar.py — Evaluación propia del agente y costo por tarea 🧪
=============================================================
Corre cada caso de evals/casos.json con el agente REAL (Grok), uno por uno, y revisa:
  ✔ usó las herramientas requeridas        ✔ no usó ninguna prohibida
  ✔ dice lo esperado (alguna alternativa)   ✔ no dice lo prohibido
  ✔ menciona el precio real de la BD       ✔ Grok no devolvió error
Un caso pasa solo si pasan TODAS sus revisiones; de cada fallo se guarda el motivo.

Los precios esperados NO están en el JSON (cambian cada mes): se calculan en vivo desde
la BD con agente/datos.py, igual que los calcula la herramienta.

Uso:
    python scripts/evaluar.py                               (todos los casos)
    python scripts/evaluar.py --categoria fuera_de_alcance
    python scripts/evaluar.py --id pd01 --repeticiones 3    (consistencia)
    python scripts/evaluar.py --pausa 5                     (segundos entre casos)
    python scripts/evaluar.py --recalcular-costo reportes/evaluacion_AAAAMMDD_HHMM.json
        (recalcula el costo de un reporte ya guardado con los precios del .env, sin llamar a Grok)

Deja el reporte en reportes/evaluacion_AAAAMMDD_HHMM.json y .md. Si se corrieron TODOS
los casos, el .md se copia a docs/evaluacion.md para mostrarlo en el repo.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# Permite correr el script directamente (python scripts/evaluar.py) e importar `agente`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agente import config  # noqa: E402
from agente.agente import _miles, calcular_costo_usd, ejecutar_agente, guardar_log  # noqa: E402
from agente.catalogo import VECINOS, normalizar, resolver_departamento  # noqa: E402
from agente.datos import (buscar_historial, ultimo_periodo_disponible,  # noqa: E402
                          ultimo_precio_por_departamento)
from agente.herramientas import REGISTRO, _pesos, consultar_trm  # noqa: E402
from agente.llm import crear_cliente  # noqa: E402

RUTA_CASOS = config.RAIZ / "evals" / "casos.json"
CARPETA_REPORTES = config.RAIZ / "reportes"
RUTA_DOCS = config.RAIZ / "docs" / "evaluacion.md"
CATEGORIAS = ("precio_directo", "tendencia", "costo", "municipio", "sin_datos_vecinos", "alias",
              "fuera_de_alcance", "fallas", "alerta")
CAMPOS = ("id", "categoria", "pregunta", "herramientas_requeridas", "herramientas_prohibidas",
          "debe_contener_alguno", "no_debe_contener", "verificar_precio", "simular_falla_trm")
PAUSA_POR_DEFECTO = 3  # segundos entre casos, para no chocar con el límite de peticiones


# ---------- Casos ----------
def cargar_casos(ruta: Path = RUTA_CASOS) -> list[dict]:
    """Lee los casos y falla con un mensaje claro si alguno está mal escrito."""
    casos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    ids = set()
    for caso in casos:
        faltan = [c for c in CAMPOS if c not in caso]
        if faltan:
            raise ValueError(f"Al caso {caso.get('id', '?')} le faltan los campos: {', '.join(faltan)}")
        if caso["categoria"] not in CATEGORIAS:
            raise ValueError(f"Caso {caso['id']}: categoría desconocida '{caso['categoria']}'")
        desconocidas = [h for h in caso["herramientas_requeridas"] + caso["herramientas_prohibidas"]
                        if h not in REGISTRO]
        if desconocidas:
            raise ValueError(f"Caso {caso['id']}: herramientas que no existen: {', '.join(desconocidas)}")
        if caso["id"] in ids:
            raise ValueError(f"Hay dos casos con el id '{caso['id']}'")
        ids.add(caso["id"])
    return casos


def filtrar(casos: list[dict], categoria: str | None = None, id_: str | None = None) -> list[dict]:
    return [c for c in casos if (not categoria or c["categoria"] == categoria) and (not id_ or c["id"] == id_)]


# ---------- Revisiones ----------
def _contiene(texto_normalizado: str, buscado: str) -> bool:
    """Busca `buscado` al INICIO de una palabra, sin tildes ni mayúsculas:
    'agronom' encuentra 'Agrónomo' y 'agrónoma'; 'ica' encuentra 'ICA' pero no 'técnica'.
    Si empieza por 're:' es una expresión regular sobre el texto normalizado (sin tildes,
    en minúsculas y con puntos/comas cambiados por espacios), ej. para detectar una dosis."""
    if buscado.startswith("re:"):
        return re.search(buscado[3:], texto_normalizado) is not None
    return re.search(r"(?<!\w)" + re.escape(normalizar(buscado)), texto_normalizado) is not None


def _grupos(debe: list) -> list[list[str]]:
    """debe_contener_alguno acepta una lista de textos (basta UNO) o una lista de grupos
    (en CADA grupo debe aparecer al menos uno)."""
    if all(isinstance(t, str) for t in debe):
        return [debe] if debe else []
    return [g if isinstance(g, list) else [g] for g in debe]


def numeros_en(texto: str) -> set[int]:
    """'$169.271 o unos 170 mil' -> {169271, 170000}. Acepta puntos o comas de miles."""
    numeros = set()
    for m in re.finditer(r"(\d{1,3}(?:[.,]\d{3})+|\d+)(\s*mil\b)?", texto or "", re.IGNORECASE):
        valor = int(re.sub(r"[.,]", "", m.group(1)))
        numeros.add(valor * 1000 if m.group(2) else valor)
    return numeros


def menciona_precio(texto: str, esperado: int) -> bool:
    """El número exacto ('169.271') o redondeado a miles ('169.000', '170.000', '169 mil')."""
    aceptados = {esperado, esperado // 1000 * 1000, (esperado + 500) // 1000 * 1000}
    return bool(numeros_en(texto) & aceptados)


def _meses(periodo: str) -> int:
    anio, mes = periodo.split("-")
    return int(anio) * 12 + int(mes)


def precio_esperado(verificar: dict) -> tuple[int, str] | None:
    """Precio que DEBERÍA decir el agente, calculado en vivo desde la BD con datos.py.
    - normal: último precio del departamento (promedio de municipios) o del municipio
    - con "bultos": ese precio × bultos
    - con "vecino_mas_barato": el vecino más barato con dato vigente
    Devuelve (valor, de dónde sale) o None si la BD no tiene el dato."""
    if verificar.get("vecino_mas_barato"):
        departamento = resolver_departamento(verificar["region"])
        publicado = ultimo_periodo_disponible(config.RUTA_BD)
        vigentes = [o for o in ultimo_precio_por_departamento(config.RUTA_BD, verificar["insumo"],
                                                              VECINOS.get(departamento, []))
                    if _meses(publicado) - _meses(o["periodo"]) <= config.MESES_DATO_VIGENTE]
        if not vigentes:
            return None
        o = vigentes[0]  # ya vienen del más barato al más caro
        return o["precio_cop"], f"vecino más barato: {o['region']}, {o['periodo']}"
    historial = buscar_historial(config.RUTA_BD, verificar["insumo"], verificar["region"],
                                 verificar.get("municipio"))
    if not historial:
        return None
    ultimo, bultos = historial[-1], verificar.get("bultos") or 1
    lugar = f"{ultimo.get('municipio', '')} {ultimo['region']}".strip()
    detalle = f"{lugar}, {ultimo['periodo']}" + (f", {bultos} bultos" if bultos > 1 else "")
    return ultimo["precio_cop"] * bultos, detalle


def telegram_configurado() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def revisar(caso: dict, salida: dict, telegram_ok: bool | None = None) -> list[str]:
    """Todas las revisiones de un caso. Devuelve los motivos de fallo ([] = aprobado)."""
    telegram_ok = telegram_configurado() if telegram_ok is None else telegram_ok
    pasos = [p for p in salida["rastro"] if p["tipo"] == "herramienta"]
    usadas = [p["nombre"] for p in pasos]
    texto = normalizar(salida.get("respuesta") or "")
    fallos = []

    if salida.get("error_llm"):
        fallos.append(f"error de Grok: {salida['error_llm']}")
    faltan = [h for h in caso["herramientas_requeridas"] if h not in usadas]
    if faltan:
        fallos.append(f"no usó: {', '.join(faltan)}")
    prohibidas = sorted(set(usadas) & set(caso["herramientas_prohibidas"]))
    if prohibidas:
        fallos.append(f"usó prohibida: {', '.join(prohibidas)}")

    debe = caso["debe_contener_alguno"]
    alertas = [p for p in pasos if p["nombre"] == "enviar_alerta"]
    if caso["categoria"] == "alerta" and not telegram_ok:
        # Sin Telegram se espera un error "config" bien explicado, no un envío
        debe = caso.get("alternativa_sin_telegram", {}).get("debe_contener_alguno", debe)
        if alertas and not any(p.get("tipo_error") == "config" for p in alertas):
            fallos.append("Telegram no está configurado pero enviar_alerta no devolvió error 'config'")
    elif caso["categoria"] == "alerta" and alertas and not any(p["exito"] for p in alertas):
        fallos.append(f"la alerta no se envió: {alertas[-1].get('error', 'sin detalle')}")
    for grupo in _grupos(debe):
        if not any(_contiene(texto, t) for t in grupo):
            muestra = " / ".join(grupo[:4]) + (" / …" if len(grupo) > 4 else "")
            fallos.append(f"no dice ninguno de: {muestra}")
    dichos = [t for t in caso["no_debe_contener"] if _contiene(texto, t)]
    if dichos:
        fallos.append(f"dice lo prohibido: {', '.join(repr(t) for t in dichos)}")

    if caso["simular_falla_trm"] and any(p["nombre"] == "consultar_trm" and p["exito"] for p in pasos):
        fallos.append("la falla simulada de la TRM no ocurrió (consultar_trm respondió bien)")

    if caso["verificar_precio"]:
        esperado = precio_esperado(caso["verificar_precio"])
        if esperado is None:
            fallos.append("la BD no tiene el precio para verificar (revisa el caso)")
        elif not menciona_precio(salida.get("respuesta") or "", esperado[0]):
            fallos.append(f"no menciona el precio esperado {_pesos(esperado[0])} ({esperado[1]})")
    return fallos


# ---------- Ejecución ----------
def correr_caso(caso: dict, cliente, modelo: str) -> dict:
    """Corre el agente con la pregunta del caso (activando la caída de la TRM si se pide)."""
    os.environ.pop("SIMULAR_FALLA_TRM", None)
    if caso["simular_falla_trm"]:
        os.environ["SIMULAR_FALLA_TRM"] = "1"
    try:
        return ejecutar_agente(caso["pregunta"], cliente, modelo)
    finally:
        os.environ.pop("SIMULAR_FALLA_TRM", None)


def evaluar(casos: list[dict], cliente, modelo: str, repeticiones: int = 1, pausa: float = PAUSA_POR_DEFECTO,
            dormir=time.sleep, guardar_logs: bool = True) -> list[dict]:
    """Corre cada caso `repeticiones` veces, con `pausa` segundos entre corridas."""
    resultados, total, n = [], len(casos) * repeticiones, 0
    for caso in casos:
        corridas = []
        for _ in range(repeticiones):
            if n:
                dormir(pausa)
            n += 1
            salida = correr_caso(caso, cliente, modelo)
            if guardar_logs:
                guardar_log(caso["pregunta"], {"caso": caso["id"], **salida})
            fallos = revisar(caso, salida)
            corridas.append({
                "aprobado": not fallos, "fallos": fallos, "respuesta": salida.get("respuesta") or "",
                "herramientas": [{k: p.get(k) for k in ("nombre", "argumentos", "exito", "tipo_error")}
                                 for p in salida["rastro"] if p["tipo"] == "herramienta"],
                "uso": salida["uso"],
            })
            u = salida["uso"]
            print(f"  [{n}/{total}] {caso['id']:<5} {'✅' if not fallos else '❌'}  "
                  f"{u['llamadas_llm']} llamadas · {_miles(u['duracion_ms'] / 1000, 1)} s"
                  + (f"  → {fallos[0]}" if fallos else ""), flush=True)
        resultados.append({k: caso[k] for k in ("id", "categoria", "pregunta")} | {"corridas": corridas})
    return resultados


# ---------- Resumen ----------
def _promedio(valores: list) -> float | None:
    valores = [v for v in valores if v is not None]
    return sum(valores) / len(valores) if valores else None


def _promedio_uso(usos: list[dict]) -> dict:
    claves = ("llamadas_llm", "tokens_entrada", "tokens_salida", "tokens_total", "duracion_ms", "costo_usd")
    return {k: _promedio([u[k] for u in usos]) for k in claves}


def resumir(resultados: list[dict], trm: dict | None = None, modelo: str = "") -> dict:
    """% aprobado (total, por categoría), consistencia, uso promedio y costo por tarea."""
    corridas = [c for r in resultados for c in r["corridas"]]
    repeticiones = max((len(r["corridas"]) for r in resultados), default=1)
    casos = []
    for r in resultados:
        aprobadas = sum(c["aprobado"] for c in r["corridas"])
        fallos = list(dict.fromkeys(f for c in r["corridas"] for f in c["fallos"]))  # sin repetidos
        casos.append({k: r[k] for k in ("id", "categoria", "pregunta")} | {
            "aprobadas": aprobadas, "corridas": len(r["corridas"]),
            "consistente": aprobadas in (0, len(r["corridas"])),
            "fallos": fallos, "uso_promedio": _promedio_uso([c["uso"] for c in r["corridas"]]),
            "respuesta": r["corridas"][-1]["respuesta"], "herramientas": r["corridas"][-1]["herramientas"]})

    por_categoria = {}
    for r in resultados:
        cat = por_categoria.setdefault(r["categoria"], {"corridas": 0, "aprobadas": 0})
        cat["corridas"] += len(r["corridas"])
        cat["aprobadas"] += sum(c["aprobado"] for c in r["corridas"])
    for cat in por_categoria.values():
        cat["pct"] = round(cat["aprobadas"] / cat["corridas"] * 100, 1)

    promedio = _promedio_uso([c["uso"] for c in corridas])
    trm_valor = (trm or {}).get("trm_actual")
    promedio["costo_cop"] = (promedio["costo_usd"] * trm_valor
                             if promedio["costo_usd"] is not None and trm_valor else None)
    con_costo = [c for c in casos if c["uso_promedio"]["costo_usd"] is not None]
    criterio_caro = "costo_usd" if con_costo else "tokens_total"
    candidatos = con_costo or [c for c in casos if c["uso_promedio"]["tokens_total"] is not None]
    mas_caro = max(candidatos, key=lambda c: c["uso_promedio"][criterio_caro], default=None)
    mas_lento = max(casos, key=lambda c: c["uso_promedio"]["duracion_ms"] or 0, default=None)
    costos = [c["uso"]["costo_usd"] for c in corridas]

    return {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "modelo": modelo,
        "n_casos": len(resultados),
        "repeticiones": repeticiones,
        "n_corridas": len(corridas),
        "aprobadas": sum(c["aprobado"] for c in corridas),
        "aprobado_pct": round(sum(c["aprobado"] for c in corridas) / len(corridas) * 100, 1) if corridas else 0,
        "por_categoria": por_categoria,
        "consistencia_pct": (round(sum(c["consistente"] for c in casos) / len(casos) * 100, 1)
                             if repeticiones > 1 and casos else None),
        "promedio_por_tarea": promedio,
        "costo_total_usd": sum(costos) if costos and None not in costos else None,
        "precios_configurados": None not in (config.PRECIO_ENTRADA_USD_MILLON, config.PRECIO_SALIDA_USD_MILLON),
        "trm": {"valor": trm_valor, "fecha": trm.get("fecha")} if trm_valor else None,
        "mas_caro": ({"id": mas_caro["id"], "criterio": criterio_caro,
                      "valor": mas_caro["uso_promedio"][criterio_caro]} if mas_caro else None),
        "mas_lento": ({"id": mas_lento["id"], "duracion_ms": mas_lento["uso_promedio"]["duracion_ms"]}
                      if mas_lento else None),
        "telegram_configurado": telegram_configurado(),
        "casos": casos,
    }


# ---------- Formato y reportes ----------
def _n(valor, decimales: int = 0, vacio: str = "n/d") -> str:
    return vacio if valor is None else _miles(valor, decimales)


def _usd(valor) -> str:
    return "sin precio" if valor is None else f"${_miles(valor, 4)}"


def _resultado(caso: dict) -> str:
    icono = "✅" if caso["aprobadas"] == caso["corridas"] else "❌"
    return icono if caso["corridas"] == 1 else f"{icono} {caso['aprobadas']}/{caso['corridas']}"


def _uso_promedio_md(resumen: dict) -> list[str]:
    p = resumen["promedio_por_tarea"]
    cop = f"${_n(p['costo_cop'])} COP" if p["costo_cop"] is not None else "n/d (sin precio o sin TRM)"
    caro, lento = resumen["mas_caro"], resumen["mas_lento"]
    caro_txt = "n/d" if not caro else (
        f"`{caro['id']}` ({_usd(caro['valor'])} USD)" if caro["criterio"] == "costo_usd"
        else f"`{caro['id']}` ({_n(caro['valor'])} tokens)")
    lento_txt = f"`{lento['id']}` ({_n(lento['duracion_ms'] / 1000, 1)} s)" if lento else "n/d"
    trm = resumen["trm"]
    trm_txt = f"${_n(trm['valor'], 2)} ({trm['fecha']})" if trm else "no disponible (solo USD)"
    return [
        "| Promedio por tarea | Valor |", "|---|---|",
        f"| Llamadas a Grok | {_n(p['llamadas_llm'], 1)} |",
        f"| Tokens de entrada | {_n(p['tokens_entrada'])} |",
        f"| Tokens de salida | {_n(p['tokens_salida'])} |",
        f"| Tokens totales | {_n(p['tokens_total'])} |",
        f"| Duración | {_n(p['duracion_ms'] and p['duracion_ms'] / 1000, 1)} s |",
        f"| **Costo USD** | **{_usd(p['costo_usd'])}** |",
        f"| **Costo COP** | **{cop}** |",
        f"| Caso más caro | {caro_txt} |",
        f"| Caso más lento | {lento_txt} |",
        f"| TRM usada | {trm_txt} |",
    ]


def a_markdown(resumen: dict) -> str:
    """Reporte legible para docs/evaluacion.md."""
    lineas = [
        "# 🧪 Evaluación propia del agente", "",
        f"- **Fecha:** {resumen['fecha']} · **Modelo:** `{resumen['modelo']}`",
        f"- **Casos:** {resumen['n_casos']} · **Repeticiones:** {resumen['repeticiones']} · "
        f"**Corridas:** {resumen['n_corridas']}",
        f"- **Aprobado total:** {resumen['aprobado_pct']} % ({resumen['aprobadas']}/{resumen['n_corridas']})",
    ]
    if resumen["consistencia_pct"] is not None:
        lineas.append(f"- **Consistencia:** {resumen['consistencia_pct']} % de los casos dieron el mismo "
                      "resultado en todas sus repeticiones")
    if not resumen["precios_configurados"]:
        lineas.append("- ⚠️ Sin PRECIO_ENTRADA_USD_MILLON / PRECIO_SALIDA_USD_MILLON en el .env: costo n/d")
    if resumen.get("costo_recalculado"):
        r = resumen["costo_recalculado"]
        lineas.append(f"- 💲 Costo recalculado el {r['fecha']} con los tokens guardados y "
                      f"${_n(r['precio_entrada_usd_millon'], 2)} (entrada) / ${_n(r['precio_salida_usd_millon'], 2)} "
                      "(salida) USD por millón de tokens")
    if resumen.get("costo_total_usd") is not None:
        lineas.append(f"- **Costo total de la corrida:** {_usd(resumen['costo_total_usd'])} USD")
    if not resumen["telegram_configurado"]:
        lineas.append("- ℹ️ Telegram sin configurar: en `alerta` se espera el error 'config' bien explicado")
    lineas += ["", "## Por categoría", "", "| Categoría | Aprobado | % |", "|---|---|---|"]
    for cat, d in resumen["por_categoria"].items():
        lineas.append(f"| {cat} | {d['aprobadas']}/{d['corridas']} | {d['pct']} % |")
    lineas += ["", "## Costo por tarea", "", *_uso_promedio_md(resumen), "",
               "## Por caso", "",
               "| Caso | Categoría | Resultado | Llamadas | Tokens entrada | Tokens salida | Duración | USD | Motivo |",
               "|---|---|---|---|---|---|---|---|---|"]
    for c in resumen["casos"]:
        u = c["uso_promedio"]
        motivo = "; ".join(c["fallos"]).replace("|", "/") or "—"
        lineas.append(f"| {c['id']} | {c['categoria']} | {_resultado(c)} | {_n(u['llamadas_llm'], 1)} | "
                      f"{_n(u['tokens_entrada'])} | {_n(u['tokens_salida'])} | "
                      f"{_n(u['duracion_ms'] / 1000, 1)} s | {_usd(u['costo_usd'])} | {motivo} |")
    fallidos = [c for c in resumen["casos"] if c["fallos"]]
    if fallidos:
        lineas += ["", "## Detalle de los fallos", ""]
        for c in fallidos:
            usadas = ", ".join(h["nombre"] for h in c["herramientas"]) or "ninguna"
            respuesta = " ".join(c["respuesta"].split())[:500]
            lineas += [f"### {c['id']} · {c['categoria']}", "", f"**Pregunta:** {c['pregunta']}", "",
                       f"**Herramientas:** {usadas}", "", "**Motivos:**",
                       *[f"- {f}" for f in c["fallos"]], "", f"> {respuesta}", ""]
    return "\n".join(lineas) + "\n"


def _sin_secretos(texto: str) -> str:
    """Borra la API key, el token y el chat de Telegram si aparecieran en el reporte."""
    for secreto in (config.XAI_API_KEY, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID):
        if secreto and len(secreto) >= 4:
            texto = texto.replace(secreto, "***")
    return texto


def _escribir_reporte(resumen: dict, ruta_json: Path, copiar_a: Path | None = None) -> tuple[Path, Path]:
    """Escribe el .json y su .md al lado (y copia el .md a `copiar_a` si se pide)."""
    ruta_md = ruta_json.with_suffix(".md")
    ruta_json.write_text(_sin_secretos(json.dumps(resumen, ensure_ascii=False, indent=2)), encoding="utf-8")
    ruta_md.write_text(_sin_secretos(a_markdown(resumen)), encoding="utf-8")
    if copiar_a:
        copiar_a.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ruta_md, copiar_a)
    return ruta_json, ruta_md


def guardar_reportes(resumen: dict, carpeta: Path = CARPETA_REPORTES, copiar_a: Path | None = None) -> tuple[Path, Path]:
    """Escribe evaluacion_AAAAMMDD_HHMM.json y .md (y copia el .md a `copiar_a` si se pide)."""
    carpeta.mkdir(parents=True, exist_ok=True)
    return _escribir_reporte(resumen, carpeta / f"evaluacion_{datetime.now():%Y%m%d_%H%M}.json", copiar_a)


def recalcular_costo(resumen: dict) -> dict:
    """Recalcula el costo de un reporte guardado con los precios ACTUALES del .env, a partir
    de los tokens que ya tiene (sin volver a llamar a Grok). Como el costo es lineal en los
    tokens, el costo del promedio de tokens es igual al promedio de los costos."""
    for caso in resumen["casos"]:
        u = caso["uso_promedio"]
        u["costo_usd"] = calcular_costo_usd(u["tokens_entrada"], u["tokens_salida"])
    p = resumen["promedio_por_tarea"]
    p["costo_usd"] = calcular_costo_usd(p["tokens_entrada"], p["tokens_salida"])
    trm_valor = (resumen.get("trm") or {}).get("valor")
    p["costo_cop"] = p["costo_usd"] * trm_valor if p["costo_usd"] is not None and trm_valor else None
    costos = [c["uso_promedio"]["costo_usd"] * c["corridas"] for c in resumen["casos"]]
    resumen["costo_total_usd"] = sum(costos) if costos and None not in costos else None
    resumen["precios_configurados"] = None not in (config.PRECIO_ENTRADA_USD_MILLON,
                                                   config.PRECIO_SALIDA_USD_MILLON)
    con_costo = [c for c in resumen["casos"] if c["uso_promedio"]["costo_usd"] is not None]
    if con_costo:
        caro = max(con_costo, key=lambda c: c["uso_promedio"]["costo_usd"])
        resumen["mas_caro"] = {"id": caro["id"], "criterio": "costo_usd", "valor": caro["uso_promedio"]["costo_usd"]}
    resumen["costo_recalculado"] = {"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                    "precio_entrada_usd_millon": config.PRECIO_ENTRADA_USD_MILLON,
                                    "precio_salida_usd_millon": config.PRECIO_SALIDA_USD_MILLON}
    return resumen


def imprimir(resumen: dict) -> None:
    """Tabla por caso + resumen en consola."""
    print("\n" + "=" * 100)
    print(f"{'Caso':<6}{'Categoría':<19}{'Res.':<8}{'Llam.':>6}{'Tokens':>9}{'Seg.':>7}{'USD':>11}  Motivo")
    print("-" * 100)
    for c in resumen["casos"]:
        u = c["uso_promedio"]
        print(f"{c['id']:<6}{c['categoria']:<19}{_resultado(c):<8}{_n(u['llamadas_llm'], 1):>6}"
              f"{_n(u['tokens_total']):>9}{_n(u['duracion_ms'] / 1000, 1):>7}{_usd(u['costo_usd']):>11}  "
              f"{'; '.join(c['fallos'])}")
    print("=" * 100)
    print(f"✅ Aprobado total: {resumen['aprobado_pct']} % ({resumen['aprobadas']}/{resumen['n_corridas']})")
    for cat, d in resumen["por_categoria"].items():
        print(f"   · {cat:<19} {d['aprobadas']}/{d['corridas']}  ({d['pct']} %)")
    if resumen["consistencia_pct"] is not None:
        print(f"🔁 Consistencia: {resumen['consistencia_pct']} %")
    print()
    for fila in _uso_promedio_md(resumen)[2:]:
        print("   " + fila.strip("|").replace(" | ", ": ").replace("**", "").strip())


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # emojis sin errores en la consola de Windows
    parser = argparse.ArgumentParser(description="Evalúa el agente con los casos de evals/casos.json")
    parser.add_argument("--categoria", choices=CATEGORIAS)
    parser.add_argument("--id", help="corre solo el caso con este id (ej: pd01)")
    parser.add_argument("--repeticiones", type=int, default=1, help="veces que se repite cada caso")
    parser.add_argument("--pausa", type=float, default=PAUSA_POR_DEFECTO, help="segundos entre casos")
    parser.add_argument("--recalcular-costo", metavar="REPORTE_JSON", type=Path,
                        help="recalcula el costo de un reporte ya guardado con los precios actuales del .env")
    args = parser.parse_args(argv)
    if args.repeticiones < 1:
        parser.error("--repeticiones debe ser 1 o más")

    if args.recalcular_costo:
        if None in (config.PRECIO_ENTRADA_USD_MILLON, config.PRECIO_SALIDA_USD_MILLON):
            raise SystemExit("❌ Pon PRECIO_ENTRADA_USD_MILLON y PRECIO_SALIDA_USD_MILLON en el .env.")
        ruta = args.recalcular_costo
        resumen = recalcular_costo(json.loads(ruta.read_text(encoding="utf-8")))
        completa = resumen["n_casos"] == len(cargar_casos())  # solo una corrida completa va a docs/
        imprimir(resumen)
        ruta_json, ruta_md = _escribir_reporte(resumen, ruta, RUTA_DOCS if completa else None)
        print(f"\n📄 Recalculado: {ruta_json} · {ruta_md}" + (f"\n📌 Copiado a {RUTA_DOCS}" if completa else ""))
        return

    casos = filtrar(cargar_casos(), args.categoria, args.id)
    if not casos:
        raise SystemExit("❌ Ningún caso coincide con el filtro.")
    cliente = crear_cliente()
    print(f"🧪 {len(casos)} casos × {args.repeticiones} · modelo {config.GROK_MODEL} · pausa {args.pausa:g} s\n")
    resultados = evaluar(casos, cliente, config.GROK_MODEL, args.repeticiones, args.pausa)

    trm = consultar_trm()  # para pasar el costo a pesos; si falla, el reporte queda solo en USD
    resumen = resumir(resultados, None if "error" in trm else trm, config.GROK_MODEL)
    imprimir(resumen)
    completa = not (args.categoria or args.id)
    ruta_json, ruta_md = guardar_reportes(resumen, copiar_a=RUTA_DOCS if completa else None)
    print(f"\n📄 Reportes: {ruta_json.relative_to(config.RAIZ)} · {ruta_md.relative_to(config.RAIZ)}"
          + (f"\n📌 Copiado a {RUTA_DOCS.relative_to(config.RAIZ)}" if completa else ""))


if __name__ == "__main__":
    main()
