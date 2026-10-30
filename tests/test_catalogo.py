"""
Pruebas del catálogo 📚: alias de insumos, nombres de departamentos y vecinos.
"""
import pytest

from agente.catalogo import ALIAS, PRESENTACIONES, VECINOS, resolver_departamento, resolver_insumo


@pytest.mark.parametrize("texto, oficial", [
    ("urea", "Urea 46%"),
    ("  UREA ", "Urea 46%"),
    ("Urea 46%", "Urea 46%"),
    ("DAP", "Fosfato Diamónico (DAP) 18-46-0"),
    ("fosfato diamónico", "Fosfato Diamónico (DAP) 18-46-0"),
    ("Fosfato Diamonico", "Fosfato Diamónico (DAP) 18-46-0"),
    ("kcl", "Cloruro de Potasio 0-0-60"),
    ("Cloruro de potasio", "Cloruro de Potasio 0-0-60"),
    ("potasio", "Cloruro de Potasio 0-0-60"),
    ("triple 15", "15-15-15"),
    ("10-20-20", "10-20-20"),
])
def test_resolver_insumo(texto, oficial):
    assert resolver_insumo(texto) == oficial


@pytest.mark.parametrize("texto", ["glifosato", "", "urea' OR '1'='1", None, 123])
def test_resolver_insumo_desconocido_da_none(texto):
    assert resolver_insumo(texto) is None


def test_todos_los_alias_apuntan_a_un_insumo_del_catalogo():
    assert set(ALIAS.values()) <= set(PRESENTACIONES)


@pytest.mark.parametrize("texto, oficial", [
    (" boyacá ", "Boyacá"),
    ("BOYACA", "Boyacá"),
    ("bogota", "Bogotá, D.C."),
    ("Bogotá D.C.", "Bogotá, D.C."),
    ("norte de santander", "Norte de Santander"),
    ("santander", "Santander"),
    ("nariño", "Nariño"),
    ("valle", "Valle del Cauca"),
])
def test_resolver_departamento(texto, oficial):
    assert resolver_departamento(texto) == oficial


def test_resolver_departamento_desconocido():
    assert resolver_departamento("Bucaramanga") is None


# ---------- VECINOS: datos geográficos fijos, se revisan con cuidado ----------
def test_vecinos_tiene_32_departamentos_mas_bogota():
    assert len(VECINOS) == 33


def test_vecinos_es_simetrico_y_sin_errores_de_nombre():
    for departamento, vecinos in VECINOS.items():
        assert departamento not in vecinos
        assert len(vecinos) == len(set(vecinos)), f"{departamento} tiene vecinos repetidos"
        for vecino in vecinos:
            assert vecino in VECINOS, f"'{vecino}' (vecino de {departamento}) no es un departamento"
            assert departamento in VECINOS[vecino], f"{vecino} no tiene a {departamento} como vecino"


@pytest.mark.parametrize("a, b, son_vecinos", [
    ("Boyacá", "Santander", True),
    ("Boyacá", "Caldas", True),   # Puerto Boyacá – La Dorada
    ("Boyacá", "Meta", False),    # Paratebueno (Cundinamarca) queda en medio
    ("Bogotá, D.C.", "Meta", True),  # por el Sumapaz
    ("Chocó", "Córdoba", False),  # el Urabá antioqueño los separa
    ("Arauca", "Norte de Santander", False),
    ("Nariño", "Cauca", True),
])
def test_vecinos_casos_que_suelen_confundirse(a, b, son_vecinos):
    assert (b in VECINOS[a]) is son_vecinos


def test_san_andres_no_tiene_vecinos_terrestres():
    assert VECINOS[resolver_departamento("San Andrés")] == []
