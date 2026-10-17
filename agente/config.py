"""
config.py — Lee la configuración desde el archivo .env
======================================================
Aquí NO se escriben claves. Las claves viven en .env (que NO se sube a GitHub).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

# ⚠️ MANUAL: pega tu API key de Grok en el archivo .env (variable XAI_API_KEY).
#    Se crea en https://console.x.ai  →  API Keys.
XAI_API_KEY = os.getenv("XAI_API_KEY", "")

# ⚠️ MANUAL: verifica en la documentación de xAI la URL base y el nombre del
#    modelo vigente (cambian con el tiempo). La API de Grok es compatible con
#    el SDK de OpenAI, por eso usamos la librería `openai` con otra base_url.
XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
GROK_MODEL = os.getenv("GROK_MODEL", "")  # ej: el modelo que veas en console.x.ai

# Ruta del CSV de precios (en S1 son datos de EJEMPLO; en S3 pasan a ser reales)
RUTA_PRECIOS = Path(os.getenv("RUTA_PRECIOS", RAIZ / "data" / "precios_ejemplo.csv"))

# Carpeta donde se guarda el rastro de cada ejecución (evidencia end-to-end)
CARPETA_LOGS = RAIZ / "logs"

# Freno de seguridad: máximo de vueltas del loop para que nunca sea infinito
MAX_ITERACIONES = int(os.getenv("MAX_ITERACIONES", "5"))


def validar_config() -> None:
    """Falla con un mensaje claro si falta algo en el .env."""
    faltantes = [n for n, v in {"XAI_API_KEY": XAI_API_KEY, "GROK_MODEL": GROK_MODEL}.items() if not v]
    if faltantes:
        raise SystemExit(
            f"❌ Faltan variables en .env: {', '.join(faltantes)}\n"
            "   Copia .env.example como .env y llénalas (ver README)."
        )
