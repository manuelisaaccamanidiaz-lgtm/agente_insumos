"""
Pruebas del loop SIN gastar API: usamos un LLM "falso" que responde un guion fijo.
Así comprobamos que el flujo pregunta → herramienta → respuesta funciona.
Ejecutar:  pytest -v
"""
import json
from types import SimpleNamespace as NS

import openai
import pytest

from agente import config
from agente.agente import calcular_costo_usd, ejecutar_agente, formatear_uso, guardar_log
from agente.herramientas import consultar_precios, ejecutar


class LLMFalso:
    """Primera llamada: pide la herramienta. Segunda: responde con texto."""
    def __init__(self, herramienta="consultar_precios",
                 argumentos='{"insumo": "urea", "region": "Santander"}'):
        self.llamadas = 0
        self.herramienta, self.argumentos = herramienta, argumentos
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, model, messages, tools):
        self.llamadas += 1
        if self.llamadas == 1:
            tc = NS(id="call_1", function=NS(name=self.herramienta, arguments=self.argumentos))
            msg = NS(content=None, tool_calls=[tc])
        else:
            dato = json.loads(messages[-1]["content"])  # lo que devolvió la herramienta
            if "error" in dato:
                msg = NS(content=f"No pude: {dato['error']}", tool_calls=None)
            else:
                ultimo = dato["historial"][-1]["precio_cop"]
                msg = NS(content=f"La urea está en {ultimo} COP", tool_calls=None)
        return NS(choices=[NS(message=msg)])


class LLMQueFalla:
    """Simula que la API de Grok devuelve un error."""
    def __init__(self, error):
        self.chat = NS(completions=NS(create=lambda **_: (_ for _ in ()).throw(error)))


def _error_openai(clase):
    """Crea la excepción del SDK sin su __init__ (que pide objetos HTTP internos que
    cambian entre versiones). El agente solo distingue los errores por su tipo."""
    return clase.__new__(clase)


def test_herramienta_devuelve_historial():
    r = consultar_precios("Urea", "santander")  # mayúsculas/minúsculas no importan
    assert len(r["historial"]) == 7  # meses con datos dentro de los últimos 12
    assert r["historial"][-1]["precio_cop"] == 163000


def test_herramienta_sin_datos():
    assert "error" in consultar_precios("glifosato", "Narino")


def test_ejecutar_herramienta_inexistente_no_rompe():
    r = json.loads(ejecutar("volar", "{}"))
    assert r["tipo_error"] == "validacion"


def test_ejecutar_argumentos_invalidos_no_rompe():
    assert json.loads(ejecutar("consultar_precios", "esto no es json"))["tipo_error"] == "validacion"
    assert json.loads(ejecutar("consultar_precios", '{"insumo": "urea"}'))["tipo_error"] == "validacion"


def test_loop_end_to_end():
    llm = LLMFalso()
    salida = ejecutar_agente("¿Precio de la urea en Santander?", llm, "modelo-falso")
    assert salida["respuesta"] == "La urea está en 163000 COP"
    assert salida["rastro"][0]["nombre"] == "consultar_precios"
    assert llm.llamadas == 2


def test_rastro_registra_exito_y_duracion():
    paso = ejecutar_agente("urea Santander", LLMFalso(), "modelo-falso")["rastro"][0]
    assert paso["exito"] is True
    assert isinstance(paso["duracion_ms"], int) and paso["duracion_ms"] >= 0
    assert json.loads(paso["argumentos"]) == {"insumo": "urea", "region": "Santander"}


def test_rastro_registra_error_y_el_loop_sigue():
    llm = LLMFalso(argumentos='{"insumo": "glifosato", "region": "Nariño"}')
    salida = ejecutar_agente("glifosato Nariño", llm, "modelo-falso")
    paso = salida["rastro"][0]
    assert paso["exito"] is False and paso["tipo_error"] == "sin_datos"
    assert salida["respuesta"].startswith("No pude")  # el LLM recibió el error y respondió


def test_error_401_de_grok_da_mensaje_claro():
    salida = ejecutar_agente("hola", LLMQueFalla(_error_openai(openai.AuthenticationError)), "modelo-falso")
    assert "XAI_API_KEY" in salida["respuesta"]
    assert salida["rastro"][-1]["tipo"] == "error_llm"


def test_api_key_incorrecta_con_400_de_xai_da_mensaje_claro():
    error = _error_openai(openai.BadRequestError)
    error.status_code, error.message = 400, "Incorrect API key provided."
    assert "XAI_API_KEY" in ejecutar_agente("hola", LLMQueFalla(error), "modelo-falso")["respuesta"]


def test_error_429_de_grok_da_mensaje_claro():
    error = _error_openai(openai.RateLimitError)
    assert "429" in ejecutar_agente("hola", LLMQueFalla(error), "modelo-falso")["respuesta"]


