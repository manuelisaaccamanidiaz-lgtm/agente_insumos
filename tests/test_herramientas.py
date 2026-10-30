"""
Pruebas de las herramientas SIN internet 🔌
- La BD es una SQLite temporal cargada con el ETL desde un Excel falso (conftest.py).
  Precios FICTICIOS de data/precios_ejemplo.csv; último mes publicado: septiembre 2026.
- Las APIs (TRM y Telegram) se reemplazan con unittest.mock: nunca sale una petición real.
"""
from unittest.mock import MagicMock, patch

import requests

from agente import config, herramientas
from agente.herramientas import (analizar_tendencia, calcular_costo_compra, consultar_precios,
                                 consultar_regiones_vecinas, consultar_trm, enviar_alerta)


def _respuesta(json_data=None, status=200, json_error=None):
    """Respuesta falsa de `requests`."""
    resp = MagicMock(status_code=status)
    resp.json.side_effect = json_error
    resp.json.return_value = json_data
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


# ---------- Base de datos ----------
def test_bd_inexistente_da_error_config(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RUTA_BD", tmp_path / "no_existe.db")
    for r in (consultar_precios("urea", "Santander"), consultar_regiones_vecinas("urea", "Boyacá"),
              calcular_costo_compra("urea", "Santander", 1)):
        assert r["tipo_error"] == "config"
        assert "python scripts/actualizar_sipsa.py" in r["error"]


# ---------- consultar_precios ----------
def test_consultar_precios_departamento_con_rango():
    r = consultar_precios("URÉA", " santandér ")
    assert r["insumo"] == "Urea 46%" and r["region"] == "Santander"
    assert (r["precio_actual_cop"], r["precio_min_cop"], r["precio_max_cop"], r["n_municipios"]) == (163000, 160000, 166000, 2)
    assert r["ultimo_periodo"] == "2026-09" and r["ultimo_mes"] == "septiembre 2026"
    assert r["fuente"] == "DANE-SIPSA (mes publicado: septiembre 2026)"
    assert r["es_ejemplo"] is False and r["dato_desactualizado"] is False


def test_consultar_precios_solo_ultimos_12_meses():
    historial = consultar_precios("urea", "Santander")["historial"]
    assert historial[0]["periodo"] >= "2025-10" and historial[-1]["periodo"] == "2026-09"  # 2025-09 ya no entra
    assert set(historial[0]) == {"periodo", "precio_cop", "precio_min", "precio_max", "n_municipios"}


def test_consultar_precios_por_municipio():
    r = consultar_precios("dap", "Santander", municipio="BUCARAMANGA")
    assert r["municipio"] == "Bucaramanga" and r["precio_actual_cop"] == 225000 and r["n_municipios"] == 1


def test_consultar_precios_municipio_en_el_campo_region():
    r = consultar_precios("dap", "Bucaramanga")  # el LLM puso el municipio como región
    assert r["region"] == "Santander" and r["municipio"] == "Bucaramanga"


def test_consultar_precios_dato_viejo_se_marca_desactualizado():
    r = consultar_precios("urea", "Boyacá")
    assert r["ultimo_periodo"] == "2026-02" and r["meses_de_atraso"] == 7
    assert r["dato_desactualizado"] is True


def test_municipio_desactualizado_trae_referencia_del_departamento():
    r = consultar_precios("urea", "Santander", "Barbosa")
    assert r["dato_desactualizado"] is True
    ref = r["referencia_departamento"]
    assert ref["periodo"] == "2026-09" and ref["precio_cop"] == 163000 and ref["dato_desactualizado"] is False


def test_consultar_precios_sin_datos_sugiere_departamentos():
    r = consultar_precios("urea", "Nariño")
    assert r["tipo_error"] == "sin_datos" and "septiembre 2026" in r["error"]
    assert "Santander" in r["error"] and "Cundinamarca" in r["error"]


def test_consultar_precios_municipio_sin_datos_sugiere_municipios():
    r = consultar_precios("urea", "Santander", "San Gil")
    assert r["tipo_error"] == "sin_datos"
    assert "Bucaramanga" in r["error"] and "Piedecuesta" in r["error"]


def test_consultar_precios_insumo_inexistente_sugiere_insumos():
    r = consultar_precios("glifosato", "Nariño")
    assert r["tipo_error"] == "sin_datos"
    assert "urea" in r["error"] and "dap" in r["error"]


def test_consultar_precios_region_inexistente():
    assert consultar_precios("urea", "Narnia")["tipo_error"] == "validacion"


# ---------- analizar_tendencia (mensual) ----------
def test_tendencia_bajando_recomienda_esperar():
    r = analizar_tendencia("urea", "Santander")
    assert r["recomendacion"] == "esperar"
    assert (r["desde"], r["hasta"], r["n_meses"]) == ("2026-04", "2026-09", 6)
    assert (r["precio_actual_cop"], r["precio_min_cop"], r["precio_max_cop"]) == (163000, 160000, 166000)
    # promedios mensuales: 182, 178, 174, 170, 166, 163 mil → Sxy = -67.500, Sxx = 17,5
    assert r["pendiente_cop_mes"] == -3857
    assert r["pendiente_pct_mes"] == -2.24
    assert r["promedio_6_meses_cop"] == 172167
    assert r["variacion_6_meses_pct"] == -10.44
    assert r["variacion_vs_mes_anterior_pct"] == -1.81
    assert "bajando" in r["porque"] and "por mes" in r["porque"]


def test_tendencia_compara_con_el_mismo_mes_del_anio_anterior():
    r = analizar_tendencia("urea", "Santander")
    assert r["precio_mismo_mes_anio_anterior_cop"] == 152000  # sep-2025: (150 + 154) / 2 mil
    assert r["variacion_anual_pct"] == 7.24
    assert "septiembre 2025" in r["porque"]


def test_tendencia_sin_mismo_mes_del_anio_anterior():
    r = analizar_tendencia("dap", "Santander")
    assert r["precio_mismo_mes_anio_anterior_cop"] is None and r["variacion_anual_pct"] is None


def test_tendencia_subiendo_recomienda_comprar_ya():
    r = analizar_tendencia("dap", "Santander")
    assert r["recomendacion"] == "comprar_ya" and r["pendiente_pct_mes"] == 2.35


def test_tendencia_estable_es_neutral():
    assert analizar_tendencia("kcl", "Santander")["recomendacion"] == "neutral"


def test_tendencia_umbral_configurable(monkeypatch):
    monkeypatch.setattr(config, "UMBRAL_PCT_MENSUAL", 3.0)
    assert analizar_tendencia("urea", "Santander")["recomendacion"] == "neutral"


def test_tendencia_con_un_solo_mes_da_error():
    r = analizar_tendencia("urea", "Meta")
    assert r["tipo_error"] == "sin_datos" and "al menos 2" in r["error"]


def test_tendencia_sin_datos():
    assert analizar_tendencia("glifosato", "Nariño")["tipo_error"] == "sin_datos"


# ---------- consultar_regiones_vecinas ----------
def test_vecinos_ordenados_del_mas_barato_al_mas_caro():
    r = consultar_regiones_vecinas("urea", "boyaca")
    assert r["region"] == "Boyacá"
    regiones = [v["region"] for v in r["vecinos"]]
    # Meta (150.000) es más barato pero NO es vecino de Boyacá
    assert regiones == ["Cundinamarca", "Santander", "Norte de Santander", "Casanare"]
    assert [v["precio_cop"] for v in r["vecinos"][:3]] == [158000, 163000, 170000]
    assert r["vecinos"][0]["precio_min"] == 157000 and r["vecinos"][0]["precio_max"] == 159000


def test_vecinos_con_dato_viejo_van_al_final():
    r = consultar_regiones_vecinas("urea", "Boyacá")
    casanare = r["vecinos"][-1]  # 130.000 es el más barato, pero de marzo 2025
    assert casanare["region"] == "Casanare" and casanare["dato_desactualizado"] is True
    assert r["mas_barato_vigente"]["region"] == "Cundinamarca"


def test_vecinos_incluye_el_precio_de_la_region_y_los_que_no_tienen_datos():
    r = consultar_regiones_vecinas("urea", "Boyacá")
    assert r["precio_en_la_region"]["periodo"] == "2026-02"
    assert set(r["vecinos_sin_datos"]) == {"Antioquia", "Arauca", "Caldas"}
    assert r["es_ejemplo"] is False and "septiembre 2026" in r["fuente"]


def test_vecinos_sin_datos():
    r = consultar_regiones_vecinas("dap", "Nariño")  # vecinos: Cauca y Putumayo, sin DAP
    assert r["tipo_error"] == "sin_datos"
    assert "Cauca" in r["error"] and "Santander" in r["error"]  # dice dónde sí hay


def test_vecinos_region_o_insumo_invalidos():
    assert consultar_regiones_vecinas("urea", "Narnia")["tipo_error"] == "validacion"
    assert consultar_regiones_vecinas("glifosato", "Boyacá")["tipo_error"] == "sin_datos"
    assert consultar_regiones_vecinas("urea", "San Andrés")["tipo_error"] == "sin_datos"


def test_vecinos_esta_registrada_para_el_llm():
    nombres = [e["function"]["name"] for e in herramientas.ESQUEMAS]
    assert "consultar_regiones_vecinas" in nombres
    assert "consultar_regiones_vecinas" in herramientas.REGISTRO


# ---------- calcular_costo_compra ----------
def test_costo_usa_el_ultimo_precio_real():
    r = calcular_costo_compra("DAP", "Bucaramanga", 10)
    assert r["municipio"] == "Bucaramanga" and r["periodo_precio"] == "2026-09"
    assert r["precio_unitario_cop"] == 225000 and r["total_cop"] == 2250000
    assert r["es_ejemplo"] is False


def test_costo_departamento_con_rango():
    r = calcular_costo_compra("urea", "Santander", 2)
    assert (r["total_cop"], r["total_min_cop"], r["total_max_cop"]) == (326000, 320000, 332000)


def test_costo_municipio_desactualizado_trae_total_del_departamento():
    r = calcular_costo_compra("urea", "Santander", 10, municipio="Barbosa")
    assert r["total_cop"] == 1500000 and r["dato_desactualizado"] is True
    assert r["referencia_departamento"]["total_cop"] == 1630000


def test_costo_bultos_invalidos():
    for malo in (0, -3, 2.5, "10", True):
        assert calcular_costo_compra("urea", "Santander", malo)["tipo_error"] == "validacion"


# ---------- consultar_trm ----------
TRM_OK = [
    {"valor": "4100.00", "unidad": "COP", "vigenciadesde": "2026-10-24T00:00:00.000"},
    {"valor": "4050.00", "unidad": "COP", "vigenciadesde": "2026-10-23T00:00:00.000"},
    {"valor": "4000.00", "unidad": "COP", "vigenciadesde": "2026-10-22T00:00:00.000"},
]


def test_trm_exito():
    with patch.object(herramientas.requests, "get", return_value=_respuesta(TRM_OK)) as get:
        r = consultar_trm()
    assert r["trm_actual"] == 4100.0 and r["fecha"] == "2026-10-24"
    assert r["variacion_semana_pct"] == 2.5 and r["tendencia_dolar"] == "subiendo"
    assert "datos.gov.co" in r["fuente"]
    assert get.call_args.kwargs["timeout"] == config.TIMEOUT_HTTP


def test_trm_timeout_reintenta_una_vez_y_da_error_red():
    with patch.object(herramientas.requests, "get", side_effect=requests.Timeout()) as get:
        r = consultar_trm()
    assert r["tipo_error"] == "red" and "no respondió" in r["error"]
    assert get.call_count == 2  # intento + 1 reintento


def test_trm_reintento_recupera_la_respuesta():
    efectos = [requests.ConnectionError(), _respuesta(TRM_OK)]
    with patch.object(herramientas.requests, "get", side_effect=efectos):
        assert consultar_trm()["trm_actual"] == 4100.0


def test_trm_error_http():
    with patch.object(herramientas.requests, "get", return_value=_respuesta(status=503)):
        r = consultar_trm()
    assert r["tipo_error"] == "red" and "503" in r["error"]


def test_trm_json_inesperado():
    for malo in [{"mensaje": "hola"}, [{"otro_campo": 1}], None]:
        with patch.object(herramientas.requests, "get", return_value=_respuesta(malo)):
            assert consultar_trm()["tipo_error"] == "red"
    with patch.object(herramientas.requests, "get",
                      return_value=_respuesta(json_error=ValueError("no es JSON"))):
        assert consultar_trm()["tipo_error"] == "red"


def test_trm_simular_falla_usa_url_invalida(monkeypatch):
    monkeypatch.setenv("SIMULAR_FALLA_TRM", "1")
    with patch.object(herramientas.requests, "get", side_effect=requests.ConnectionError()) as get:
        r = consultar_trm()
    assert r["tipo_error"] == "red"
    assert get.call_args.args[0] == config.URL_TRM_FALLIDA


# ---------- enviar_alerta ----------
def _configurar_telegram(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TOKEN_FALSO")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "999")


def test_alerta_exito(monkeypatch):
    _configurar_telegram(monkeypatch)
    ok = _respuesta({"ok": True, "result": {"message_id": 42}})
    with patch.object(herramientas.requests, "post", return_value=ok) as post:
        r = enviar_alerta("Urea en Santander: espere")
    assert r == {"enviado": True, "chat_id": "999", "message_id": 42}
    assert post.call_args.kwargs["json"] == {"chat_id": "999", "text": "Urea en Santander: espere"}


def test_alerta_sin_config_no_rompe():
    with patch.object(herramientas.requests, "post") as post:
        r = enviar_alerta("hola")
    assert r["tipo_error"] == "config" and "TELEGRAM_BOT_TOKEN" in r["error"]
    post.assert_not_called()


def test_alerta_mensaje_vacio_o_largo(monkeypatch):
    _configurar_telegram(monkeypatch)
    assert enviar_alerta("   ")["tipo_error"] == "validacion"
    assert enviar_alerta("x" * 1001)["tipo_error"] == "validacion"


def test_alerta_telegram_responde_ok_false(monkeypatch):
    _configurar_telegram(monkeypatch)
    rechazo = _respuesta({"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})
    with patch.object(herramientas.requests, "post", return_value=rechazo):
        r = enviar_alerta("hola")
    assert r["tipo_error"] == "config" and "chat not found" in r["error"]


def test_alerta_error_de_red_no_filtra_el_token(monkeypatch):
    _configurar_telegram(monkeypatch)
    error = requests.ConnectionError("https://api.telegram.org/bot123:TOKEN_FALSO/sendMessage")
    with patch.object(herramientas.requests, "post", side_effect=error):
        r = enviar_alerta("hola")
    assert r["tipo_error"] == "red"
    assert "TOKEN_FALSO" not in r["error"]
