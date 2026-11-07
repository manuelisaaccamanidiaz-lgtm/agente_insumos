"""
carga.py — Corrida desatendida de la semana de carga (S4) 🏭
============================================================
Recorre data/cola_s4.jsonl tarea por tarea con el agente real (Grok por la pasarela
del reto) y escribe la bitácora DESPUÉS DE CADA TAREA:

  bitacora/s4_bitacora.csv     una fila por tarea (hora, entrada, resultado, éxito, costo...)
  bitacora/s4_bitacora.jsonl   lo mismo + respuesta completa y rastro de herramientas
  bitacora/s4_eventos.jsonl    arranques, reintentos, pausas, resúmenes por hora, excepciones

Es REANUDABLE: si se reinicia, salta las tareas que ya están en la bitácora.
Nada tumba el proceso: cada tarea va en try/except, Grok se reintenta con espera
exponencial y, tras 10 fallos seguidos, hace una pausa y continúa.

Uso:
    python scripts/carga.py                      (ritmo por defecto: una tarea cada 33 s ≈ 12,8 h para 1.400)
    python scripts/carga.py --intervalo 30
    python scripts/carga.py --prueba 5           (5 tareas, sin espera, bitácora en bitacora/prueba/)
"""
import argparse
import csv
import json
import signal
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from agente import config, herramientas  # noqa: E402
from agente.agente import ejecutar_agente  # noqa: E402

ZONA = ZoneInfo("America/Bogota")
RUTA_COLA = RAIZ / "data" / "cola_s4.jsonl"
ESPERAS_REINTENTO = (5, 15, 45)   # segundos entre reintentos si Grok falla
FALLOS_SEGUIDOS_PAUSA = 10
PAUSA_LARGA_S = 300
COLUMNAS = ["n", "id", "intencion", "inicio", "fin", "duracion_s", "entrada", "resultado", "exito",
            "motivo_fallo", "herramientas_usadas", "errores_herramientas", "reintentos",
            "llamadas_llm", "tokens_entrada", "tokens_salida", "costo_usd"]

_detener = False


def _ahora() -> str:
    return datetime.now(ZONA).isoformat(timespec="seconds")


def _al_pedir_salir(*_):
    """Ctrl+C: termina la tarea actual y sale limpio."""
    global _detener
    _detener = True
    print("\n⏹️  Deteniendo al terminar la tarea actual...")


def _mantener_despierto(activar: bool) -> None:
    """En Windows evita que el PC se suspenda mientras corre la carga."""
    if sys.platform != "win32":
        return
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(
        ES_CONTINUOUS | ES_SYSTEM_REQUIRED if activar else ES_CONTINUOUS)


