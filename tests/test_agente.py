"""
Pruebas del loop SIN gastar API: usamos un LLM "falso" que responde un guion fijo.
Así comprobamos que el flujo pregunta → herramienta → respuesta funciona.
Ejecutar:  pytest -v
"""
import json
from types import SimpleNamespace as NS

from agente.agente import ejecutar_agente
from agente.herramientas import consultar_precios, ejecutar


class LLMFalso:
    """Primera llamada: pide la herramienta. Segunda: responde con texto."""
    def __init__(self):
        self.llamadas = 0
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, model, messages, tools):
        self.llamadas += 1
        if self.llamadas == 1:
            tc = NS(id="call_1", function=NS(name="consultar_precios",
                                             arguments='{"insumo": "urea", "region": "Santander"}'))
            msg = NS(content=None, tool_calls=[tc])
        else:
            dato = json.loads(messages[-1]["content"])  # lo que devolvió la herramienta
            ultimo = dato["historial"][-1]["precio_cop"]
            msg = NS(content=f"La urea está en {ultimo} COP", tool_calls=None)
        return NS(choices=[NS(message=msg)])


def test_herramienta_devuelve_historial():
    r = consultar_precios("Urea", "santander")  # mayúsculas/minúsculas no importan
    assert len(r["historial"]) == 4
    assert r["historial"][-1]["precio_cop"] == 171000


def test_herramienta_sin_datos():
    assert "error" in consultar_precios("glifosato", "Narino")


def test_ejecutar_herramienta_inexistente_no_rompe():
    assert "error" in json.loads(ejecutar("volar", "{}"))


def test_loop_end_to_end():
    llm = LLMFalso()
    salida = ejecutar_agente("¿Precio de la urea en Santander?", llm, "modelo-falso")
    assert salida["respuesta"] == "La urea está en 171000 COP"
    assert salida["rastro"][0]["nombre"] == "consultar_precios"
    assert llm.llamadas == 2
