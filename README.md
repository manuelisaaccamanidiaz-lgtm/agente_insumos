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

## ✅ Estado: Semana 3 (parte 1), el agente usa precios REALES del DANE

> Lo de S2 (herramientas y manejo de fallas) y S1 (agente end-to-end) sigue más abajo.

## 📊 S3 · Datos reales

Los precios ya **no son de ejemplo**: salen del **DANE · SIPSA-Insumos** (Sistema de Información
de Precios y Abastecimiento del Sector Agropecuario, componente de insumos).

| | |
|---|---|
| **Fuente** | [Serie histórica de precios por municipio (Excel, ~64 MB)](https://www.dane.gov.co/files/operaciones/SIPSA/anex-SIPSAInsumos-SeriesHistoricasMun-2021-2026.xlsx), hoja **1.3 · Fertilizantes** |
| **Qué trae** | Precio promedio **mensual** por municipio y producto (ej.: `Urea 46%`, bulto de 50 kg) |
| **Frecuencia** | Mensual. El DANE publica cada mes con **~3 semanas de retraso** (el 20 de octubre salió septiembre) |
| **Qué cargamos** | 10 fertilizantes de bulto de 50 kg ([catalogo.py](agente/catalogo.py)), últimos 2 años, a nivel municipio |

**Cómo actualizar** (una vez al mes, cuando el DANE publique):

```bash
python scripts/actualizar_sipsa.py            # descarga solo si la copia local tiene > 30 días
python scripts/actualizar_sipsa.py --forzar   # descarga sí o sí
```

El script es un pequeño **pipeline ETL** ([actualizar_sipsa.py](scripts/actualizar_sipsa.py)):

1. **Extraer:** descarga el Excel en streaming (con timeout y progreso) a `data/`. Si la descarga
   falla pero hay copia local, sigue con la local y avisa. Una descarga cortada no daña la copia anterior.
2. **Transformar:** lee solo las hojas de `HOJAS_SIPSA` con `openpyxl` (modo `read_only`), deja los
   insumos del catálogo con su presentación, los últimos `ANIOS_HISTORIA` años, pasa `"Enero "` → `1`
   y limpia espacios. Ignora títulos, filas vacías y las notas al pie.
3. **Cargar:** guarda en la tabla `precios_sipsa` de `data/insumos.db` en **una transacción** con
   `executemany`. Un índice único lo hace **idempotente**; si el DANE corrige un precio, se actualiza.

```text
✅ 116,085 filas leídas · 8,947 del catálogo · 8,947 nuevas · 0 actualizadas
📅 Periodos: 2025-01 → 2026-09
```

**Cómo lo usa el agente:** el SIPSA da precios por municipio; el agente habla de departamentos. Por eso
cada mes se **agrega por departamento**: precio ≈ promedio de los municipios, más el rango
(mín–máx) y cuántos municipios reportaron. Las respuestas siempre dicen **de qué mes es el dato**:
*"alrededor de $169.271 (entre $162.667 y $177.333 según el municipio), según el DANE en septiembre de 2026"*.

**Limitaciones (importantes para no engañar al productor):**

- **No son precios de hoy:** el último dato tiene entre 3 y 7 semanas.
- **No todos los departamentos tienen todos los productos cada mes.** Ej.: Boyacá tiene urea solo
  hasta febrero de 2026. Si el dato tiene más de `MESES_DATO_VIGENTE` (3) meses de atraso se marca
  `dato_desactualizado` y el agente ofrece los **departamentos vecinos** con dato reciente.
- Solo 25 departamentos aparecen en el SIPSA (no hay datos de Amazonas, Chocó, La Guajira, Guainía,
  Guaviare, Vaupés, Vichada ni San Andrés) y no todos los municipios.
- El nombre del archivo cambia cada año (`…2021-2026.xlsx` → `…2021-2027.xlsx`): si la descarga
  da 404, actualiza `SIPSA_URL` en el `.env`.

## 🔧 S2 · Herramientas (actualizadas en S3)

El agente tiene **6 herramientas** y **él mismo decide** cuáles invocar (tool calling), usando solo
las que la pregunta necesita. Todas **siempre devuelven un dict**: si algo falla, devuelven
`{"error": "...", "tipo_error": "sin_datos|red|config|validacion"}` en vez de romper el loop.

| Herramienta | Qué hace | Fuente real | Errores que maneja |
|---|---|---|---|
| `consultar_precios(insumo, region, municipio=None)` | Últimos **12 meses**: precio promedio, rango mín–máx, nº de municipios, mes del dato y si está desactualizado | DANE-SIPSA en SQLite | `sin_datos` (dice qué municipios/departamentos sí tienen), `validacion` (región que no existe), `config` (BD sin crear) |
| `analizar_tendencia(insumo, region, municipio=None)` | Pendiente de los **últimos 6 meses** (%/mes, regresión lineal a mano), variación vs. mes anterior y vs. **mismo mes del año pasado**, recomendación `comprar_ya` / `esperar` / `neutral` + `porque` | DANE-SIPSA | `sin_datos` (menos de 2 meses), `config` |
| `consultar_regiones_vecinas(insumo, region)` | Último precio en cada **departamento vecino**, del más barato al más caro (primero los de dato reciente) | DANE-SIPSA + `VECINOS` | `sin_datos` (ningún vecino tiene; sugiere dónde sí), `validacion` |
| `calcular_costo_compra(insumo, region, bultos, municipio=None)` | Total de N bultos al último precio real, con rango | DANE-SIPSA | `validacion` (bultos ≤ 0), `sin_datos`, `config` |
| `consultar_trm()` | TRM actual (dólar oficial), variación de los últimos 7 registros y tendencia | API de datos abiertos [datos.gov.co · 32sa-8pi3](https://www.datos.gov.co/resource/32sa-8pi3.json) | `red`: timeout (10 s, 1 reintento), sin conexión, error HTTP, JSON inesperado |
| `enviar_alerta(mensaje, chat_id=None)` | Envía la recomendación por Telegram | API de bots de Telegram (`sendMessage`) | `config` (falta token/chat o Telegram lo rechaza), `validacion` (vacío o > 1000 caracteres), `red` |

**Regla de la recomendación** (en [herramientas.py](agente/herramientas.py)): con los últimos 6 meses
se calcula la pendiente en COP/mes y se pasa a % del promedio. **≤ -2 %/mes → esperar** (va bajando),
**≥ +2 %/mes → comprar ya** (va subiendo), en medio → **neutral** (sin apuro). El umbral se cambia
con `UMBRAL_PCT_MENSUAL`. El `porque` agrega la comparación con el mismo mes del año anterior.

### 🏗️ Arquitectura

```
 🏭 ETL mensual (python scripts/actualizar_sipsa.py)
 🌐 dane.gov.co ──► EXTRAER ──► data/anex-SIPSAInsumos-…Mun-2021-2026.xlsx (si falla: copia local)
                                  │
                    TRANSFORMAR ◄─┘  hoja 1.3 · catálogo (agente/catalogo.py) · últimos 2 años
                         │           "Enero " → 1 · limpia espacios
                         ▼
                      CARGAR ──► 🗄️ data/insumos.db · tabla precios_sipsa (municipio × mes)
                                          ▲  (transacción + índice único = idempotente)
                                          │
 ─────────────────────────────────────────┼──────────────────────────────────────────────
                          🧑‍🌾 pregunta     │
                               │          │
                               ▼          │
 main.py / app.py ──► agente/agente.py   🔁 loop: pensar → actuar → observar  (máx. 5 vueltas)
                 │        ▲               │
   🧠 Grok (xAI) │        │ resultado JSON (o {"error", "tipo_error"})
   agente/llm.py ▼        │               │
            agente/herramientas.py  ── ESQUEMAS (lo que ve el LLM) + REGISTRO
                 │                        │
   ┌─────────────┴──────┬───────────────┐ │
   ▼                    ▼               ▼ │
 consultar_precios   consultar_trm   enviar_alerta
 analizar_tendencia     │               │ │
 consultar_regiones_    ▼               ▼ │
   vecinas          🌐 datos.gov.co  📲 api.telegram.org
 calcular_costo_compra                    │
   │                                      │
   ▼                                      │
 agente/datos.py ── agrega por departamento (promedio, mín, máx, nº municipios)
   │                └── agente/catalogo.py: "urea" → "Urea 46%", VECINOS
   └──────────────────────────────────────┘

 📝 logs/ejecucion_*.json: cada llamada con nombre, argumentos, éxito/error y duración (ms)
```

### 🛡️ Cómo se comporta ante fallas

| Qué falla | Qué hace el agente |
|---|---|
| No hay datos del insumo/región (o son viejos) | Lo dice claro con el mes del último dato, **no inventa precios** y ofrece el departamento vecino más barato con dato reciente. |
| Falla la descarga del Excel del DANE | El ETL sigue con la copia local y avisa; si no hay copia, explica qué revisar (`SIPSA_URL`). |
| La API de la TRM no responde | Reintenta 1 vez (timeout de 10 s). Si sigue caída, responde igual con precios y tendencia y aclara que no pudo ver el dólar. |
| Telegram sin configurar o rechaza el mensaje | Da la recomendación en consola y explica por qué no llegó el aviso. Los errores nunca muestran el token. |
| El LLM manda argumentos malos o pide una herramienta que no existe | Error `validacion` que vuelve al LLM para que corrija; el loop no se cae. |
| Falla la API de Grok (sin red, 401, 404, 429) | Mensaje claro (ej.: "revisa XAI_API_KEY") en vez de un traceback. |
| Falta la BD | Error `config` que dice exactamente qué correr: `python scripts/actualizar_sipsa.py`. |

### 🎬 Demo para el video

```bash
python main.py --demo
```

Corre en orden: **1)** caso feliz con las 4 herramientas (urea en Santander + aviso por Telegram),
**2)** caso sin datos (glifosato en Nariño), **3)** caída simulada de la TRM (`SIMULAR_FALLA_TRM=1`).
🎬 **Video de la S2:** https://youtu.be/_SfU-sRlvlQ

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

