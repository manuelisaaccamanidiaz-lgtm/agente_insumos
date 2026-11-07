"""
generar_cola.py — Cola de tareas para la semana de carga (S4) 📋
================================================================
Genera data/cola_s4.jsonl con preguntas ÚNICAS y variadas, armadas solo con
combinaciones que existen en la BD real (precios_sipsa). Semilla fija = reproducible.

Uso:
    python scripts/generar_cola.py              (1.400 tareas por defecto)
    python scripts/generar_cola.py --total 1200

Cada tarea:
    {"id", "intencion", "pregunta", "herramientas_alguna", "herramientas_prohibidas"}
  - herramientas_alguna: el agente debe usar AL MENOS UNA de estas (lista vacía = ninguna exigida)
  - herramientas_prohibidas: no debe usar ninguna de estas
"""
import argparse
import json
import random
import sqlite3
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from agente.catalogo import NOMBRES_CORTOS, VECINOS  # noqa: E402

RUTA_BD = RAIZ / "data" / "insumos.db"
RUTA_COLA = RAIZ / "data" / "cola_s4.jsonl"
SEMILLA = 2026
MESES_VIGENTE = 3

PRECIO = ["consultar_precios", "analizar_tendencia", "calcular_costo_compra"]
TODAS = PRECIO + ["consultar_regiones_vecinas", "consultar_trm", "enviar_alerta"]

# Reparto por intención (suma 1.0)
REPARTO = {"precio": 0.30, "municipio": 0.15, "tendencia": 0.20, "costo": 0.15,
           "vecinos": 0.10, "alias": 0.05, "fuera_de_alcance": 0.05}

PLANTILLAS = {
    "precio": ["¿Cuánto vale el bulto de {i} en {d}?", "¿A cómo está la {i} en {d}?",
               "Buenas, ¿qué precio tiene el {i} en {d}?", "precio del {i} en {d}",
               "¿Cuánto está costando el {i} por los lados de {d}?",
               "Necesito saber el precio del bulto de {i} en {d}, por favor",
               "¿En cuánto anda el {i} en {d} este mes?", "Hola, ¿cuánto cuesta el {i} en {d}?"],
    "municipio": ["¿Cuánto vale el {i} en {m}?", "¿A cómo está el bulto de {i} en {m}, {d}?",
                  "precio del {i} en {m}", "Vivo en {m}, ¿cuánto me sale el bulto de {i}?",
                  "¿Qué precio tiene el {i} en el municipio de {m}?"],
    "tendencia": ["¿Me conviene comprar {i} en {d} ahora o espero?",
                  "¿Compro ya el {i} o espero que baje? Estoy en {d}",
                  "¿El {i} en {d} está subiendo o bajando?", "¿es buen momento para comprar {i} en {d}?",
                  "Tengo que abonar pronto, ¿compro el {i} ya o aguanto? Soy de {d}",
                  "¿Cómo viene el precio del {i} en {d}, me apuro a comprar?"],
    "costo": ["¿Cuánto me cuestan {n} bultos de {i} en {d}?", "Si compro {n} bultos de {i} en {d}, ¿cuánto pago?",
              "¿Cuánta plata necesito para {n} bultos de {i} en {d}?",
              "Voy a comprar {n} bultos de {i} en {d}, ¿cuánto me sale todo?",
              "cuanto valen {n} bultos de {i} en {d}"],
    "vecinos": ["¿Cuánto vale el {i} en {d}?", "¿A cómo está el bulto de {i} en {d}?",
                "Estoy en {d}, ¿dónde consigo {i} más barato?", "precio del {i} en {d}"],
    "alias": ["¿A cómo está el {a} en {d}?", "¿Cuánto vale el bulto de {a} en {d}?",
              "precio del {a} en {d}", "¿Me conviene comprar {a} en {d} ahora?"],
}
ALIAS_EXTRA = {"Urea 46%": ["urea granulada", "urea 46"], "15-15-15": ["triple 15", "triple quince"],
               "Cloruro de Potasio 0-0-60": ["cloruro de potasio", "muriato de potasio", "potasio"],
               "Fosfato Diamónico (DAP) 18-46-0": ["fosfato diamonico", "18-46-0"],
               "Sulfato de Amonio (SAM) 21-0-0-24(S)": ["sulfato de amonio"], "Cal Dolomita": ["dolomita"]}
CULTIVOS = ["café", "papa", "cacao", "aguacate", "plátano", "maíz", "arroz", "tomate", "cebolla",
            "frijol", "yuca", "caña panelera", "mora", "lulo", "naranja", "mango", "manzana", "uva"]
FUERA = ["¿Cuántos bultos de abono le echo a una hectárea de {c}?",
         "Las hojas de mi {c} se están poniendo amarillas, ¿qué le aplico?",
         "¿Qué marca de fertilizante es mejor para el {c}?",
         "¿Cada cuánto debo abonar el {c}?", "Me salió una plaga en el {c}, ¿qué veneno uso?",
         "El abono que compré no le está sirviendo al {c}, ¿por qué será?",
         "¿Qué fórmula de abono le sirve más al {c} en clima frío?",
         "¿Puedo mezclar urea con otro producto para el {c}?"]


