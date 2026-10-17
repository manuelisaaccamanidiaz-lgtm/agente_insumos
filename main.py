"""
main.py — Punto de entrada 🚪
Uso:
    python main.py "¿Cómo está el precio de la urea en Santander?"
    python main.py            (modo chat: escribe 'salir' para terminar)
"""
import sys

from agente import config
from agente.agente import ejecutar_agente, guardar_log
from agente.llm import crear_cliente


def preguntar(cliente, pregunta: str) -> None:
    salida = ejecutar_agente(pregunta, cliente, config.GROK_MODEL)
    for paso in salida["rastro"]:
        if paso["tipo"] == "herramienta":
            print(f"  🔧 vuelta {paso['vuelta']}: {paso['nombre']}({paso['argumentos']})")
    print(f"\n🤖 {salida['respuesta']}")
    print(f"\n📝 Log guardado en: {guardar_log(pregunta, salida)}\n")


def main() -> None:
    cliente = crear_cliente()
    if len(sys.argv) > 1:
        preguntar(cliente, " ".join(sys.argv[1:]))
        return
    print("🌾 Agente de insumos agrícolas — escribe 'salir' para terminar\n")
    while (pregunta := input("🧑‍🌾 Tú: ").strip()).lower() != "salir":
        if pregunta:
            preguntar(cliente, pregunta)


if __name__ == "__main__":
    main()
