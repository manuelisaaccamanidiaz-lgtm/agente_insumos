"""
Pruebas del pipeline ETL (scripts/actualizar_sipsa.py) SIN internet 🏭
- El Excel es uno pequeño y falso con la forma del DANE (fixture `excel_falso` en conftest.py).
- La descarga se simula con unittest.mock: nunca sale una petición real.
"""
import os
import sqlite3
import time
from contextlib import closing
from unittest.mock import MagicMock, patch

import openpyxl
import pytest
import requests

from agente import config
from agente.datos import buscar_historial
from scripts import actualizar_sipsa
from scripts.actualizar_sipsa import (DescargaFallida, actualizar, extraer, mes_a_numero,
                                      necesita_descarga, transformar)
from tests.conftest import crear_excel_falso, filas_ejemplo


# ---------- TRANSFORMAR ----------
@pytest.mark.parametrize("texto, numero", [
    ("Enero", 1), ("Enero ", 1), ("  SEPTIEMBRE  ", 9), ("setiembre", 9), ("Diciembre", 12),
    ("Mes", None), ("", None), (None, None), (3, None),
])
def test_mes_en_texto_a_numero(texto, numero):
    assert mes_a_numero(texto) == numero


def test_transformar_limpia_y_filtra(excel_falso):
    registros, leidas = transformar(excel_falso, ["1.3"], anios_historia=2)
    assert leidas == len(filas_ejemplo())  # ignora títulos, filas vacías y notas al pie
    productos = {r["producto"] for r in registros}
    assert "Crecer 500" not in productos  # no está en el catálogo
    assert not any(r["producto"] == "10-30-10" for r in registros)  # su presentación de 1 litro no va
    sep = next(r for r in registros if r["municipio"] == "Piedecuesta" and r["periodo"] == "2026-09")
    assert sep["mes"] == 9 and sep["departamento"] == "Santander"  # sin espacios sobrantes
    assert sep["fuente"] == "DANE-SIPSA"
    assert all(r["precio_cop"] != 999999 for r in registros)  # la hoja 1.4 no se lee


def test_filtro_de_anios(excel_falso):
    dos, _ = transformar(excel_falso, ["1.3"], anios_historia=2)
    assert {r["anio"] for r in dos} == {2025, 2026}  # el último año del archivo y el anterior
    tres, _ = transformar(excel_falso, ["1.3"], anios_historia=3)
    assert 2024 in {r["anio"] for r in tres}


def test_hoja_con_formato_cambiado_da_error_claro(tmp_path):
    ruta = tmp_path / "raro.xlsx"
    crear_excel_falso(ruta, filas_ejemplo())
    libro = openpyxl.load_workbook(ruta)
    libro["1.3"]["A9"] = "Otra cosa"
    libro.save(ruta)
    with pytest.raises(ValueError, match="fila 9"):
        transformar(ruta, ["1.3"], anios_historia=2)


# ---------- CARGAR ----------
def test_etl_es_idempotente(tmp_path, excel_falso):
    ruta = tmp_path / "otra.db"
    primera = actualizar(excel_falso, ruta, ["1.3"], 2)
    assert primera["insertadas"] == primera["registros_validos"] > 0
    assert (primera["desde"], primera["hasta"]) == ("2025-03", "2026-09")
    segunda = actualizar(excel_falso, ruta, ["1.3"], 2)
    assert (segunda["insertadas"], segunda["actualizadas"]) == (0, 0)  # no duplica
    with closing(sqlite3.connect(ruta)) as c:
        assert c.execute("SELECT COUNT(*) FROM precios_sipsa").fetchone()[0] == primera["registros_validos"]


def test_etl_actualiza_un_precio_corregido_por_el_dane(tmp_path):
    ruta_bd, ruta_xlsx = tmp_path / "bd.db", tmp_path / "x.xlsx"
    filas = filas_ejemplo()
    crear_excel_falso(ruta_xlsx, filas)
    actualizar(ruta_xlsx, ruta_bd, ["1.3"], 2)
    corregidas = [f[:8] + (f[8] + 1000,) if f[5] == "Bucaramanga" and f[1] == "Septiembre"
                  and f[0] == 2026 and f[6] == "Urea 46%" else f for f in filas]
    crear_excel_falso(ruta_xlsx, corregidas)
    resumen = actualizar(ruta_xlsx, ruta_bd, ["1.3"], 2)
    assert (resumen["insertadas"], resumen["actualizadas"]) == (0, 1)
    ultimo = buscar_historial(ruta_bd, "urea", "Santander", "Bucaramanga")[-1]
    assert ultimo["precio_cop"] == 161000


