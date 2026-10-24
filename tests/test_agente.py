"""
Pruebas del loop SIN gastar API: usamos un LLM "falso" que responde un guion fijo.
Así comprobamos que el flujo pregunta → herramienta → respuesta funciona.
Ejecutar:  pytest -v
"""
import json
from types import SimpleNamespace as NS

import openai

from agente.agente import ejecutar_agente
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
    assert len(r["historial"]) == 4
    assert r["historial"][-1]["precio_cop"] == 171000


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
    assert salida["respuesta"] == "La urea está en 171000 COP"
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
