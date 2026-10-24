"""
Pruebas de las 4 herramientas SIN internet 🔌
- La BD es una SQLite temporal (fixture `bd_temporal` en conftest.py).
- Las APIs (TRM y Telegram) se reemplazan con unittest.mock: nunca sale una petición real.
"""
from contextlib import closing
from unittest.mock import MagicMock, patch

import requests

from agente import config, herramientas
from agente.datos import conectar, insertar_precios
from agente.herramientas import analizar_tendencia, consultar_precios, consultar_trm, enviar_alerta
from scripts.cargar_bd import cargar


def _respuesta(json_data=None, status=200, json_error=None):
    """Respuesta falsa de `requests`."""
    resp = MagicMock(status_code=status)
    resp.json.side_effect = json_error
    resp.json.return_value = json_data
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


# ---------- Base de datos ----------
def test_cargar_bd_es_idempotente(tmp_path):
    ruta = tmp_path / "otra.db"
    assert cargar(config.RUTA_PRECIOS, ruta) == (28, 28)
    assert cargar(config.RUTA_PRECIOS, ruta) == (28, 0)  # segunda vez no duplica


def test_bd_inexistente_da_error_config(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RUTA_BD", tmp_path / "no_existe.db")
    r = consultar_precios("urea", "Santander")
    assert r["tipo_error"] == "config"
    assert "python scripts/cargar_bd.py" in r["error"]


# ---------- consultar_precios ----------
def test_consultar_precios_ignora_tildes_y_marca_ejemplo():
    r = consultar_precios("URÉA", " boyacá ")
    assert r["region"] == "Boyaca" and r["es_ejemplo"] is True
    assert [f["precio_cop"] for f in r["historial"]] == [185000, 184000, 180500, 177000]


def test_consultar_precios_sin_datos_sugiere_regiones():
    r = consultar_precios("urea", "Nariño")
    assert r["tipo_error"] == "sin_datos"
    assert "Santander" in r["error"] and "Meta" in r["error"]


def test_consultar_precios_insumo_inexistente_sugiere_insumos():
    r = consultar_precios("glifosato", "Nariño")
    assert r["tipo_error"] == "sin_datos"
    assert "urea" in r["error"] and "dap" in r["error"]


# ---------- analizar_tendencia ----------
def test_tendencia_bajando_recomienda_esperar():
    r = analizar_tendencia("urea", "Santander")
    assert r["recomendacion"] == "esperar"
    assert r["pendiente_cop_semana"] == -3650  # calculado a mano: Sxy=-18250, Sxx=5
    assert r["variacion_total_pct"] == -6.04
    assert r["variacion_ultima_semana_pct"] == -2.84
    assert r["promedio_cop"] == 177125
    assert "bajando" in r["porque"]


def test_tendencia_subiendo_recomienda_comprar_ya():
    assert analizar_tendencia("dap", "Santander")["recomendacion"] == "comprar_ya"


def test_tendencia_estable_es_neutral():
    assert analizar_tendencia("kcl", "Santander")["recomendacion"] == "neutral"


def test_tendencia_con_un_solo_dato_da_error(bd_temporal):
    with closing(conectar(bd_temporal)) as c:
        insertar_precios(c, [{"fecha": "2026-10-05", "region": "Cauca", "insumo": "urea",
                              "precio_cop": 175000, "unidad": "bulto 50 kg", "fuente": "ejemplo"}])
    r = analizar_tendencia("urea", "Cauca")
    assert r["tipo_error"] == "sin_datos" and "al menos 2" in r["error"]


def test_tendencia_sin_datos():
    assert analizar_tendencia("glifosato", "Nariño")["tipo_error"] == "sin_datos"


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
