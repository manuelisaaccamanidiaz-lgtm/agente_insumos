"""
Pruebas del evaluador SIN gastar API ni usar internet 🧪
Un LLM falso sigue un guion fijo (pedir herramientas → responder un texto) y el evaluador
revisa la salida igual que con Grok. La BD es la temporal de conftest.py (precios
FICTICIOS: la urea en Santander está en $163.000 en septiembre de 2026).
"""
import json
from types import SimpleNamespace as NS

from agente import config
from scripts import evaluar
from scripts.evaluar import (cargar_casos, correr_caso, menciona_precio, numeros_en, precio_esperado,
                             resumir, revisar)

USO = NS(prompt_tokens=1000, completion_tokens=100)


class LLMGuion:
    """Pide las herramientas de `herramientas` (una por vuelta) y luego responde `texto`.
    Cuando empieza una conversación nueva (solo system + user) vuelve al inicio del guion."""
    def __init__(self, texto, herramientas=()):
        self.texto, self.herramientas, self.paso = texto, list(herramientas), 0
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, model, messages, tools):
        if len(messages) == 2:
            self.paso = 0
        if self.paso < len(self.herramientas):
            nombre, argumentos = self.herramientas[self.paso]
            self.paso += 1
            tc = NS(id=f"call_{self.paso}", function=NS(name=nombre, arguments=json.dumps(argumentos)))
            return NS(choices=[NS(message=NS(content=None, tool_calls=[tc]))], usage=USO)
        return NS(choices=[NS(message=NS(content=self.texto, tool_calls=None))], usage=USO)


def _caso(**cambios):
    caso = {"id": "x01", "categoria": "precio_directo", "pregunta": "¿Cuánto vale la urea en Santander?",
            "herramientas_requeridas": ["consultar_precios"],
            "herramientas_prohibidas": ["consultar_trm", "enviar_alerta"],
            "debe_contener_alguno": ["septiembre", "agosto"], "no_debe_contener": ["por hectarea"],
            "verificar_precio": None, "simular_falla_trm": False}
    return caso | cambios


UREA_SANTANDER = ("consultar_precios", {"insumo": "urea", "region": "Santander"})


def _correr(caso, texto, herramientas=(UREA_SANTANDER,), telegram_ok=False):
    salida = correr_caso(caso, LLMGuion(texto, herramientas), "modelo-falso")
    return revisar(caso, salida, telegram_ok=telegram_ok)


# ---------- Revisiones de un caso ----------
def test_caso_que_pasa():
    assert _correr(_caso(), "Según el DANE, en SEPTIEMBRE de 2026 la urea está en $163.000.") == []


def test_caso_falla_por_herramienta_prohibida():
    fallos = _correr(_caso(), "En septiembre la urea está en $163.000 y el dólar sube.",
                     [UREA_SANTANDER, ("consultar_trm", {})])
    assert fallos == ["usó prohibida: consultar_trm"]


def test_caso_falla_por_herramienta_requerida_que_no_uso():
    assert _correr(_caso(), "En septiembre la urea está en $163.000.", []) == ["no usó: consultar_precios"]


def test_caso_falla_por_texto_prohibido_sin_importar_tildes_ni_mayusculas():
    fallos = _correr(_caso(), "En septiembre: $163.000. Échele 2 bultos POR HECTÁREA.")
    assert fallos == ["dice lo prohibido: 'por hectarea'"]


def test_caso_falla_si_no_dice_lo_esperado():
    fallos = _correr(_caso(), "La urea está en $163.000.")
    assert fallos == ["no dice ninguno de: septiembre / agosto"]


def test_grupos_de_textos_esperados_cada_grupo_debe_aparecer():
    caso = _caso(debe_contener_alguno=[["agronom", "ica"], ["etiqueta", "factura"]],
                 herramientas_requeridas=[])
    assert _correr(caso, "Consulte al ICA y guarde la factura.", []) == []
    assert _correr(caso, "Consulte a un agrónomo.", []) == ["no dice ninguno de: etiqueta / factura"]


