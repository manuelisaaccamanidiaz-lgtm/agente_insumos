"""
main.py — Punto de entrada 🚪
Uso:
    python main.py "¿Cómo está el precio de la urea en Santander?"
    python main.py            (modo chat: escribe 'salir' para terminar)
    python main.py --demo     (los 3 casos del video de S2)
"""
import os
import sys

from agente import config
from agente.agente import ejecutar_agente, guardar_log
from agente.llm import crear_cliente

# Casos del video: (título, pregunta, ¿simular caída de la TRM?)
CASOS_DEMO = [
    ("1/3 · Caso feliz (usa las 4 herramientas)",
     "¿Me conviene comprar urea en Santander ahora o espero? Avísame por Telegram.", False),
    ("2/3 · Caso sin datos",
     "¿Cómo está el glifosato en Nariño?", False),
    ("3/3 · Falla de una API (TRM caída a propósito)",
     "¿Me conviene comprar DAP en Boyacá ahora o espero?", True),
]


def mostrar_paso(paso: dict) -> None:
    """🔧 nombre(args) ✅ 120 ms   |   🔧 nombre(args) ❌ red: mensaje"""
    llamada = f"  🔧 {paso['nombre']}({paso['argumentos'] or ''})"
    if paso["exito"]:
        print(f"{llamada} ✅ {paso['duracion_ms']} ms")
    else:
        print(f"{llamada} ❌ {paso['tipo_error']}: {paso['error']}")


def preguntar(cliente, pregunta: str) -> None:
    salida = ejecutar_agente(pregunta, cliente, config.GROK_MODEL)
    for paso in salida["rastro"]:
        if paso["tipo"] == "herramienta":
            mostrar_paso(paso)
    print(f"\n🤖 {salida['respuesta']}")
    print(f"\n📝 Log guardado en: {guardar_log(pregunta, salida)}\n")


def demo(cliente) -> None:
    """Corre en orden los 3 casos del video."""
    for titulo, pregunta, simular_falla in CASOS_DEMO:
        print("=" * 70 + f"\n🎬 {titulo}\n🧑‍🌾 {pregunta}")
        if simular_falla:
            os.environ["SIMULAR_FALLA_TRM"] = "1"
            print("   (SIMULAR_FALLA_TRM=1 → consultar_trm apunta a una URL inválida)")
        print()
        try:
            preguntar(cliente, pregunta)
        finally:
            os.environ.pop("SIMULAR_FALLA_TRM", None)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # emojis sin errores en la consola de Windows
    cliente = crear_cliente()
    if sys.argv[1:] == ["--demo"]:
        demo(cliente)
        return
    if len(sys.argv) > 1:
        preguntar(cliente, " ".join(sys.argv[1:]))
        return
    print("🌾 Agente de insumos agrícolas — escribe 'salir' para terminar\n")
    while (pregunta := input("🧑‍🌾 Tú: ").strip()).lower() != "salir":
        if pregunta:
            preguntar(cliente, pregunta)


if __name__ == "__main__":
    main()
