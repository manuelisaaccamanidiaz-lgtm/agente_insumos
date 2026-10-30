"""
datos.py — Capa de datos 📦
===========================
Única parte del proyecto que sabe DE DÓNDE salen los precios.
S3: precios REALES del DANE (SIPSA-Insumos), mensuales y por municipio, en la tabla
`precios_sipsa` de data/insumos.db. La llena scripts/actualizar_sipsa.py.
Si cambia la fuente, solo se toca este archivo. El agente ni se entera.

El SIPSA publica un precio por MUNICIPIO; el agente habla de DEPARTAMENTOS. Por eso
buscar_historial agrega por mes: precio_cop = promedio de los municipios, más el rango
(precio_min, precio_max) y cuántos municipios lo reportaron (n_municipios).

Todas las consultas son PARAMETRIZADAS (con `?`): nunca se pega texto del usuario
dentro del SQL, así no hay inyección SQL aunque el LLM mande algo raro.
"""
import sqlite3
from contextlib import closing
from pathlib import Path

from agente.catalogo import normalizar, resolver_departamento, resolver_insumo

ESQUEMA = """
CREATE TABLE IF NOT EXISTS precios_sipsa (
    id                INTEGER PRIMARY KEY,
    anio              INTEGER NOT NULL,
    mes               INTEGER NOT NULL,   -- 1..12
    periodo           TEXT    NOT NULL,   -- AAAA-MM
    cod_departamento  TEXT    NOT NULL,
    departamento      TEXT    NOT NULL,
    cod_municipio     TEXT    NOT NULL,
    municipio         TEXT    NOT NULL,
    producto          TEXT    NOT NULL,   -- nombre oficial del DANE (ver catalogo.py)
    presentacion      TEXT    NOT NULL,
    precio_cop        REAL    NOT NULL,
    fuente            TEXT    NOT NULL DEFAULT 'DANE-SIPSA'
);
-- Índice único: un precio por (mes, municipio, producto, presentación). Hace que el ETL
-- sea idempotente y acelera las búsquedas por producto + departamento.
CREATE UNIQUE INDEX IF NOT EXISTS idx_sipsa_unico
    ON precios_sipsa (producto, presentacion, cod_municipio, periodo);
CREATE INDEX IF NOT EXISTS idx_sipsa_departamento
    ON precios_sipsa (producto, departamento, periodo);
"""

COLUMNAS = ("anio", "mes", "periodo", "cod_departamento", "departamento", "cod_municipio",
            "municipio", "producto", "presentacion", "precio_cop", "fuente")


class BaseDeDatosNoEncontrada(FileNotFoundError):
    """La BD todavía no se ha creado."""


def conectar(ruta_bd: Path, crear: bool = False) -> sqlite3.Connection:
    """Abre la BD. Si no existe (y no se pidió crearla) lanza BaseDeDatosNoEncontrada."""
    ruta_bd = Path(ruta_bd)
    if not crear and not ruta_bd.exists():
        raise BaseDeDatosNoEncontrada(
            f"No existe la base de datos {ruta_bd.name}. "
            "Créala con los datos del DANE: python scripts/actualizar_sipsa.py"
        )
    conexion = sqlite3.connect(ruta_bd)
    conexion.row_factory = sqlite3.Row
    return conexion


def crear_tablas(conexion: sqlite3.Connection) -> None:
    """Crea la tabla y los índices si no existen (se puede llamar muchas veces)."""
    conexion.executescript(ESQUEMA)


