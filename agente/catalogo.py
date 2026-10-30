"""
catalogo.py — Nombres oficiales y geografía 📚
==============================================
El campesino dice "urea" o "triple 15"; el DANE publica "Urea 46%" o "15-15-15".
Aquí se traduce lo que escribe la gente (o el LLM) al nombre EXACTO del Excel de SIPSA,
para que el ETL y las consultas hablen el mismo idioma.

También vive aquí la geografía fija: los 32 departamentos + Bogotá D.C. con sus vecinos
terrestres (para sugerir dónde comprar cuando en la región no hay datos).
"""
import re
import unicodedata


def normalizar(texto: str) -> str:
    """'  Boyacá ' -> 'boyaca', 'Bogotá, D.C.' -> 'bogota dc', 'UREA  46%' -> 'urea 46%'.
    Quita tildes, mayúsculas, puntos/comas y espacios repetidos."""
    sin_tildes = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    sin_puntos = re.sub(r"[.,]", " ", sin_tildes.lower())
    return re.sub(r"\s+", " ", sin_puntos).strip()


# ---------- Insumos ----------
# Nombre oficial del DANE (hoja 1.3) → presentación que cargamos. Solo bultos de 50 kg:
# así todos los precios son comparables entre sí y con lo que compra el productor.
PRESENTACIONES = {
    "Urea 46%": "50 kilogramos",
    "Fosfato Diamónico (DAP) 18-46-0": "50 kilogramos",
    "Cloruro de Potasio 0-0-60": "50 kilogramos",
    "15-15-15": "50 kilogramos",
    "10-20-20": "50 kilogramos",
    "10-30-10": "50 kilogramos",
    "13-26-6": "50 kilogramos",
    "17-6-18-2(Mg)": "50 kilogramos",
    "Sulfato de Amonio (SAM) 21-0-0-24(S)": "50 kilogramos",
    "Cal Dolomita": "50 kilogramos",
}

# Alias (ya normalizados) → nombre oficial. El nombre oficial también funciona como alias.
ALIAS = {
    "urea": "Urea 46%",
    "urea 46": "Urea 46%",
    "dap": "Fosfato Diamónico (DAP) 18-46-0",
    "fosfato diamonico": "Fosfato Diamónico (DAP) 18-46-0",
    "fosfato diamonico dap": "Fosfato Diamónico (DAP) 18-46-0",
    "18-46-0": "Fosfato Diamónico (DAP) 18-46-0",
    "kcl": "Cloruro de Potasio 0-0-60",
    "cloruro de potasio": "Cloruro de Potasio 0-0-60",
    "potasio": "Cloruro de Potasio 0-0-60",
    "muriato de potasio": "Cloruro de Potasio 0-0-60",
    "0-0-60": "Cloruro de Potasio 0-0-60",
    "triple 15": "15-15-15",
    "triple quince": "15-15-15",
    "15 15 15": "15-15-15",
    "10 20 20": "10-20-20",
    "10 30 10": "10-30-10",
    "13 26 6": "13-26-6",
    "17-6-18": "17-6-18-2(Mg)",
    "17-6-18-2": "17-6-18-2(Mg)",
    "sulfato de amonio": "Sulfato de Amonio (SAM) 21-0-0-24(S)",
    "sam": "Sulfato de Amonio (SAM) 21-0-0-24(S)",
    "21-0-0": "Sulfato de Amonio (SAM) 21-0-0-24(S)",
    "dolomita": "Cal Dolomita",
    "cal dolomitica": "Cal Dolomita",
    **{normalizar(oficial): oficial for oficial in PRESENTACIONES},
}

# Nombre corto para mostrarle al LLM en los errores ("insumos disponibles: urea, dap, ...")
NOMBRES_CORTOS = {
    "Urea 46%": "urea",
    "Fosfato Diamónico (DAP) 18-46-0": "dap",
    "Cloruro de Potasio 0-0-60": "kcl",
    "15-15-15": "15-15-15",
    "10-20-20": "10-20-20",
    "10-30-10": "10-30-10",
    "13-26-6": "13-26-6",
    "17-6-18-2(Mg)": "17-6-18-2",
    "Sulfato de Amonio (SAM) 21-0-0-24(S)": "sulfato de amonio",
    "Cal Dolomita": "cal dolomita",
}


def resolver_insumo(texto: str) -> str | None:
    """'UREA' -> 'Urea 46%', 'fosfato diamónico' -> 'Fosfato Diamónico (DAP) 18-46-0'.
    Devuelve None si el insumo no está en el catálogo."""
    if not isinstance(texto, str):
        return None
    return ALIAS.get(normalizar(texto))