class Bitacora:
    """Escribe CSV + JSONL + eventos con flush inmediato (si se va la luz, no se pierde nada)."""

    def __init__(self, carpeta: Path):
        carpeta.mkdir(parents=True, exist_ok=True)
        self.csv = carpeta / "s4_bitacora.csv"
        self.jsonl = carpeta / "s4_bitacora.jsonl"
        self.eventos = carpeta / "s4_eventos.jsonl"
        if not self.csv.exists():
            with open(self.csv, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow(COLUMNAS)

    def hechas(self) -> dict[str, dict]:
        """Tareas ya registradas (id → fila), para reanudar."""
        if not self.jsonl.exists():
            return {}
        filas = {}
        with open(self.jsonl, encoding="utf-8") as f:
            for linea in f:
                try:
                    fila = json.loads(linea)
                    filas[fila["id"]] = fila
                except (json.JSONDecodeError, KeyError):
                    continue  # una línea cortada por un apagón no rompe la reanudación
        return filas

    def tarea(self, fila: dict) -> None:
        with open(self.csv, "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow([fila.get(c) for c in COLUMNAS])
        with open(self.jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")

    def evento(self, tipo: str, **datos) -> None:
        with open(self.eventos, "a", encoding="utf-8") as f:
            f.write(json.dumps({"hora": _ahora(), "tipo": tipo, **datos}, ensure_ascii=False) + "\n")


def evaluar_tarea(tarea: dict, salida: dict) -> tuple[bool, str]:
    """¿La tarea se resolvió bien? Devuelve (éxito, motivo del fallo)."""
    if salida.get("error_llm"):
        return False, f"error de Grok: {salida['error_llm']}"
    if not (salida.get("respuesta") or "").strip():
        return False, "respuesta vacía"
    if "límite de vueltas" in salida["respuesta"]:
        return False, "se alcanzó el límite de vueltas"
    usadas = {p["nombre"] for p in salida.get("rastro", []) if p.get("tipo") == "herramienta"}
    prohibidas = usadas & set(tarea["herramientas_prohibidas"])
    if prohibidas:
        return False, f"usó herramientas prohibidas: {', '.join(sorted(prohibidas))}"
    if tarea["herramientas_alguna"] and not usadas & set(tarea["herramientas_alguna"]):
        return False, f"no usó ninguna de: {', '.join(tarea['herramientas_alguna'])}"
    return True, ""


def correr_tarea(tarea: dict, cliente, bitacora: Bitacora, dormir=time.sleep) -> dict:
    """Resuelve UNA tarea con reintentos. Nunca lanza excepciones."""
    inicio, t0 = _ahora(), time.perf_counter()
    reintentos, salida = 0, {}
    for intento in range(len(ESPERAS_REINTENTO) + 1):
        try:
            salida = ejecutar_agente(tarea["pregunta"], cliente, config.GROK_MODEL)
        except Exception as e:  # último seguro: ni un bug del agente detiene la carga
            salida = {"error_llm": f"excepción {type(e).__name__}: {e}", "rastro": [], "respuesta": ""}
            bitacora.evento("excepcion", id=tarea["id"], detalle=traceback.format_exc(limit=3)[-800:])
        if not salida.get("error_llm") or intento == len(ESPERAS_REINTENTO):
            break
        espera = ESPERAS_REINTENTO[intento]
        reintentos += 1
        bitacora.evento("reintento", id=tarea["id"], intento=reintentos, espera_s=espera,
                        motivo=salida["error_llm"][:300])
        dormir(espera)

    exito, motivo = evaluar_tarea(tarea, salida)
    pasos = [p for p in salida.get("rastro", []) if p.get("tipo") == "herramienta"]
    uso = salida.get("uso") or {}
    return {
        "id": tarea["id"], "intencion": tarea["intencion"], "inicio": inicio, "fin": _ahora(),
        "duracion_s": round(time.perf_counter() - t0, 2), "entrada": tarea["pregunta"],
        "resultado": (salida.get("respuesta") or "")[:500], "exito": exito, "motivo_fallo": motivo,
        "herramientas_usadas": " | ".join(p["nombre"] for p in pasos),
        "errores_herramientas": " | ".join(f"{p['nombre']}:{p.get('tipo_error')}"
                                           for p in pasos if not p.get("exito")),
        "reintentos": reintentos, "llamadas_llm": uso.get("llamadas_llm"),
        "tokens_entrada": uso.get("tokens_entrada"), "tokens_salida": uso.get("tokens_salida"),
        "costo_usd": uso.get("costo_usd"),
        "respuesta_completa": salida.get("respuesta"), "rastro": salida.get("rastro", []),
    }


def _avisar_telegram(texto: str, bitacora: Bitacora) -> None:
    """Resumen por hora a Telegram (opcional). Si falla, se anota y se sigue."""
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return
    resultado = herramientas.enviar_alerta(texto)
    if "error" in resultado:
        bitacora.evento("telegram_fallo", detalle=resultado["error"][:200])


def _verificar() -> str | None:
    """Revisa todo antes de arrancar. Devuelve el problema o None."""
    if not config.XAI_API_KEY or not config.GROK_MODEL:
        return "Faltan XAI_API_KEY o GROK_MODEL en el .env."
    if "api.x.ai" in config.XAI_BASE_URL:
        return "XAI_BASE_URL apunta a api.x.ai: la S4 debe usar la pasarela del reto."
    if not config.RUTA_BD.exists():
        return "No existe data/insumos.db: corre python scripts/actualizar_sipsa.py"
    if not RUTA_COLA.exists():
        return "No existe data/cola_s4.jsonl: corre python scripts/generar_cola.py"
    return None


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Corrida desatendida de la S4.")
    parser.add_argument("--intervalo", type=float, default=33,
                        help="segundos entre el inicio de una tarea y la siguiente (por defecto 33)")
    parser.add_argument("--prueba", type=int, default=0, help="corre N tareas sin espera (bitácora aparte)")
    args = parser.parse_args(argv)

    problema = _verificar()
    if problema:
        print(f"❌ {problema}")
        return 2

    # Modo carga: no se ofrece enviar_alerta (evita 1.400 mensajes de Telegram)
    herramientas.ESQUEMAS = [e for e in herramientas.ESQUEMAS if e["function"]["name"] != "enviar_alerta"]
    from agente.llm import crear_cliente
    cliente = crear_cliente()

    bitacora = Bitacora(RAIZ / "bitacora" / ("prueba" if args.prueba else ""))
    cola = [json.loads(l) for l in open(RUTA_COLA, encoding="utf-8") if l.strip()]
    hechas = bitacora.hechas()
    pendientes = [t for t in cola if t["id"] not in hechas]
    if args.prueba:
        pendientes = pendientes[:args.prueba]
    if not pendientes:
        print("✅ La cola ya está completa.")
        return 0

    signal.signal(signal.SIGINT, _al_pedir_salir)
    _mantener_despierto(True)
    bitacora.evento("inicio_proceso", pendientes=len(pendientes), ya_hechas=len(hechas),
                    intervalo_s=args.intervalo, modelo=config.GROK_MODEL)
    print(f"🚜 {len(pendientes):,} tareas pendientes ({len(hechas):,} ya hechas) · una cada "
          f"{args.intervalo:.0f} s · modelo {config.GROK_MODEL}")

    n = len(hechas)
    exitos = sum(1 for f in hechas.values() if f.get("exito"))
    costo = sum(f.get("costo_usd") or 0 for f in hechas.values())
    fallos_seguidos, ultima_hora = 0, time.time()
    try:
        for tarea in pendientes:
            if _detener:
                break
            t0 = time.time()
            fila = correr_tarea(tarea, cliente, bitacora)
            n += 1
            fila["n"] = n
            bitacora.tarea(fila)
            exitos += fila["exito"]
            costo += fila["costo_usd"] or 0
            fallos_seguidos = 0 if fila["exito"] else fallos_seguidos + 1
            restantes = len(cola) - n
            eta = datetime.fromtimestamp(time.time() + restantes * args.intervalo, ZONA)
            print(f"[{n:04d}/{len(cola)}] {datetime.now(ZONA):%H:%M:%S} {'✅' if fila['exito'] else '❌'} "
                  f"{fila['intencion']} · {fila['llamadas_llm']} llamadas · {fila['duracion_s']:.1f} s · "
                  f"${costo:.4f} acumulado · éxito {exitos / n:.1%} · fin aprox. {eta:%a %H:%M}"
                  + (f"  ({fila['motivo_fallo']})" if not fila["exito"] else ""), flush=True)

            if fallos_seguidos >= FALLOS_SEGUIDOS_PAUSA:
                bitacora.evento("pausa_por_fallos", fallos_seguidos=fallos_seguidos, pausa_s=PAUSA_LARGA_S)
                print(f"⏸️  {fallos_seguidos} fallos seguidos: pausa de {PAUSA_LARGA_S // 60} min y sigo.")
                time.sleep(PAUSA_LARGA_S)
                fallos_seguidos = 0
            if time.time() - ultima_hora >= 3600:
                ultima_hora = time.time()
                resumen = f"S4 · {n} tareas · éxito {exitos / n:.1%} · costo ${costo:.2f} USD"
                bitacora.evento("resumen_hora", tareas=n, exitos=exitos, costo_usd=round(costo, 4))
                _avisar_telegram(resumen, bitacora)
            if not args.prueba:
                espera = args.intervalo - (time.time() - t0)
                while espera > 0 and not _detener:
                    time.sleep(min(espera, 1))
                    espera -= 1
    finally:
        _mantener_despierto(False)
        bitacora.evento("fin_proceso", tareas=n, exitos=exitos, costo_usd=round(costo, 4),
                        motivo="detenido" if _detener else "cola terminada")
    print(f"🏁 {n:,} tareas · éxito {exitos / max(n, 1):.1%} · costo ${costo:.4f} USD")
    return 0 if (not _detener or args.prueba) else 1


if __name__ == "__main__":
    sys.exit(main())