def test_texto_esperado_busca_al_inicio_de_palabra():
    caso = _caso(debe_contener_alguno=["ica"], herramientas_requeridas=[])
    assert _correr(caso, "Pida asistencia técnica.", []) == ["no dice ninguno de: ica"]  # 'técnica' no es 'ICA'


def test_verificar_precio_en_vivo_desde_la_bd():
    caso = _caso(verificar_precio={"insumo": "urea", "region": "Santander", "municipio": None})
    assert precio_esperado(caso["verificar_precio"])[0] == 163000
    assert _correr(caso, "En septiembre de 2026 la urea vale alrededor de $163.000.") == []
    fallos = _correr(caso, "En septiembre de 2026 la urea vale alrededor de $150.000.")
    assert fallos == ["no menciona el precio esperado $163.000 (Santander, 2026-09)"]


def test_verificar_precio_con_bultos_y_municipio():
    verificar = {"insumo": "urea", "region": "Santander", "municipio": None, "bultos": 10}
    assert precio_esperado(verificar)[0] == 1630000
    municipio = precio_esperado({"insumo": "urea", "region": "Santander", "municipio": "Bucaramanga"})
    assert municipio is not None and municipio[1].startswith("Bucaramanga Santander")


def test_verificar_precio_sin_datos_en_la_bd_es_fallo_del_caso():
    caso = _caso(verificar_precio={"insumo": "glifosato", "region": "Nariño", "municipio": None})
    assert "la BD no tiene el precio para verificar (revisa el caso)" in _correr(caso, "En septiembre: $1.")


def test_menciona_precio_exacto_o_redondeado_a_miles():
    assert numeros_en("$169.271 o 169,271 o unos 170 mil") == {169271, 170000}
    assert menciona_precio("alrededor de $169.271", 169271)
    assert menciona_precio("unos $169.000", 169271)      # truncado a miles
    assert menciona_precio("cerca de 170 mil pesos", 169600)  # redondeado a miles
    assert not menciona_precio("$168.000", 169271)
    assert not menciona_precio("sin precio", 169271)


def test_error_de_grok_hace_fallar_el_caso():
    caso = _caso(herramientas_requeridas=[], debe_contener_alguno=[])
    salida = {"respuesta": "⚠️ 429", "rastro": [], "error_llm": "Grok está limitando (429)",
              "uso": {"llamadas_llm": 1}}
    assert revisar(caso, salida, telegram_ok=True) == ["error de Grok: Grok está limitando (429)"]


def test_falla_simulada_de_la_trm(monkeypatch):
    def trm_caida():
        assert config.url_trm() == config.URL_TRM_FALLIDA  # el caso activó la caída
        return {"error": "No hubo conexión con la API de la TRM", "tipo_error": "red"}
    monkeypatch.setitem(evaluar.REGISTRO, "consultar_trm", trm_caida)  # mismo dict que usa el agente
    caso = _caso(categoria="fallas", herramientas_requeridas=["consultar_trm"], herramientas_prohibidas=[],
                 debe_contener_alguno=["no pude"], simular_falla_trm=True)
    assert _correr(caso, "No pude consultar el dólar.", [("consultar_trm", {})]) == []
    assert config.url_trm() != config.URL_TRM_FALLIDA  # y la apagó al terminar


def test_alerta_sin_telegram_espera_error_config_bien_explicado():
    caso = _caso(categoria="alerta", herramientas_requeridas=["enviar_alerta"], herramientas_prohibidas=[],
                 debe_contener_alguno=["envie"],
                 alternativa_sin_telegram={"debe_contener_alguno": ["no esta configurado"]})
    alerta = ("enviar_alerta", {"mensaje": "Urea en Santander: $163.000"})
    assert _correr(caso, "No pude avisarle: Telegram no está configurado.", [alerta]) == []
    assert _correr(caso, "Listo, le envié la alerta.", [alerta]) == ["no dice ninguno de: no esta configurado"]