# ---------- Departamentos ----------
# Vecinos TERRESTRES de cada departamento (los 32 + Bogotá D.C.), con los nombres tal
# como los escribe el DANE. Es simétrico: si A es vecino de B, B es vecino de A
# (lo verifica tests/test_catalogo.py). San Andrés es una isla: no tiene vecinos.
# Ojo con dos casos que se confunden: Boyacá SÍ limita con Caldas (Puerto Boyacá–La Dorada,
# río Magdalena) y NO con Meta (entre ambos queda Paratebueno, Cundinamarca).
VECINOS = {
    "Amazonas": ["Caquetá", "Putumayo", "Vaupés"],
    "Antioquia": ["Bolívar", "Boyacá", "Caldas", "Chocó", "Córdoba", "Risaralda", "Santander"],
    "Arauca": ["Boyacá", "Casanare", "Vichada"],
    "Archipiélago de San Andrés, Providencia y Santa Catalina": [],
    "Atlántico": ["Bolívar", "Magdalena"],
    "Bogotá, D.C.": ["Cundinamarca", "Huila", "Meta"],
    "Bolívar": ["Antioquia", "Atlántico", "Cesar", "Córdoba", "Magdalena", "Santander", "Sucre"],
    "Boyacá": ["Antioquia", "Arauca", "Caldas", "Casanare", "Cundinamarca",
               "Norte de Santander", "Santander"],
    "Caldas": ["Antioquia", "Boyacá", "Cundinamarca", "Risaralda", "Tolima"],
    "Caquetá": ["Amazonas", "Cauca", "Guaviare", "Huila", "Meta", "Putumayo", "Vaupés"],
    "Casanare": ["Arauca", "Boyacá", "Cundinamarca", "Meta", "Vichada"],
    "Cauca": ["Caquetá", "Huila", "Nariño", "Putumayo", "Tolima", "Valle del Cauca"],
    "Cesar": ["Bolívar", "La Guajira", "Magdalena", "Norte de Santander", "Santander"],
    "Chocó": ["Antioquia", "Risaralda", "Valle del Cauca"],
    "Córdoba": ["Antioquia", "Bolívar", "Sucre"],
    "Cundinamarca": ["Bogotá, D.C.", "Boyacá", "Caldas", "Casanare", "Huila", "Meta", "Tolima"],
    "Guainía": ["Guaviare", "Vaupés", "Vichada"],
    "Guaviare": ["Caquetá", "Guainía", "Meta", "Vaupés", "Vichada"],
    "Huila": ["Bogotá, D.C.", "Caquetá", "Cauca", "Cundinamarca", "Meta", "Tolima"],
    "La Guajira": ["Cesar", "Magdalena"],
    "Magdalena": ["Atlántico", "Bolívar", "Cesar", "La Guajira"],
    "Meta": ["Bogotá, D.C.", "Caquetá", "Casanare", "Cundinamarca", "Guaviare", "Huila", "Vichada"],
    "Nariño": ["Cauca", "Putumayo"],
    "Norte de Santander": ["Boyacá", "Cesar", "Santander"],
    "Putumayo": ["Amazonas", "Caquetá", "Cauca", "Nariño"],
    "Quindío": ["Risaralda", "Tolima", "Valle del Cauca"],
    "Risaralda": ["Antioquia", "Caldas", "Chocó", "Quindío", "Tolima", "Valle del Cauca"],
    "Santander": ["Antioquia", "Bolívar", "Boyacá", "Cesar", "Norte de Santander"],
    "Sucre": ["Bolívar", "Córdoba"],
    "Tolima": ["Caldas", "Cauca", "Cundinamarca", "Huila", "Quindío", "Risaralda", "Valle del Cauca"],
    "Valle del Cauca": ["Cauca", "Chocó", "Quindío", "Risaralda", "Tolima"],
    "Vaupés": ["Amazonas", "Caquetá", "Guainía", "Guaviare"],
    "Vichada": ["Arauca", "Casanare", "Guainía", "Guaviare", "Meta"],
}

# Formas comunes de escribir un departamento (normalizadas) → nombre del DANE
_ALIAS_DEPARTAMENTOS = {
    **{normalizar(d): d for d in VECINOS},
    "bogota": "Bogotá, D.C.",
    "bogota dc": "Bogotá, D.C.",
    "bogota distrito capital": "Bogotá, D.C.",
    "distrito capital": "Bogotá, D.C.",
    "valle": "Valle del Cauca",
    "guajira": "La Guajira",
    "norte santander": "Norte de Santander",
    "san andres": "Archipiélago de San Andrés, Providencia y Santa Catalina",
    "san andres y providencia": "Archipiélago de San Andrés, Providencia y Santa Catalina",
}


def resolver_departamento(texto: str) -> str | None:
    """' boyacá ' -> 'Boyacá', 'bogota' -> 'Bogotá, D.C.'. None si no es un departamento."""
    if not isinstance(texto, str):
        return None
    return _ALIAS_DEPARTAMENTOS.get(normalizar(texto))
