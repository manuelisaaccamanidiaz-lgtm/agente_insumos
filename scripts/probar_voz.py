"""
probar_voz.py — Prueba rápida de la voz de Abona (no toca la corrida de la S4) 🗣️
Uso:  python scripts/probar_voz.py            (4 preguntas de ejemplo)
      python scripts/probar_voz.py "su pregunta"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agente import config  # noqa: E402
from agente.agente import ejecutar_agente, formatear_uso  # noqa: E402
from agente.llm import crear_cliente  # noqa: E402
from agente.voz_abona import activar_voz_abona  # noqa: E402

PREGUNTAS = [
    "hola, quien eres?",
    "¿Me conviene comprar urea en Santander ahora o espero?",
    "cuanto me cuestan 12 bultos de dap en bucaramanga",
    "las hojas de mi cafe se estan poniendo amarillas, que le echo?",
]

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    activar_voz_abona()
    cliente = crear_cliente()
    for pregunta in (sys.argv[1:] and [" ".join(sys.argv[1:])]) or PREGUNTAS:
        salida = ejecutar_agente(pregunta, cliente, config.GROK_MODEL)
        herramientas = [p["nombre"] for p in salida["rastro"] if p["tipo"] == "herramienta"]
        print(f"\n> {pregunta}\n  herramientas: {', '.join(herramientas) or 'ninguna'}\n")
        print(salida["respuesta"])
        print(f"\n  {formatear_uso(salida['uso'])}\n" + "-" * 70)