def test_error_de_red_de_grok_da_mensaje_claro():
    error = _error_openai(openai.APIConnectionError)
    assert "conexión" in ejecutar_agente("hola", LLMQueFalla(error), "modelo-falso")["respuesta"]


# ---------- Tokens y costo por tarea ----------
class LLMConUso(LLMFalso):
    """Igual que LLMFalso, pero cada respuesta trae `usage` (o no, si usage=None)."""
    def __init__(self, usage=NS(prompt_tokens=1000, completion_tokens=50), **kwargs):
        super().__init__(**kwargs)
        self.usage = usage

    def _create(self, model, messages, tools):
        resp = super()._create(model, messages, tools)
        return resp if self.usage is None else NS(choices=resp.choices, usage=self.usage)


def test_uso_acumula_tokens_de_todas_las_llamadas(monkeypatch):
    monkeypatch.setattr(config, "PRECIO_ENTRADA_USD_MILLON", None)
    monkeypatch.setattr(config, "PRECIO_SALIDA_USD_MILLON", None)
    uso = ejecutar_agente("urea Santander", LLMConUso(), "modelo-falso")["uso"]
    assert uso["llamadas_llm"] == 2
    assert (uso["tokens_entrada"], uso["tokens_salida"], uso["tokens_total"]) == (2000, 100, 2100)
    assert isinstance(uso["duracion_ms"], int) and uso["duracion_ms"] >= 0
    assert uso["costo_usd"] is None  # sin precios en el .env no se inventa el costo


def test_uso_calcula_costo_con_precios_del_env(monkeypatch):
    monkeypatch.setattr(config, "PRECIO_ENTRADA_USD_MILLON", 0.2)
    monkeypatch.setattr(config, "PRECIO_SALIDA_USD_MILLON", 0.5)
    uso = ejecutar_agente("urea Santander", LLMConUso(), "modelo-falso")["uso"]
    assert uso["costo_usd"] == pytest.approx((2000 * 0.2 + 100 * 0.5) / 1_000_000)


def test_sin_usage_los_tokens_quedan_en_none_y_no_rompe(monkeypatch):
    monkeypatch.setattr(config, "PRECIO_ENTRADA_USD_MILLON", 0.2)
    monkeypatch.setattr(config, "PRECIO_SALIDA_USD_MILLON", 0.5)
    salida = ejecutar_agente("urea Santander", LLMConUso(usage=None), "modelo-falso")
    assert salida["respuesta"] == "La urea está en 163000 COP"
    uso = salida["uso"]
    assert uso["llamadas_llm"] == 2
    assert uso["tokens_entrada"] is uso["tokens_salida"] is uso["tokens_total"] is uso["costo_usd"] is None


def test_error_de_grok_tambien_devuelve_uso():
    uso = ejecutar_agente("hola", LLMQueFalla(_error_openai(openai.RateLimitError)), "modelo-falso")["uso"]
    assert uso["llamadas_llm"] == 1 and uso["tokens_total"] == 0


def test_calcular_costo_usd_falta_un_precio(monkeypatch):
    assert calcular_costo_usd(1_000_000, 1_000_000, 0.2, 0.5) == pytest.approx(0.7)
    monkeypatch.setattr(config, "PRECIO_ENTRADA_USD_MILLON", None)  # PRECIO_ENTRADA vacío en el .env
    monkeypatch.setattr(config, "PRECIO_SALIDA_USD_MILLON", 0.5)
    assert calcular_costo_usd(1000, 100) is None
    assert calcular_costo_usd(None, 100, 0.2, 0.5) is None


def test_precio_del_env_vacio_o_invalido_es_none(monkeypatch):
    for valor, esperado in (("", None), ("abc", None), ("0.20", 0.2), ("0,5", 0.5)):
        monkeypatch.setenv("PRECIO_PRUEBA", valor)
        assert config._precio_millon("PRECIO_PRUEBA") == esperado


def test_formatear_uso_linea_discreta():
    uso = {"llamadas_llm": 3, "tokens_total": 4210, "duracion_ms": 6140, "costo_usd": 0.0021}
    assert formatear_uso(uso) == "🧾 3 llamadas · 4.210 tokens · 6,1 s · $0,0021 USD"
    uso.update(llamadas_llm=1, tokens_total=None, costo_usd=None)
    assert formatear_uso(uso) == "🧾 1 llamada · tokens n/d · 6,1 s · costo sin precio"


def test_log_incluye_uso(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CARPETA_LOGS", tmp_path)
    salida = ejecutar_agente("urea Santander", LLMConUso(), "modelo-falso")
    ruta = guardar_log("urea Santander", salida)
    assert json.loads(open(ruta, encoding="utf-8").read())["uso"]["tokens_total"] == 2100
