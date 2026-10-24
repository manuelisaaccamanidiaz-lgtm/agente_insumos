"""
datos.py — Capa de datos 📦
===========================
Única parte del proyecto que sabe DE DÓNDE salen los precios.
S2: una base SQLite (data/insumos.db) que se llena con scripts/cargar_bd.py.
S3: la misma tabla recibirá datos reales (DANE/SIPSA, distribuidores) con otra `fuente`.
Si cambia la fuente, solo se toca este archivo. El agente ni se entera.

Todas las consultas son PARAMETRIZADAS (con `?`): nunca se pega texto del usuario
dentro del SQL, así no hay inyección SQL aunque el LLM mande algo raro.
"""
import sqlite3
from contextlib import closing
import unicodedata
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS precios (
    id          INTEGER PRIMARY KEY,
    fecha       TEXT    NOT NULL,   -- AAAA-MM-DD
    region      TEXT    NOT NULL,
    insumo      TEXT    NOT NULL,
    precio_cop  INTEGER NOT NULL,
    unidad      TEXT    NOT NULL,
    fuente      TEXT    NOT NULL
);
-- Índice único: acelera la búsqueda por (insumo, region, fecha) y evita duplicados
-- cuando el script de carga se corre más de una vez.
CREATE UNIQUE INDEX IF NOT EXISTS idx_precios_insumo_region_fecha
    ON precios (insumo, region, fecha, fuente);
"""


class BaseDeDatosNoEncontrada(FileNotFoundError):
    """La BD todavía no se ha creado."""


def _normalizar(texto: str) -> str:
    """'Boyacá ' -> 'boyaca', 'Nariño' -> 'narino' para que las búsquedas no fallen
    por tildes, eñes o mayúsculas."""
    sin_tildes = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return sin_tildes.strip().lower()


def conectar(ruta_bd: Path, crear: bool = False) -> sqlite3.Connection:
    """Abre la BD y registra la función `normalizar` para usarla dentro del SQL.
    Si la BD no existe (y no se pidió crearla) lanza BaseDeDatosNoEncontrada."""
    ruta_bd = Path(ruta_bd)
    if not crear and not ruta_bd.exists():
        raise BaseDeDatosNoEncontrada(
            f"No existe la base de datos {ruta_bd.name}. Córrela primero con: python scripts/cargar_bd.py"
        )
    conexion = sqlite3.connect(ruta_bd)
    conexion.row_factory = sqlite3.Row
    conexion.create_function("normalizar", 1, _normalizar, deterministic=True)
    return conexion


def crear_tablas(conexion: sqlite3.Connection) -> None:
    """Crea la tabla y los índices si no existen (se puede llamar muchas veces)."""
    conexion.executescript(ESQUEMA)


def insertar_precios(conexion: sqlite3.Connection, filas: list[dict]) -> int:
    """Inserta filas ignorando las repetidas. Devuelve cuántas filas NUEVAS entraron."""
    antes = conexion.total_changes
    conexion.executemany(
        "INSERT OR IGNORE INTO precios (fecha, region, insumo, precio_cop, unidad, fuente) "
        "VALUES (:fecha, :region, :insumo, :precio_cop, :unidad, :fuente)",
        filas,
    )
    conexion.commit()
    return conexion.total_changes - antes


def buscar_historial(ruta_bd: Path, insumo: str, region: str) -> list[dict]:
    """Historial de un insumo en una región, ordenado del más viejo al más reciente."""
    with closing(conectar(ruta_bd)) as conexion:
        filas = conexion.execute(
            "SELECT fecha, region, insumo, precio_cop, unidad, fuente FROM precios "
            "WHERE normalizar(insumo) = ? AND normalizar(region) = ? ORDER BY fecha",
            (_normalizar(insumo), _normalizar(region)),
        ).fetchall()
    return [dict(f) for f in filas]


def insumos_disponibles(ruta_bd: Path, region: str | None = None) -> list[str]:
    """Insumos con datos (en una región, o en todas si no se indica)."""
    sql, params = "SELECT DISTINCT insumo FROM precios", ()
    if region:
        sql, params = sql + " WHERE normalizar(region) = ?", (_normalizar(region),)
    with closing(conectar(ruta_bd)) as conexion:
        return sorted(f["insumo"] for f in conexion.execute(sql, params))


def regiones_disponibles(ruta_bd: Path, insumo: str | None = None) -> list[str]:
    """Regiones con datos (de un insumo, o de cualquiera si no se indica)."""
    sql, params = "SELECT DISTINCT region FROM precios", ()
    if insumo:
        sql, params = sql + " WHERE normalizar(insumo) = ?", (_normalizar(insumo),)
    with closing(conectar(ruta_bd)) as conexion:
        return sorted(f["region"] for f in conexion.execute(sql, params))