> ⚠️ Los precios de S1 y S2 eran **ficticios**. Desde S3 el agente usa datos reales del DANE;
> `data/precios_ejemplo.csv` sigue siendo ficticio y **solo lo usan las pruebas**.

### Lo que todavía falta (próximas semanas)
- Evaluación propia y costo por tarea (S3, parte 2).
- Pruebas de carga (S4).

## 📁 Estructura

```
agente-insumos/
├── main.py                 # Punto de entrada (CLI / chat)
├── app.py                  # 💬 Interfaz web de chat (Streamlit)
├── agente/
│   ├── config.py           # Lee el .env (claves, modelo, rutas)
│   ├── llm.py              # Cliente de Grok (API compatible con OpenAI)
│   ├── agente.py           # 🔁 El loop: pensar → actuar → observar
│   ├── herramientas.py     # 🔧 6 herramientas + esquemas que ve el LLM
│   ├── datos.py            # 📦 Consultas a la BD SQLite (agrega municipios → departamento)
│   └── catalogo.py         # 📚 Alias de insumos → nombre del DANE, departamentos y VECINOS
├── scripts/actualizar_sipsa.py  # 🏭 ETL: Excel del DANE → data/insumos.db (idempotente)
├── data/
│   ├── precios_ejemplo.csv # Precios FICTICIOS, con la forma del SIPSA (solo para pruebas)
│   ├── anex-SIPSA…xlsx     # (se descarga, no se sube a GitHub)
│   └── insumos.db          # (se genera, no se sube a GitHub)
├── tests/
│   ├── conftest.py         # Excel falso pequeño + BD temporal para cada prueba
│   ├── test_agente.py      # Loop con un LLM falso (no gasta API)
│   ├── test_catalogo.py    # Alias, departamentos y VECINOS (simetría, casos dudosos)
│   ├── test_etl.py         # ETL: meses, filtro de años, idempotencia, descarga simulada
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

python scripts/actualizar_sipsa.py  # 0) descarga los precios del DANE y llena data/insumos.db
pytest -v                   # 1) pruebas sin gastar API ni usar internet
python main.py "¿Cómo está la urea en Santander?"   # 2) agente real
python main.py              # 3) modo chat
python main.py --demo       # 4) los 3 casos del video
streamlit run app.py        # 5) interfaz web de chat (se abre en http://localhost:8501)
```

### 💬 Interfaz web (Streamlit)

`streamlit run app.py` abre un chat en el navegador que usa **el mismo agente** que la consola
(`ejecutar_agente` + `crear_cliente`, sin cambiar su lógica):

- Debajo de cada respuesta, **🔧 Herramientas usadas** muestra el rastro: nombre, argumentos, ✅/❌ y duración en ms.
- Barra lateral: preguntas de ejemplo (caso feliz y caso sin datos), **Simular falla de TRM**
  (activa `SIMULAR_FALLA_TRM`) y **Limpiar chat**.
- Si falta configuración en el `.env`, muestra el error con los pasos para arreglarlo en vez de romperse.
- Cada pregunta se responde por separado: el agente todavía no recuerda los mensajes anteriores.

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
- [ ] **S3:** ~~datos reales (DANE-SIPSA)~~ ✅ · evaluación propia y costo por tarea
- [ ] **S4:** semana de carga (1.000 unidades, 12 h)