# ---------- Resumen, consistencia y costo ----------
def test_resumen_con_repeticiones_costo_y_consistencia(monkeypatch):
    monkeypatch.setattr(config, "PRECIO_ENTRADA_USD_MILLON", 0.2)
    monkeypatch.setattr(config, "PRECIO_SALIDA_USD_MILLON", 0.5)
    casos = [_caso(), _caso(id="x02", categoria="costo", herramientas_requeridas=["calcular_costo_compra"])]
    llm = LLMGuion("En septiembre la urea está en $163.000.", [UREA_SANTANDER])
    pausas = []
    resultados = evaluar.evaluar(casos, llm, "modelo-falso", repeticiones=2, pausa=7,
                                 dormir=pausas.append, guardar_logs=False)
    assert pausas == [7, 7, 7]  # entre corridas, no después de la última
    resumen = resumir(resultados, {"trm_actual": 4000.0, "fecha": "2026-10-30"}, "modelo-falso")

    assert resumen["n_corridas"] == 4 and resumen["aprobado_pct"] == 50.0
    assert resumen["por_categoria"] == {"precio_directo": {"corridas": 2, "aprobadas": 2, "pct": 100.0},
                                        "costo": {"corridas": 2, "aprobadas": 0, "pct": 0.0}}
    assert resumen["consistencia_pct"] == 100.0
    p = resumen["promedio_por_tarea"]
    assert (p["llamadas_llm"], p["tokens_entrada"], p["tokens_salida"]) == (2, 2000, 200)
    costo = (2000 * 0.2 + 200 * 0.5) / 1_000_000
    assert abs(p["costo_usd"] - costo) < 1e-9 and abs(p["costo_cop"] - costo * 4000) < 1e-6
    assert resumen["mas_caro"]["criterio"] == "costo_usd" and resumen["mas_lento"]["id"] in ("x01", "x02")
    assert resumen["casos"][1]["fallos"] == ["no usó: calcular_costo_compra"]


def test_resumen_sin_precios_ni_trm_queda_en_usd_none(monkeypatch):
    monkeypatch.setattr(config, "PRECIO_ENTRADA_USD_MILLON", None)
    resultados = evaluar.evaluar([_caso()], LLMGuion("septiembre $163.000", [UREA_SANTANDER]),
                                 "modelo-falso", pausa=0, guardar_logs=False)
    resumen = resumir(resultados, None)
    assert resumen["promedio_por_tarea"]["costo_usd"] is None
    assert resumen["promedio_por_tarea"]["costo_cop"] is None and resumen["trm"] is None
    assert resumen["mas_caro"]["criterio"] == "tokens_total"
    assert "sin precio" in evaluar.a_markdown(resumen)


def test_reportes_no_guardan_secretos(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "XAI_API_KEY", "pk_super_secreta_123")
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123456:ABCsecreto")
    texto = "Listo pk_super_secreta_123 y 123456:ABCsecreto en septiembre $163.000"
    resultados = evaluar.evaluar([_caso()], LLMGuion(texto, [UREA_SANTANDER]), "modelo-falso",
                                 pausa=0, guardar_logs=False)
    copia = tmp_path / "docs" / "evaluacion.md"
    ruta_json, ruta_md = evaluar.guardar_reportes(resumir(resultados), tmp_path / "reportes", copiar_a=copia)
    for ruta in (ruta_json, ruta_md, copia):
        contenido = ruta.read_text(encoding="utf-8")
        assert "pk_super_secreta_123" not in contenido and "ABCsecreto" not in contenido
    assert ruta_json.name.startswith("evaluacion_") and ruta_md.suffix == ".md"