def insertar_precios_sipsa(conexion: sqlite3.Connection, registros: list[dict]) -> tuple[int, int]:
    """Guarda los registros en UNA transacción con executemany.
    Si el registro ya existe y el DANE corrigió el precio, se actualiza; si es igual, no
    se toca. Devuelve (filas nuevas, filas actualizadas)."""
    antes_total = conexion.execute("SELECT COUNT(*) FROM precios_sipsa").fetchone()[0]
    antes_cambios = conexion.total_changes
    with conexion:  # commit si todo sale bien, rollback si algo falla
        conexion.executemany(
            f"INSERT INTO precios_sipsa ({', '.join(COLUMNAS)}) "
            f"VALUES ({', '.join(':' + c for c in COLUMNAS)}) "
            "ON CONFLICT (producto, presentacion, cod_municipio, periodo) DO UPDATE SET "
            "precio_cop = excluded.precio_cop, municipio = excluded.municipio, "
            "departamento = excluded.departamento "
            "WHERE precio_cop != excluded.precio_cop",
            registros,
        )
    nuevas = conexion.execute("SELECT COUNT(*) FROM precios_sipsa").fetchone()[0] - antes_total
    return nuevas, conexion.total_changes - antes_cambios - nuevas


def _resolver_municipio(conexion: sqlite3.Connection, departamento: str, texto: str) -> str | None:
    """'cucuta' -> 'San José de Cúcuta'. Primero busca el nombre exacto (sin tildes ni
    mayúsculas); si no, un único municipio del departamento que lo contenga."""
    buscado = normalizar(texto)
    nombres = [f["municipio"] for f in conexion.execute(
        "SELECT DISTINCT municipio FROM precios_sipsa WHERE departamento = ?", (departamento,))]
    exactos = [n for n in nombres if normalizar(n) == buscado]
    if exactos:
        return exactos[0]
    parecidos = [n for n in nombres if buscado and buscado in normalizar(n)]
    return parecidos[0] if len(parecidos) == 1 else None


def buscar_historial(ruta_bd: Path, insumo: str, region: str, municipio: str | None = None,
                     desde: str | None = None) -> list[dict]:
    """Historial MENSUAL de un insumo en un departamento (o en uno de sus municipios),
    ordenado del más viejo al más reciente. `desde` = 'AAAA-MM' para recortar.

    Cada fila: fecha (AAAA-MM-01), periodo, region, insumo, precio_cop (promedio de los
    municipios), precio_min, precio_max, n_municipios, unidad y fuente."""
    producto, departamento = resolver_insumo(insumo), resolver_departamento(region)
    if not producto or not departamento:
        return []
    with closing(conectar(ruta_bd)) as conexion:
        sql = ("SELECT periodo, departamento, producto, presentacion, fuente, "
               "AVG(precio_cop) AS promedio, MIN(precio_cop) AS minimo, MAX(precio_cop) AS maximo, "
               "COUNT(DISTINCT cod_municipio) AS n FROM precios_sipsa "
               "WHERE producto = ? AND departamento = ?")
        params = [producto, departamento]
        if municipio:
            nombre = _resolver_municipio(conexion, departamento, municipio)
            if not nombre:
                return []
            sql, params = sql + " AND municipio = ?", params + [nombre]
        if desde:
            sql, params = sql + " AND periodo >= ?", params + [desde]
        filas = conexion.execute(sql + " GROUP BY periodo, presentacion ORDER BY periodo", params).fetchall()
    return [{
        "fecha": f"{f['periodo']}-01",
        "periodo": f["periodo"],
        "region": f["departamento"],
        **({"municipio": nombre} if municipio else {}),
        "insumo": f["producto"],
        "precio_cop": round(f["promedio"]),
        "precio_min": round(f["minimo"]),
        "precio_max": round(f["maximo"]),
        "n_municipios": f["n"],
        "unidad": f"bulto de {f['presentacion']}",
        "fuente": f["fuente"],
    } for f in filas]


def ultimo_periodo_disponible(ruta_bd: Path, insumo: str | None = None) -> str | None:
    """Último mes publicado ('AAAA-MM') en toda la BD, o de un insumo si se indica."""
    sql, params = "SELECT MAX(periodo) FROM precios_sipsa", ()
    if insumo:
        sql, params = sql + " WHERE producto = ?", (resolver_insumo(insumo),)
    with closing(conectar(ruta_bd)) as conexion:
        return conexion.execute(sql, params).fetchone()[0]


