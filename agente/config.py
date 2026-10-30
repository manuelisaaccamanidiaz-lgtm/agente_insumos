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
#    Con la plataforma del reto se crea en tu panel (empieza por pk_) y va junto
#    con la XAI_BASE_URL que te da esa misma plataforma.
XAI_API_KEY = os.getenv("XAI_API_KEY", "")

# ⚠️ MANUAL: verifica en la documentación de xAI la URL base y el nombre del
#    modelo vigente (cambian con el tiempo). La API de Grok es compatible con
#    el SDK de OpenAI, por eso usamos la librería `openai` con otra base_url.
XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
GROK_MODEL = os.getenv("GROK_MODEL", "")  # ej: el modelo que veas en console.x.ai

# CSV de precios de EJEMPLO (ficticios): SOLO lo usan las pruebas para armar un Excel falso
RUTA_PRECIOS = Path(os.getenv("RUTA_PRECIOS") or RAIZ / "data" / "precios_ejemplo.csv")

# Base de datos SQLite que consulta el agente (se llena con: python scripts/actualizar_sipsa.py)
RUTA_BD = Path(os.getenv("RUTA_BD") or RAIZ / "data" / "insumos.db")

# ---------- S3 · Datos reales del DANE (SIPSA-Insumos) ----------
# Serie histórica MENSUAL de precios por municipio. ⚠️ El año final del nombre cambia cada
# año (…2021-2026.xlsx → …2021-2027.xlsx): si la descarga da 404, actualiza SIPSA_URL.
SIPSA_URL = os.getenv("SIPSA_URL") or (
    "https://www.dane.gov.co/files/operaciones/SIPSA/anex-SIPSAInsumos-SeriesHistoricasMun-2021-2026.xlsx"
)
# Copia local del Excel: data/<mismo nombre del archivo de la URL>
RUTA_SIPSA = Path(os.getenv("RUTA_SIPSA") or RAIZ / "data" / SIPSA_URL.rstrip("/").rsplit("/", 1)[-1])
# Si la copia local tiene más de estos días, el script la vuelve a descargar
DIAS_ACTUALIZAR_SIPSA = int(os.getenv("DIAS_ACTUALIZAR_SIPSA", "30"))
# Hojas del Excel a leer (1.3 = Fertilizantes, enmiendas y acondicionadores de suelo)
HOJAS_SIPSA = [h.strip() for h in os.getenv("HOJAS_SIPSA", "1.3").split(",") if h.strip()]
# Años que se guardan: el último año con datos y los anteriores hasta completar N
ANIOS_HISTORIA = int(os.getenv("ANIOS_HISTORIA", "2"))
# Segundos máximos de espera por cada pedazo de la descarga del Excel (~64 MB)
TIMEOUT_DESCARGA = float(os.getenv("TIMEOUT_DESCARGA", "60"))

# Recomendación: cambio mensual (pendiente / promedio) que consideramos "real"
UMBRAL_PCT_MENSUAL = float(os.getenv("UMBRAL_PCT_MENSUAL", "2"))
# Un departamento cuyo último dato tiene más de estos meses de atraso frente al último
# mes publicado se marca como "dato_desactualizado" (el agente busca vecinos)
MESES_DATO_VIGENTE = int(os.getenv("MESES_DATO_VIGENTE", "3"))

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
