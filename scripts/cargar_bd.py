"""
cargar_bd.py — Crea y llena la base de datos SQLite 🗄️
======================================================
Lee data/precios_ejemplo.csv y lo guarda en data/insumos.db (tabla `precios`).
Es IDEMPOTENTE: si lo corres dos veces no duplica filas (índice único + INSERT OR IGNORE).

Uso:
    python scripts/cargar_bd.py
"""
import csv
import sys
from contextlib import closing
from pathlib import Path

# Permite correr el script directamente (python scripts/cargar_bd.py) e importar `agente`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agente import config  # noqa: E402
from agente.datos import conectar, crear_tablas, insertar_precios  # noqa: E402


def cargar(ruta_csv: Path, ruta_bd: Path, fuente: str = "ejemplo") -> tuple[int, int]:
    """Carga el CSV en la BD. Devuelve (filas leídas, filas nuevas insertadas)."""
    with open(ruta_csv, encoding="utf-8") as f:
        filas = [
            {**fila, "precio_cop": int(fila["precio_cop"]), "fuente": fuente}
            for fila in csv.DictReader(f)
        ]
    Path(ruta_bd).parent.mkdir(parents=True, exist_ok=True)
    with closing(conectar(ruta_bd, crear=True)) as conexion:
        crear_tablas(conexion)
        nuevas = insertar_precios(conexion, filas)
    return len(filas), nuevas


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # emojis sin errores en la consola de Windows
    leidas, nuevas = cargar(config.RUTA_PRECIOS, config.RUTA_BD)
    print(f"🗄️  BD: {config.RUTA_BD}")
    print(f"✅ {leidas} filas leídas del CSV · {nuevas} nuevas · {leidas - nuevas} ya existían")