def municipios_disponibles(ruta_bd: Path, region: str, insumo: str) -> list[str]:
    """Municipios del departamento que tienen datos del insumo."""
    producto, departamento = resolver_insumo(insumo), resolver_departamento(region)
    if not producto or not departamento:
        return []
    with closing(conectar(ruta_bd)) as conexion:
        return [f["municipio"] for f in conexion.execute(
            "SELECT DISTINCT municipio FROM precios_sipsa WHERE producto = ? AND departamento = ? "
            "ORDER BY municipio", (producto, departamento))]


def regiones_disponibles(ruta_bd: Path, insumo: str | None = None, desde: str | None = None) -> list[str]:
    """Departamentos con datos (de un insumo, o de cualquiera), opcionalmente desde 'AAAA-MM'."""
    sql, condiciones, params = "SELECT DISTINCT departamento FROM precios_sipsa", [], []
    if insumo:
        condiciones.append("producto = ?")
        params.append(resolver_insumo(insumo))
    if desde:
        condiciones.append("periodo >= ?")
        params.append(desde)
    if condiciones:
        sql += " WHERE " + " AND ".join(condiciones)
    with closing(conectar(ruta_bd)) as conexion:
        return sorted(f["departamento"] for f in conexion.execute(sql, params))


def insumos_disponibles(ruta_bd: Path, region: str | None = None) -> list[str]:
    """Insumos (nombre oficial) con datos en un departamento, o en todos si no se indica."""
    sql, params = "SELECT DISTINCT producto FROM precios_sipsa", ()
    if region:
        sql, params = sql + " WHERE departamento = ?", (resolver_departamento(region),)
    with closing(conectar(ruta_bd)) as conexion:
        return sorted(f["producto"] for f in conexion.execute(sql, params))


def ultimo_precio_por_departamento(ruta_bd: Path, insumo: str, departamentos: list[str]) -> list[dict]:
    """Para cada departamento de la lista, el precio del ÚLTIMO mes en que tuvo datos del
    insumo (promedio, mínimo y máximo de sus municipios). Ordenado del más barato al más caro."""
    producto = resolver_insumo(insumo)
    if not producto or not departamentos:
        return []
    marcas = ", ".join("?" for _ in departamentos)
    with closing(conectar(ruta_bd)) as conexion:
        filas = conexion.execute(
            "WITH ultimo AS (SELECT departamento, MAX(periodo) AS periodo FROM precios_sipsa "
            f"  WHERE producto = ? AND departamento IN ({marcas}) GROUP BY departamento) "
            "SELECT p.departamento, p.periodo, AVG(p.precio_cop) AS promedio, "
            "MIN(p.precio_cop) AS minimo, MAX(p.precio_cop) AS maximo, "
            "COUNT(DISTINCT p.cod_municipio) AS n FROM precios_sipsa p "
            "JOIN ultimo u ON p.departamento = u.departamento AND p.periodo = u.periodo "
            "WHERE p.producto = ? GROUP BY p.departamento ORDER BY promedio",
            [producto, *departamentos, producto],
        ).fetchall()
    return [{"region": f["departamento"], "periodo": f["periodo"], "precio_cop": round(f["promedio"]),
             "precio_min": round(f["minimo"]), "precio_max": round(f["maximo"]),
             "n_municipios": f["n"]} for f in filas]


def buscar_departamento_de_municipio(ruta_bd: Path, texto: str) -> list[tuple[str, str]]:
    """'Bucaramanga' -> [('Santander', 'Bucaramanga')]. Sirve cuando el LLM pone un
    municipio en el campo `region`. Puede devolver varios (hay municipios homónimos)."""
    buscado = normalizar(texto)
    with closing(conectar(ruta_bd)) as conexion:
        filas = conexion.execute("SELECT DISTINCT departamento, municipio FROM precios_sipsa").fetchall()
    return [(f["departamento"], f["municipio"]) for f in filas if normalizar(f["municipio"]) == buscado]