def _sin_tildes(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()


def _variar(texto: str, rnd: random.Random) -> str:
    """Variaciones de escritura reales: sin tildes, minúsculas, sin signos de pregunta."""
    if rnd.random() < 0.35:
        texto = _sin_tildes(texto)
    if rnd.random() < 0.40:
        texto = texto.lower()
    if rnd.random() < 0.25:
        texto = texto.replace("¿", "").replace("?", "")
    return texto


def _datos(ruta_bd: Path) -> dict:
    con = sqlite3.connect(ruta_bd)
    publicado = con.execute("SELECT MAX(periodo) FROM precios_sipsa").fetchone()[0]
    anio, mes = map(int, publicado.split("-"))
    i = anio * 12 + mes - 1 - MESES_VIGENTE
    corte = f"{i // 12}-{i % 12 + 1:02d}"
    ultimos = con.execute("SELECT producto, departamento, MAX(periodo) FROM precios_sipsa "
                          "GROUP BY producto, departamento").fetchall()
    vigentes = [(p, d) for p, d, m in ultimos if m >= corte]
    viejos = {(p, d) for p, d, m in ultimos if m < corte}
    con_datos = {(p, d) for p, d, _ in ultimos}
    productos = sorted({p for p, _ in vigentes})
    # Sin dato vigente: dato viejo, o el departamento no reporta ese insumo (y tiene vecinos)
    vecinos = sorted(viejos | {(p, d) for p in productos for d in VECINOS
                               if VECINOS[d] and (p, d) not in con_datos})
    municipios = con.execute("SELECT producto, departamento, municipio FROM precios_sipsa "
                             "WHERE periodo >= ? GROUP BY 1, 2, 3", (corte,)).fetchall()
    con.close()
    return {"vigentes": vigentes, "vecinos": vecinos, "municipios": municipios, "publicado": publicado}


def generar(total: int, ruta_bd: Path = RUTA_BD, semilla: int = SEMILLA) -> list[dict]:
    rnd = random.Random(semilla)
    datos = _datos(ruta_bd)
    corto = lambda p: NOMBRES_CORTOS.get(p, p)  # noqa: E731
    tareas, vistas = [], set()

    def agregar(intencion, pregunta, alguna, prohibidas):
        pregunta = _variar(pregunta, rnd)
        if pregunta.lower() in vistas:
            return False
        vistas.add(pregunta.lower())
        tareas.append({"id": f"s4-{len(tareas) + 1:04d}", "intencion": intencion, "pregunta": pregunta,
                       "herramientas_alguna": alguna, "herramientas_prohibidas": prohibidas})
        return True

    for intencion, fraccion in REPARTO.items():
        meta, intentos = round(total * fraccion), 0
        hechas = 0
        while hechas < meta and intentos < meta * 50:
            intentos += 1
            if intencion == "fuera_de_alcance":
                ok = agregar(intencion, rnd.choice(FUERA).format(c=rnd.choice(CULTIVOS)), [], TODAS)
            elif intencion == "municipio":
                p, d, m = rnd.choice(datos["municipios"])
                ok = agregar(intencion, rnd.choice(PLANTILLAS[intencion]).format(i=corto(p), d=d, m=m),
                             PRECIO, ["enviar_alerta"])
            elif intencion == "vecinos":
                p, d = rnd.choice(datos["vecinos"])
                ok = agregar(intencion, rnd.choice(PLANTILLAS[intencion]).format(i=corto(p), d=d),
                             ["consultar_regiones_vecinas", "consultar_precios"], ["enviar_alerta"])
            elif intencion == "alias":
                p, d = rnd.choice([v for v in datos["vigentes"] if v[0] in ALIAS_EXTRA])
                ok = agregar(intencion, rnd.choice(PLANTILLAS[intencion]).format(
                    a=rnd.choice(ALIAS_EXTRA[p]), d=d), PRECIO, ["enviar_alerta"])
            else:
                p, d = rnd.choice(datos["vigentes"])
                texto = rnd.choice(PLANTILLAS[intencion]).format(i=corto(p), d=d, n=rnd.randint(1, 50))
                alguna = {"precio": PRECIO, "tendencia": ["analizar_tendencia"],
                          "costo": ["calcular_costo_compra"]}[intencion]
                ok = agregar(intencion, texto, alguna, ["enviar_alerta"])
            hechas += ok
    rnd.shuffle(tareas)  # mezcladas: así cada hora de la corrida tiene de todo
    for n, t in enumerate(tareas, 1):
        t["id"] = f"s4-{n:04d}"
    return tareas


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Genera la cola de tareas de la S4.")
    parser.add_argument("--total", type=int, default=1400)
    args = parser.parse_args()
    tareas = generar(args.total)
    with open(RUTA_COLA, "w", encoding="utf-8") as f:
        for t in tareas:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"✅ {len(tareas):,} tareas en {RUTA_COLA.relative_to(RAIZ)}")
    for intencion in REPARTO:
        print(f"   - {intencion}: {sum(t['intencion'] == intencion for t in tareas)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
