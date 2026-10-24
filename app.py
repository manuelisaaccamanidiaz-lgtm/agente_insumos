"""
app.py — Interfaz web de chat 💬 (Streamlit)
============================================
Solo es otra "cara" del agente: reutiliza ejecutar_agente y crear_cliente tal cual,
igual que main.py. Nada de la lógica del agente vive aquí.

Uso:
    streamlit run app.py
"""
import os

import streamlit as st

from agente import config
from agente.agente import ejecutar_agente, guardar_log
from agente.llm import crear_cliente

EJEMPLOS = {
    "✅ Caso feliz": "¿Me conviene comprar urea en Santander ahora o espero? Avísame por Telegram.",
    "🔍 Caso sin datos": "¿Cómo está el glifosato en Nariño?",
}

st.set_page_config(page_title="Asesor de Insumos Agrícolas", page_icon="🌾")
st.title("🌾 Asesor de Insumos Agrícolas")
st.caption(
    "El pequeño productor compra el fertilizante cuando lo necesita, no cuando conviene. "
    "Pregúntale al agente por un insumo y una región: revisa precios, tendencia y dólar, "
    "y te dice si comprar ya o esperar, y por qué."
)


@st.cache_resource
def obtener_cliente():
    """Crea el cliente de Grok una sola vez (no en cada recarga de la página)."""
    return crear_cliente()


def sin_latex(texto: str) -> str:
    """Streamlit interpreta '$...$' como fórmula matemática: '$171.000 ... $3.650' se
    vería roto. Escapamos el signo pesos para que se muestre tal cual."""
    return (texto or "").replace("$", r"\$")


def mostrar_rastro(rastro: list[dict]) -> None:
    """Expander con cada herramienta que usó el agente: ✅/❌, argumentos y duración."""
    pasos = [p for p in rastro if p["tipo"] in ("herramienta", "error_llm")]
    if not pasos:
        return
    with st.expander("🔧 Herramientas usadas"):
        for paso in pasos:
            if paso["tipo"] == "error_llm":
                st.markdown(f"❌ **Grok:** {sin_latex(paso['mensaje'])}")
            elif paso["exito"]:
                st.markdown(f"✅ `{paso['nombre']}({paso['argumentos'] or ''})` · {paso['duracion_ms']} ms")
            else:
                st.markdown(f"❌ `{paso['nombre']}({paso['argumentos'] or ''})` · {paso['duracion_ms']} ms  \n"
                            f"**{paso['tipo_error']}:** {sin_latex(paso['error'])}")


# ---------- Configuración: si falta algo, se explica en vez de romper ----------
try:
    cliente = obtener_cliente()
except SystemExit as e:  # validar_config() avisa así cuando falta algo en el .env
    st.error(
        f"{e}\n\n**Cómo arreglarlo:**\n"
        "1. Copia `.env.example` como `.env` en la carpeta del proyecto.\n"
        "2. Llena `XAI_API_KEY` (empieza con `xai-`, se crea en https://console.x.ai) y `GROK_MODEL`.\n"
        "3. Detén la app (Ctrl+C) y vuelve a correr `streamlit run app.py`."
    )
    st.stop()

if not config.RUTA_BD.exists():
    st.warning("No existe la base de datos de precios. Córrela con: `python scripts/cargar_bd.py`")

# ---------- Barra lateral ----------
if "mensajes" not in st.session_state:
    st.session_state.mensajes = []  # [{"role", "content", "rastro"}]

with st.sidebar:
    st.header("🧪 Pruebas rápidas")
    for etiqueta, pregunta in EJEMPLOS.items():
        if st.button(etiqueta, width="stretch", help=pregunta):
            st.session_state.pendiente = pregunta

    if st.checkbox("Simular falla de TRM", help="consultar_trm usará una URL inválida (SIMULAR_FALLA_TRM=1)"):
        os.environ["SIMULAR_FALLA_TRM"] = "1"
    else:
        os.environ.pop("SIMULAR_FALLA_TRM", None)

    if st.button("🗑️ Limpiar chat", width="stretch"):
        st.session_state.mensajes = []
        st.rerun()

    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        st.info("📲 Telegram no está configurado: el agente responderá, pero no podrá enviar alertas.")
    st.caption("⚠️ Los precios actuales son de ejemplo (ficticios). "
               "Cada pregunta se responde por separado: el agente no recuerda las anteriores.")

# ---------- Chat ----------
for mensaje in st.session_state.mensajes:
    with st.chat_message(mensaje["role"], avatar="🧑‍🌾" if mensaje["role"] == "user" else "🤖"):
        st.markdown(sin_latex(mensaje["content"]))
        if mensaje.get("rastro"):
            mostrar_rastro(mensaje["rastro"])

pregunta = st.chat_input("Ej: ¿Cómo está la urea en Boyacá?") or st.session_state.pop("pendiente", None)
if pregunta:
    st.session_state.mensajes.append({"role": "user", "content": pregunta})
    with st.chat_message("user", avatar="🧑‍🌾"):
        st.markdown(sin_latex(pregunta))

    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner("Consultando precios, tendencia y dólar..."):
            salida = ejecutar_agente(pregunta, cliente, config.GROK_MODEL)
            guardar_log(pregunta, salida)  # misma evidencia en logs/ que la versión de consola
        st.markdown(sin_latex(salida["respuesta"]))
        mostrar_rastro(salida["rastro"])

    st.session_state.mensajes.append(
        {"role": "assistant", "content": salida["respuesta"], "rastro": salida["rastro"]}
    )
