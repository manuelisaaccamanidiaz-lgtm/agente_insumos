"""
datos.py — Capa de datos 📦
===========================
Única parte del proyecto que sabe DE DÓNDE salen los precios.
Hoy: un CSV de ejemplo. Mañana (S3): DANE/SIPSA, distribuidores, etc.
Si cambia la fuente, solo se toca este archivo. El agente ni se entera.
"""
import csv
from pathlib import Path


def _normalizar(texto: str) -> str:
    """'Boyacá ' -> 'boyaca' para que las búsquedas no fallen por tildes o mayúsculas."""
    reemplazos = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouaeiou")
    return texto.strip().lower().translate(reemplazos)


def cargar_precios(ruta: Path) -> list[dict]:
    """Lee el CSV y devuelve una lista de filas (dicts) con el precio como entero."""
    with open(ruta, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    for fila in filas:
        fila["precio_cop"] = int(fila["precio_cop"])
    return filas


def buscar_historial(filas: list[dict], insumo: str, region: str) -> list[dict]:
    """Filtra por insumo y región, ordenado del más viejo al más reciente."""
    insumo_n, region_n = _normalizar(insumo), _normalizar(region)
    resultado = [
        f for f in filas
        if _normalizar(f["insumo"]) == insumo_n and _normalizar(f["region"]) == region_n
    ]
    return sorted(resultado, key=lambda f: f["fecha"])
