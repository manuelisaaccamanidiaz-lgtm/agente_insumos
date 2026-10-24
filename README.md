# 🌾 Agente Monitor de Precios de Insumos Agrícolas

Agente de IA en Python que consulta precios de insumos (urea, DAP, KCl…) por región y responde al productor.
**Cerebro:** Grok (xAI) · **Lenguaje:** Python 3.11+

## 🎯 El problema

El precio del fertilizante define la rentabilidad de la cosecha, y el pequeño productor
**compra cuando necesita, no cuando conviene**. No tiene tiempo ni herramientas para seguir
los precios por región y anticipar cuándo es buen momento para comprar.

## 🤖 Qué hace el agente

Rastrea precios de insumos (urea, DAP, KCl…) por región, proyecta la ventana de compra y le
avisa al productor con una recomendación y su porqué.
**Quién paga:** cooperativas, almacenes agropecuarios y gremios.

## ✅ Estado: Semana 2, el agente decide qué herramientas usar

> Lo de S1 (agente end-to-end) sigue más abajo como referencia.

## 🔧 S2 · Herramientas

El agente tiene **4 herramientas** y **él mismo decide** cuáles invocar (tool calling).
Todas hacen algo real y **siempre devuelven un dict**: si algo falla, devuelven
`{"error": "...", "tipo_error": "sin_datos|red|config|validacion"}` en vez de romper el loop.

| Herramienta | Qué hace | Fuente real | Errores que maneja |
|---|---|---|---|
| `consultar_precios(insumo, region)` | Historial semanal de precios (COP) | BD SQLite `data/insumos.db` | `sin_datos` (sugiere regiones/insumos que sí hay), `config` (BD sin crear) |
| `analizar_tendencia(insumo, region)` | Variación total y de la última semana, promedio, pendiente (regresión lineal a mano) y recomendación `comprar_ya` / `esperar` / `neutral` + `porque` | BD SQLite | `sin_datos` (menos de 2 datos), `config` |
| `consultar_trm()` | TRM actual (dólar oficial), variación de los últimos 7 registros y tendencia | API de datos abiertos [datos.gov.co · 32sa-8pi3](https://www.datos.gov.co/resource/32sa-8pi3.json) | `red`: timeout (10 s, 1 reintento), sin conexión, error HTTP, JSON inesperado |
| `enviar_alerta(mensaje, chat_id=None)` | Envía la recomendación por Telegram | API de bots de Telegram (`sendMessage`) | `config` (falta token/chat o Telegram lo rechaza), `validacion` (vacío o > 1000 caracteres), `red` |

**Regla de la recomendación** (en [herramientas.py](agente/herramientas.py)): se calcula la pendiente
en COP/semana y se pasa a % del promedio. **≤ -1 %/semana → esperar** (va bajando),
**≥ +1 %/semana → comprar ya** (va subiendo), en medio → **neutral** (sin apuro).

### 🏗️ Arquitectura

```
                          🧑‍🌾 pregunta
                               │
                               ▼
 main.py ──► agente/agente.py   🔁 loop: pensar → actuar → observar  (máx. 5 vueltas)
                 │        ▲
   🧠 Grok (xAI) │        │ resultado JSON (o {"error", "tipo_error"})
   agente/llm.py ▼        │
            agente/herramientas.py  ── ESQUEMAS (lo que ve el LLM) + REGISTRO
                 │
   ┌─────────────┼──────────────────┬──────────────────────┐
   ▼             ▼                  ▼                      ▼
consultar_   analizar_         consultar_trm          enviar_alerta
precios      tendencia              │                      │
   └──────┬──────┘                  ▼                      ▼
          ▼                  🌐 datos.gov.co         📲 api.telegram.org
   agente/datos.py           (TRM, requests)         (bot, requests)
          ▼
   🗄️ data/insumos.db  ◄── scripts/cargar_bd.py ◄── data/precios_ejemplo.csv

 📝 logs/ejecucion_*.json: cada llamada con nombre, argumentos, éxito/error y duración (ms)
```

### 🛡️ Cómo se comporta ante fallas

| Qué falla | Qué hace el agente |
|---|---|
| No hay datos del insumo/región | Lo dice claro, **no inventa precios** y sugiere lo que sí existe (ej.: "hay urea en Boyaca, Meta y Santander"). |
| La API de la TRM no responde | Reintenta 1 vez (timeout de 10 s). Si sigue caída, responde igual con precios y tendencia y aclara que no pudo ver el dólar. |
| Telegram sin configurar o rechaza el mensaje | Da la recomendación en consola y explica por qué no llegó el aviso. Los errores nunca muestran el token. |
| El LLM manda argumentos malos o pide una herramienta que no existe | Error `validacion` que vuelve al LLM para que corrija; el loop no se cae. |
| Falla la API de Grok (sin red, 401, 404, 429) | Mensaje claro (ej.: "revisa XAI_API_KEY") en vez de un traceback. |
| Falta la BD | Error `config` que dice exactamente qué correr: `python scripts/cargar_bd.py`. |

### 🎬 Demo para el video

```bash
python main.py --demo
```

Corre en orden: **1)** caso feliz con las 4 herramientas (urea en Santander + aviso por Telegram),
**2)** caso sin datos (glifosato en Nariño), **3)** caída simulada de la TRM (`SIMULAR_FALLA_TRM=1`).
Guion: [docs/guion_video_s2.md](docs/guion_video_s2.md).