# ---------- Capa de datos sobre lo cargado ----------
def test_agrega_por_departamento_promedio_min_max(bd_temporal):
    historial = buscar_historial(bd_temporal, "urea", "Santander")
    sep = historial[-1]
    assert sep["periodo"] == "2026-09" and sep["fecha"] == "2026-09-01"
    assert (sep["precio_cop"], sep["precio_min"], sep["precio_max"], sep["n_municipios"]) == (163000, 160000, 166000, 2)
    assert sep["region"] == "Santander" and sep["insumo"] == "Urea 46%"
    assert sep["unidad"] == "bulto de 50 kilogramos" and sep["fuente"] == "DANE-SIPSA"
    assert [f["periodo"] for f in historial] == sorted(f["periodo"] for f in historial)  # viejo → nuevo


def test_consulta_por_municipio_con_tildes_y_mayusculas(bd_temporal):
    historial = buscar_historial(bd_temporal, "UREA", "SANTANDÉR", "piedecuesta")
    assert [f["precio_cop"] for f in historial][-2:] == [168000, 166000]
    assert historial[-1]["municipio"] == "Piedecuesta" and historial[-1]["n_municipios"] == 1
    assert buscar_historial(bd_temporal, "urea", "Norte de Santander", "cucuta")[-1]["precio_cop"] == 170000


def test_historial_inexistente_es_lista_vacia(bd_temporal):
    assert buscar_historial(bd_temporal, "glifosato", "Santander") == []
    assert buscar_historial(bd_temporal, "urea", "Santander", "Medellín") == []
    assert buscar_historial(bd_temporal, "urea' OR '1'='1", "x") == []


# ---------- EXTRAER (descarga) ----------
def _envejecer(ruta, dias):
    viejo = time.time() - dias * 86400
    os.utime(ruta, (viejo, viejo))


def test_necesita_descarga(tmp_path):
    ruta = tmp_path / "sipsa.xlsx"
    assert necesita_descarga(ruta, 30) is True  # no existe
    ruta.write_bytes(b"x")
    assert necesita_descarga(ruta, 30) is False
    assert necesita_descarga(ruta, 30, forzar=True) is True
    _envejecer(ruta, 31)
    assert necesita_descarga(ruta, 30) is True


def test_copia_local_reciente_no_descarga(tmp_path):
    ruta = tmp_path / "sipsa.xlsx"
    ruta.write_bytes(b"x")
    with patch.object(actualizar_sipsa.requests, "get") as get:
        assert extraer("https://ejemplo.invalid/a.xlsx", ruta, dias=30) == ruta
    get.assert_not_called()


def test_descarga_exitosa_escribe_el_archivo(tmp_path):
    ruta = tmp_path / "sipsa.xlsx"
    resp = MagicMock(headers={"content-length": "6"})
    resp.__enter__.return_value = resp
    resp.iter_content.return_value = [b"abc", b"def"]
    with patch.object(actualizar_sipsa.requests, "get", return_value=resp) as get:
        assert extraer("https://ejemplo.invalid/a.xlsx", ruta, dias=30) == ruta
    assert ruta.read_bytes() == b"abcdef"
    assert not (tmp_path / "sipsa.xlsx.part").exists()
    assert get.call_args.kwargs["stream"] is True
    assert get.call_args.kwargs["timeout"] == config.TIMEOUT_DESCARGA


def test_descarga_falla_pero_usa_la_copia_local(tmp_path, capsys):
    ruta = tmp_path / "sipsa.xlsx"
    ruta.write_bytes(b"copia vieja")
    _envejecer(ruta, 90)
    with patch.object(actualizar_sipsa.requests, "get", side_effect=requests.ConnectionError()):
        assert extraer("https://ejemplo.invalid/a.xlsx", ruta, dias=30) == ruta
    assert ruta.read_bytes() == b"copia vieja"  # la copia anterior queda intacta
    assert "copia local" in capsys.readouterr().out


def test_descarga_cortada_no_deja_archivos_a_medias(tmp_path):
    carpeta = tmp_path / "descargas"
    ruta = carpeta / "sipsa.xlsx"
    resp = MagicMock(headers={})
    resp.__enter__.return_value = resp
    resp.iter_content.side_effect = requests.ConnectionError("se cayó a mitad")
    with patch.object(actualizar_sipsa.requests, "get", return_value=resp):
        with pytest.raises(DescargaFallida):
            extraer("https://ejemplo.invalid/a.xlsx", ruta, dias=30)
    assert list(carpeta.iterdir()) == []  # ni el .xlsx ni el .part a medias


def test_descarga_404_sin_copia_local_da_error_claro(tmp_path):
    resp = MagicMock(status_code=404)
    resp.__enter__.return_value = resp
    resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    with patch.object(actualizar_sipsa.requests, "get", return_value=resp):
        with pytest.raises(DescargaFallida, match="SIPSA_URL"):
            extraer("https://ejemplo.invalid/a.xlsx", tmp_path / "sipsa.xlsx", dias=30)


def test_main_sin_internet_ni_copia_devuelve_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "RUTA_SIPSA", tmp_path / "no_existe.xlsx")
    with patch.object(actualizar_sipsa.requests, "get", side_effect=requests.ConnectionError()):
        assert actualizar_sipsa.main([]) == 1
    assert "No se pudo descargar" in capsys.readouterr().out
