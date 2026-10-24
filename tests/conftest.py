"""
Fixtures compartidas por todas las pruebas 🧪
Cada prueba usa su PROPIA base SQLite temporal (tmp_path), cargada desde el CSV de ejemplo.
Así no dependemos de data/insumos.db ni del .env real (Telegram queda "sin configurar").
"""
import pytest

from agente import config
from scripts.cargar_bd import cargar


@pytest.fixture(autouse=True)
def bd_temporal(tmp_path, monkeypatch):
    ruta = tmp_path / "insumos_test.db"
    cargar(config.RUTA_PRECIOS, ruta)
    monkeypatch.setattr(config, "RUTA_BD", ruta)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    monkeypatch.delenv("SIMULAR_FALLA_TRM", raising=False)
    return ruta