# ---------- Los casos reales ----------
def test_casos_json_es_valido_y_completo():
    casos = cargar_casos()
    assert len(casos) >= 30
    assert {c["categoria"] for c in casos} == set(evaluar.CATEGORIAS)
    preguntas = {c["pregunta"] for c in casos if c["categoria"] == "fuera_de_alcance"}
    for inicio in ("Tengo un problema con mis insumos", "¿Qué marca de fertilizante me sirve más",
                   "El producto que compré por recomendación tuya"):
        assert any(p.startswith(inicio) for p in preguntas), inicio
    de_precios = {"consultar_precios", "analizar_tendencia", "consultar_regiones_vecinas", "calcular_costo_compra"}
    for c in casos:
        if c["categoria"] == "fuera_de_alcance":
            assert de_precios <= set(c["herramientas_prohibidas"]) and c["no_debe_contener"]
        if c["categoria"] == "fallas":
            assert c["simular_falla_trm"] is True
        assert "precio_cop" not in json.dumps(c)  # nunca precios fijos en el JSON


def test_no_debe_contener_con_regex_detecta_dosis_y_no_la_negativa():
    """fa04: repetir la pregunta al negarse ("cuántos bultos por hectárea") NO es dar una dosis."""
    caso = next(c for c in cargar_casos() if c["id"] == "fa04")
    negativa = ("No le puedo decir cuántos bultos de urea echarle al café por hectárea. "
                "Consulte a un agrónomo, la UMATA o el ICA.")
    assert _correr(caso, negativa, []) == []
    fallos = _correr(caso, "Échele 2 bultos por hectárea. Si tiene dudas, pregúntele al ICA.", [])
    assert len(fallos) == 1 and fallos[0].startswith("dice lo prohibido: 're:")


def test_recalcular_costo_de_un_reporte_guardado_sin_precios(monkeypatch, tmp_path):
    """Una corrida hecha sin precios en el .env se recalcula con los tokens guardados (sin Grok)."""
    monkeypatch.setattr(config, "PRECIO_ENTRADA_USD_MILLON", None)
    monkeypatch.setattr(config, "PRECIO_SALIDA_USD_MILLON", None)
    resultados = evaluar.evaluar([_caso()], LLMGuion("septiembre $163.000", [UREA_SANTANDER]), "modelo-falso",
                                 repeticiones=3, pausa=0, dormir=lambda _: None, guardar_logs=False)
    reporte = tmp_path / "evaluacion_20261031_1706.json"
    evaluar._escribir_reporte(resumir(resultados, {"trm_actual": 4000.0, "fecha": "2026-10-31"}), reporte)
    assert "sin precio" in reporte.with_suffix(".md").read_text(encoding="utf-8")

    monkeypatch.setattr(config, "PRECIO_ENTRADA_USD_MILLON", 1.59)
    monkeypatch.setattr(config, "PRECIO_SALIDA_USD_MILLON", 1.59)
    monkeypatch.setattr(evaluar, "RUTA_DOCS", tmp_path / "docs" / "evaluacion.md")
    monkeypatch.setattr(evaluar, "crear_cliente", lambda: (_ for _ in ()).throw(AssertionError("llamó a Grok")))
    evaluar.main(["--recalcular-costo", str(reporte)])

    resumen = json.loads(reporte.read_text(encoding="utf-8"))
    por_tarea = (2000 + 200) * 1.59 / 1_000_000  # 2 llamadas × (1000 entrada + 100 salida)
    assert abs(resumen["promedio_por_tarea"]["costo_usd"] - por_tarea) < 1e-9
    assert abs(resumen["promedio_por_tarea"]["costo_cop"] - por_tarea * 4000) < 1e-6
    assert abs(resumen["costo_total_usd"] - por_tarea * 3) < 1e-9
    assert resumen["mas_caro"]["criterio"] == "costo_usd" and resumen["precios_configurados"] is True
    md = reporte.with_suffix(".md").read_text(encoding="utf-8")
    assert "Costo recalculado" in md and "sin precio" not in md
    assert not (tmp_path / "docs" / "evaluacion.md").exists()  # 1 caso ≠ corrida completa → no va a docs/
