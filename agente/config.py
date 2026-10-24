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

# CSV de precios de EJEMPLO: solo lo lee scripts/cargar_bd.py para llenar la BD
RUTA_PRECIOS = Path(os.getenv("RUTA_PRECIOS") or RAIZ / "data" / "precios_ejemplo.csv")

# Base de datos SQLite que consulta el agente (se crea con: python scripts/cargar_bd.py)
RUTA_BD = Path(os.getenv("RUTA_BD") or RAIZ / "data" / "insumos.db")

# API pública de la TRM (dólar oficial) en datos abiertos de Colombia
TRM_API_URL = os.getenv("TRM_API_URL") or "https://www.datos.gov.co/resource/32sa-8pi3.json"

# ⚠️ MANUAL: token del bot (@BotFather) y chat al que llegan las alertas. Ver README.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Segundos máximos de espera para cualquier API externa (TRM, Telegram)
TIMEOUT_HTTP = float(os.getenv("TIMEOUT_HTTP", "10"))

# Carpeta donde se guarda el rastro de cada ejecución (evidencia end-to-end)
CARPETA_LOGS = RAIZ / "logs"

# Freno de seguridad: máximo de vueltas del loop para que nunca sea infinito
MAX_ITERACIONES = int(os.getenv("MAX_ITERACIONES", "5"))

# URL que no existe (el dominio .invalid nunca resuelve): sirve para simular una caída
URL_TRM_FALLIDA = "https://trm-falla-simulada.invalid/resource.json"


def url_trm() -> str:
    """URL de la TRM a usar. Con SIMULAR_FALLA_TRM=1 devuelve una URL inválida (para el demo).
    Se lee en cada llamada (no al importar) para poder activarla en caliente."""
    if os.getenv("SIMULAR_FALLA_TRM") == "1":
        return URL_TRM_FALLIDA
    return TRM_API_URL


def validar_config() -> None:
    """Falla con un mensaje claro si falta algo en el .env."""
    faltantes = [n for n, v in {"XAI_API_KEY": XAI_API_KEY, "GROK_MODEL": GROK_MODEL}.items() if not v]
    if faltantes:
        raise SystemExit(
            f"❌ Faltan variables en .env: {', '.join(faltantes)}\n"
            "   Copia .env.example como .env y llénalas (ver README)."
        )