```text
  🔧 consultar_precios({"insumo":"urea","region":"Santander"}) ✅ 1 ms
  🔧 analizar_tendencia({"insumo":"urea","region":"Santander"}) ✅ 1 ms
  🔧 consultar_trm({}) ✅ 989 ms
  🔧 enviar_alerta({"mensaje":"Urea en Santander: ..."}) ✅ ...
  ...
  🔧 consultar_trm({}) ❌ red: No hubo conexión con la API de la TRM (datos.gov.co). ...
```

## 🧱 S1 · Agente corriendo end-to-end

```
Pregunta → 🧠 Grok → 🔧 consultar_precios → 👀 resultado → 🧠 Grok → ✅ respuesta + 📝 log
```

**Ejemplo real de ejecución:**

```text
> python main.py "¿Cómo está la urea en Santander?"
  🔧 vuelta 1: consultar_precios({"insumo":"urea","region":"Santander"})

🤖 Urea en Santander (datos de ejemplo): el bulto de 50 kg ha bajado estas semanas.
- 14 sep 2026: $182.000
- 21 sep 2026: $179.500
- 28 sep 2026: $176.000
- 5 oct 2026: $171.000 (último dato)

> python main.py "¿Cuánto vale el glifosato en Nariño?"
  🔧 vuelta 1: consultar_precios({"insumo":"glifosato","region":"Nariño"})

🤖 No hay datos de precios para el glifosato en Nariño.
```

Con el segundo ejemplo se comprueba que el agente **no inventa precios** cuando no tiene datos.

> ⚠️ Los precios en `data/precios_ejemplo.csv` (y en la BD con `fuente = "ejemplo"`) son **ficticios**. Los datos reales llegan en la Semana 3.

### Lo que todavía falta (próximas semanas)
- Datos reales del DANE/SIPSA y distribuidores, evaluación y costo por tarea (S3).
- Pruebas de carga (S4).

## 📁 Estructura

```
agente-insumos/
├── main.py                 # Punto de entrada (CLI / chat)
├── agente/
│   ├── config.py           # Lee el .env (claves, modelo, rutas)
│   ├── llm.py              # Cliente de Grok (API compatible con OpenAI)
│   ├── agente.py           # 🔁 El loop: pensar → actuar → observar
│   ├── herramientas.py     # 🔧 4 herramientas + esquemas que ve el LLM
│   └── datos.py            # 📦 Consultas a la BD SQLite
├── scripts/cargar_bd.py    # 🗄️ Crea data/insumos.db desde el CSV (idempotente)
├── data/
│   ├── precios_ejemplo.csv # Precios FICTICIOS
│   └── insumos.db          # (se genera, no se sube a GitHub)
├── docs/guion_video_s2.md  # 🎬 Guion del video de S2
├── tests/
│   ├── conftest.py         # BD SQLite temporal para cada prueba
│   ├── test_agente.py      # Loop con un LLM falso (no gasta API)
│   └── test_herramientas.py  # Herramientas con APIs simuladas (sin internet)
├── logs/                   # Rastro de cada ejecución (evidencia)
├── .env.example            # Plantilla de configuración
└── requirements.txt
```

## 🚀 Cómo correrlo

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      |  Linux/Mac:  source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # en Windows: copy .env.example .env
# ⚠️ MANUAL: abre .env y llena XAI_API_KEY y GROK_MODEL (y Telegram, ver abajo)

python scripts/cargar_bd.py # 0) crea data/insumos.db (puedes correrlo varias veces)
pytest -v                   # 1) pruebas sin gastar API ni usar internet
python main.py "¿Cómo está la urea en Santander?"   # 2) agente real
python main.py              # 3) modo chat
python main.py --demo       # 4) los 3 casos del video
```


### 📲 Configurar Telegram (para `enviar_alerta`)

1. En Telegram, abre **@BotFather** → `/newbot` → elige un nombre y un usuario que termine en `bot`.
2. Copia el token que te da (`123456789:AA...`) en `.env` → `TELEGRAM_BOT_TOKEN=`.
3. Abre el chat con **tu** bot y envíale cualquier mensaje (ej.: `hola`). Sin esto, Telegram no deja que el bot te escriba.
4. En el navegador abre `https://api.telegram.org/bot<TOKEN>/getUpdates` y copia el número de `"chat":{"id": ...}` en `.env` → `TELEGRAM_CHAT_ID=`.
5. Prueba: `python main.py "Avísame por Telegram cómo está la urea en Meta"`.

Si no configuras Telegram, el agente funciona igual: solo te dice que no pudo enviar el aviso.

## 🗓️ Hoja de ruta

- [x] **S1:** agente corriendo end-to-end
- [x] **S2:** 4 herramientas reales (SQLite, TRM, Telegram), manejo de fallas y video de 2 min
- [ ] **S3:** datos reales, evaluación propia y costo por tarea
- [ ] **S4:** semana de carga (1.000 unidades, 12 h)
