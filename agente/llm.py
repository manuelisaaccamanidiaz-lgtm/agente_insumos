"""
llm.py — Conexión con el "cerebro" (Grok) 🧠
=============================================
Grok expone una API compatible con OpenAI, así que usamos el SDK `openai`
apuntando a la URL de xAI. Si algún día cambias de proveedor, solo tocas aquí.
"""
from openai import OpenAI

from agente import config


def crear_cliente() -> OpenAI:
    config.validar_config()
    return OpenAI(api_key=config.XAI_API_KEY, base_url=config.XAI_BASE_URL)
