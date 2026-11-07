"""
llm.py — Conexión con el "cerebro" (Grok) 🧠
=============================================
Grok se usa a través de la pasarela de la plataforma del reto, que es compatible con
OpenAI, así que usamos el SDK `openai` apuntando a esa URL (XAI_BASE_URL).
Si algún día cambias de proveedor, solo tocas aquí.
"""
from openai import OpenAI

from agente import config


def crear_cliente(max_retries: int = 2) -> OpenAI:
    """max_retries: reintentos automáticos del SDK (2 es su valor por defecto). La semana de
    carga usa 0 para hacer ella misma los reintentos y dejarlos todos en la bitácora."""
    config.validar_config()
    # timeout: que una caída de la API no deje la consola colgada (el SDK trae 10 min)
    return OpenAI(api_key=config.XAI_API_KEY, base_url=config.XAI_BASE_URL, timeout=60,
                  max_retries=max_retries)
