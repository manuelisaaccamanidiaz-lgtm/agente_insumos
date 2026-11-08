"""
resumen_carga.py — Reporte de la semana de carga (S4) 📄
=======================================================
Lee bitacora/s4_bitacora.csv y bitacora/s4_eventos.jsonl (solo lectura: se puede correr
mientras la carga sigue andando) y escribe REPORTE_S4.md en la raíz del proyecto.

Uso:
    python scripts/resumen_carga.py
"""
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
BITACORA = RAIZ / "bitacora" / "s4_bitacora.csv"
EVENTOS = RAIZ / "bitacora" / "s4_eventos.jsonl"
COLA = RAIZ / "data" / "cola_s4.jsonl"
SALIDA = RAIZ / "REPORTE_S4.md"
TRM_URL = "https://www.datos.gov.co/resource/32sa-8pi3.json"
NOMBRES = {"precio": "Precio por departamento", "municipio": "Precio por municipio",
           "tendencia": "Comprar ya o esperar", "costo": "Costo de N bultos",
           "vecinos": "Sin dato vigente (vecinos)", "alias": "Nombres comunes (alias)",
           "fuera_de_alcance": "Fuera de alcance (agronomía)"}


def miles(n, d=0):
    return f"{n:,.{d}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def trm_actual():
    try:
        r = requests.get(TRM_URL, params={"$order": "vigenciadesde DESC", "$limit": 1}, timeout=10)
        r.raise_for_status()
        return float(r.json()[0]["valor"])
    except Exception:
        return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    filas = list(csv.DictReader(open(BITACORA, encoding="utf-8-sig", newline="")))
    eventos = [json.loads(l) for l in open(EVENTOS, encoding="utf-8") if l.strip()] if EVENTOS.exists() else []
    total_cola = sum(1 for l in open(COLA, encoding="utf-8") if l.strip())
    if not filas:
        print("La bitácora está vacía.")
        return 1

    hora = lambda s: datetime.fromisoformat(s)  # noqa: E731
    inicio, fin = hora(filas[0]["inicio"]), hora(filas[-1]["fin"])
    horas = (fin - inicio).total_seconds() / 3600
    exitos = sum(f["exito"] == "True" for f in filas)
    costo = sum(float(f["costo_usd"] or 0) for f in filas)
    t_in = sum(int(f["tokens_entrada"] or 0) for f in filas)
    t_out = sum(int(f["tokens_salida"] or 0) for f in filas)
    durs = sorted(float(f["duracion_s"]) for f in filas)
    p95 = durs[max(0, int(len(durs) * 0.95) - 1)]
    llamadas = sum(int(f["llamadas_llm"] or 0) for f in filas)
    trm = trm_actual()
    tipos = Counter(e["tipo"] for e in eventos)
    en_curso = len(filas) < total_cola and not (eventos and eventos[-1]["tipo"] == "fin_proceso")

    # tramo continuo más largo: sin huecos mayores a 10 minutos entre tareas
    tramo_max, ini_tramo, anterior = 0.0, inicio, None
    for f in filas:
        a, b = hora(f["inicio"]), hora(f["fin"])
        if anterior and (a - anterior).total_seconds() > 600:
            ini_tramo = a
        tramo_max = max(tramo_max, (b - ini_tramo).total_seconds() / 3600)
        anterior = b

    por_hora = Counter(hora(f["fin"]).strftime("%Y-%m-%d %H:00") for f in filas)
    intenciones = defaultdict(lambda: [0, 0])
    for f in filas:
        intenciones[f["intencion"]][0] += 1
        intenciones[f["intencion"]][1] += f["exito"] == "True"
    fallos = [f for f in filas if f["exito"] != "True"]
    con_reintento = sum(int(f["reintentos"] or 0) > 0 for f in filas)
    errores_herr = Counter(e.split(":")[1] for f in filas for e in f["errores_herramientas"].split(" | ") if ":" in e)

    cop = lambda usd: f" (≈ ${miles(usd * trm)} COP)" if trm else ""  # noqa: E731
    L = ["# REPORTE S4 · Semana de carga de Abona", ""]
    if en_curso:
        L += [f"> **Corrida en curso.** Corte del {fin:%d/%m/%Y %H:%M} (hora de Colombia): "
              f"{miles(len(filas))} de {miles(total_cola)} tareas. El reporte se regenera al terminar.", ""]
    L += ["## Resumen", "",
          "| Indicador | Valor |", "|---|---|",
          f"| Unidades de trabajo completadas | **{miles(len(filas))}** de {miles(total_cola)} en cola |",
          f"| Tasa de éxito | **{miles(exitos / len(filas) * 100, 1)} %** ({miles(exitos)} de {miles(len(filas))}) |",
          f"| Duración desatendida | **{miles(horas, 2)} h** ({inicio:%d/%m %H:%M} → {fin:%d/%m %H:%M}, hora de Colombia) |",
          f"| Tramo continuo más largo | {miles(tramo_max, 2)} h |",
          f"| Costo total | **US$ {miles(costo, 2)}**{cop(costo)} |",
          f"| Costo por tarea | **US$ {miles(costo / len(filas), 4)}**{cop(costo / len(filas))} |",
          f"| Llamadas a Grok | {miles(llamadas)} ({miles(llamadas / len(filas), 2)} por tarea) |",
          f"| Tokens | {miles(t_in + t_out)} ({miles(t_in)} de entrada · {miles(t_out)} de salida) |",
          f"| Duración por tarea | mediana {miles(statistics.median(durs), 1)} s · p95 {miles(p95, 1)} s |",
          f"| Modelo y ruta | `grok-4.6` por la pasarela del reto (llave del reto) |", "",
          "El costo usa un precio efectivo de US$ 1,59 por millón de tokens medido en el panel de la plataforma; "
          "es una **cota superior** (la pasarela cobra más barato el prompt repetido)."
          + (f" Pesos con la TRM de hoy: ${miles(trm, 2)}." if trm else ""), "",
          "## Cómo corrió sin intervención", "",
          f"- **Cola:** {miles(total_cola)} preguntas únicas generadas con `scripts/generar_cola.py` a partir de la BD real del DANE.",
          "- **Ejecutor:** `scripts/carga.py` toma una tarea cada 33 s y escribe la bitácora después de cada una (reanudable).",
          "- **Supervisor:** `scripts/carga_supervisor.ps1` relanza el proceso si se cae.",
          "- **Recuperación:** reintentos a Grok con espera de 5, 15 y 45 s; pausa de 5 min tras 10 fallos seguidos.", "",
          "| Evento | Veces |", "|---|---|",
          f"| Arranques del proceso | {tipos.get('inicio_proceso', 0)} |",
          f"| Reinicios automáticos del supervisor | {tipos.get('reinicio_automatico', 0)} |",
          f"| Reintentos a Grok | {tipos.get('reintento', 0)} (en {con_reintento} tareas) |",
          f"| Pausas por fallos seguidos | {tipos.get('pausa_por_fallos', 0)} |",
          f"| Excepciones atrapadas | {tipos.get('excepcion', 0)} |", "",
          "Errores de herramientas que el agente manejó sin fallar la tarea: "
          + (", ".join(f"`{k}` × {v}" for k, v in errores_herr.most_common()) or "ninguno") + ".", "",
          "## Éxito por tipo de pregunta", "", "| Tipo | Tareas | Éxito |", "|---|---|---|"]
    for k, nombre in NOMBRES.items():
        if k in intenciones:
            t, e = intenciones[k]
            L.append(f"| {nombre} | {miles(t)} | {miles(e)} ({miles(e / t * 100, 1)} %) |")
    L += ["", "## Tareas por hora", "", "| Hora | Tareas |", "|---|---|"]
    L += [f"| {h} | {n} |" for h, n in sorted(por_hora.items())]
    L += ["", "## Fallos", ""]
    if fallos:
        L += ["| Tarea | Tipo | Motivo |", "|---|---|---|"]
        L += [f"| {f['id']} | {f['intencion']} | {f['motivo_fallo'][:120]} |" for f in fallos[:15]]
    else:
        L.append("Ninguna tarea falló.")
    L += ["", "## Archivos", "",
          "- `bitacora/s4_bitacora.csv`: una fila por tarea (hora, entrada, resultado, éxito, motivo, herramientas, reintentos, tokens, costo).",
          "- `bitacora/s4_bitacora.jsonl`: lo mismo con la respuesta completa y el rastro de herramientas.",
          "- `bitacora/s4_eventos.jsonl`: arranques, reinicios, reintentos, pausas y resúmenes por hora.", "",
          "## Para la entrega", "", "```",
          f"Unidades: {miles(len(filas))} tareas completas en {miles(horas, 2)} h desatendidas",
          f"Tasa de éxito: {miles(exitos / len(filas) * 100, 1)} %",
          f"Costo total: US$ {miles(costo, 2)}" + (f" (≈ ${miles(costo * trm)} COP)" if trm else ""),
          f"Costo por tarea: US$ {miles(costo / len(filas), 4)}" + (f" (≈ ${miles(costo / len(filas) * trm)} COP)" if trm else ""),
          "```", ""]
    SALIDA.write_text("\n".join(L), encoding="utf-8")
    print(f"✅ {SALIDA.name}: {miles(len(filas))} tareas · {miles(exitos / len(filas) * 100, 1)} % · "
          f"{miles(horas, 2)} h · US$ {miles(costo, 2)}" + (" · CORRIDA EN CURSO" if en_curso else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
