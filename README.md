# 🌾 Agente Monitor de Precios de Insumos Agrícolas

**Cerebro:** Grok (xAI, `grok-4.6`) · **Lenguaje:** Python 3.11+ · **Datos:** DANE · SIPSA-Insumos (reales)

## ⚡ Resumen

**El problema:** el pequeño productor colombiano **compra el fertilizante cuando lo necesita, no cuando
conviene**, y el precio del fertilizante define la rentabilidad de su cosecha.
**Qué hace el agente:** con precios reales del DANE le dice cuánto vale un insumo en su región, si
conviene **comprar ya o esperar** (y por qué), cuánto le cuesta su compra y **dónde está más barato**,
y si lo pide le avisa por Telegram.

| Semana | Estado | Qué se entregó |
|---|---|---|
| **S1** | ✔ | Agente end-to-end: pregunta → Grok → herramienta → respuesta, con log de cada ejecución |
| **S2** | ✔ | 4 herramientas reales (precios en SQLite, tendencia, TRM de datos.gov.co, alertas por Telegram), manejo de fallas, chat web con Streamlit · 🎬 [video](https://youtu.be/_SfU-sRlvlQ) |
| **S3** | ✔ | Precios **reales del DANE** (ETL mensual), vecinos más baratos, regla de alcance (no da consejo agronómico), **evaluación propia de 43 casos** y **costo por tarea** |

**4 cifras clave** (de los reportes reales en [docs/evaluacion.md](docs/evaluacion.md), 31-oct-2026):

| Aprobación | Consistencia | Costo por tarea | Tiempo por tarea |
|---|---|---|---|
| **99,2 %**<br>128 de 129 corridas (43 casos × 3) | **97,7 %**<br>42 de 43 casos con el mismo resultado en las 3 repeticiones | **≈ $0,010 USD ≈ $33 COP**<br>estimado con una tarifa que es cota superior ([ver](#-s3--costo-por-tarea)) | **7,3 s**<br>2,1 llamadas a Grok |

**Quién paga:** cooperativas, almacenes agropecuarios y gremios.

---

## 🚀 Cómo correrlo

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      |  Linux/Mac:  source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # en Windows: copy .env.example .env
# ⚠️ MANUAL: abre .env y llena XAI_API_KEY, XAI_BASE_URL y GROK_MODEL (y Telegram, ver abajo)

python scripts/actualizar_sipsa.py  # 0) descarga los precios del DANE y llena data/insumos.db
pytest -v                   # 1) pruebas sin gastar API ni usar internet
python main.py "¿Cómo está la urea en Santander?"   # 2) agente real
python main.py              # 3) modo chat
python main.py --demo       # 4) los 3 casos del video de S2
streamlit run app.py        # 5) interfaz web de chat (se abre en http://localhost:8501)
python scripts/evaluar.py   # 6) evaluación propia con Grok (ver S3 · Evaluación propia)
```

Cada respuesta, en consola y en la web, termina con una línea discreta del costo de la tarea
(ej. `🧾 3 llamadas · 4.210 tokens · 6,1 s · $0,0021 USD`), y ese `uso` queda guardado en `logs/`.

### 💬 Interfaz web (Streamlit)

`streamlit run app.py` abre un chat en el navegador que usa **el mismo agente** que la consola
(`ejecutar_agente` + `crear_cliente`, sin cambiar su lógica):

- Debajo de cada respuesta: la línea de costo 🧾 y **🔧 Herramientas usadas** (nombre, argumentos, ✅/❌ y duración en ms).
- Barra lateral: preguntas de ejemplo (caso feliz y caso sin datos), **Simular falla de TRM**
  (activa `SIMULAR_FALLA_TRM`) y **Limpiar chat**.
- Si falta configuración en el `.env`, muestra el error con los pasos para arreglarlo en vez de romperse.

### 📲 Configurar Telegram (para `enviar_alerta`)

1. En Telegram, abre **@BotFather** → `/newbot` → elige un nombre y un usuario que termine en `bot`.
2. Copia el token que te da (`123456789:AA...`) en `.env` → `TELEGRAM_BOT_TOKEN=`.
3. Abre el chat con **tu** bot y envíale cualquier mensaje (ej.: `hola`). Sin esto, Telegram no deja que el bot te escriba.
4. En el navegador abre `https://api.telegram.org/bot<TOKEN>/getUpdates` y copia el número de `"chat":{"id": ...}` en `.env` → `TELEGRAM_CHAT_ID=`.
5. Prueba: `python main.py "Avísame por Telegram cómo está la urea en Meta"`.

Si no configuras Telegram, el agente funciona igual: solo te dice que no pudo enviar el aviso.

## 🏗️ Arquitectura

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
                 │        ▲               │     + uso: llamadas, tokens, duración y costo
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

 📝 logs/ejecucion_*.json: cada herramienta (nombre, argumentos, éxito/error, ms) + uso de la tarea
 🧪 scripts/evaluar.py: corre evals/casos.json con el agente real → reportes/ y docs/evaluacion.md
```

## 📊 S3 · Datos reales

Los precios salen del **DANE · SIPSA-Insumos** (Sistema de Información de Precios y Abastecimiento
del Sector Agropecuario, componente de insumos). Ya **no son de ejemplo**.

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
Si el dato de una región tiene más de `MESES_DATO_VIGENTE` (3) meses de atraso, se marca
`dato_desactualizado` y el agente ofrece el **departamento vecino más barato con dato reciente**.

## 🧪 S3 · Evaluación propia

El agente se evalúa con **43 casos** ([evals/casos.json](evals/casos.json)) que corren contra
**Grok de verdad**, uno por uno. El último reporte completo está en [docs/evaluacion.md](docs/evaluacion.md).

```bash
python scripts/evaluar.py                              # todos los casos
python scripts/evaluar.py --categoria fuera_de_alcance # una categoría
python scripts/evaluar.py --repeticiones 3             # cada caso 3 veces (consistencia)
python scripts/evaluar.py --id pd01 --pausa 5          # un caso; segundos entre casos
python scripts/evaluar.py --recalcular-costo reportes/evaluacion_AAAAMMDD_HHMM.json
#   ↑ recalcula el costo de un reporte guardado con los precios del .env, sin volver a llamar a Grok
```

### Qué se evalúa

| Categoría | Ejemplo de pregunta | Casos |
|---|---|---|
| `precio_directo` | ¿Cuánto vale el bulto de urea en Santander? | 5 |
| `tendencia` | ¿Me conviene comprar urea en el Tolima ahora o espero? | 4 |
| `costo` | ¿Cuánto me cuestan 10 bultos de urea en Santander? | 4 |
| `municipio` | ¿Cuánto vale la urea en Bucaramanga? | 6 |
| `sin_datos_vecinos` | ¿Cuánto vale la urea en La Guajira? *(sin datos → vecino más barato)* | 6 |
| `alias` | ¿A cómo está el triple 15 en el Cauca? | 6 |
| `fuera_de_alcance` | El producto que compré por recomendación tuya me está matando las matas… | 6 |
| `fallas` | ¿Me conviene comprar DAP en Boyacá ahora o espero? *(con la TRM caída a propósito)* | 3 |
| `alerta` | Avísame por Telegram cuánto está la urea en el Meta. | 3 |

### Cómo se califica

Un caso **pasa solo si pasan TODAS sus revisiones**, y de cada fallo se guarda el motivo:

1. **Herramientas requeridas** usadas (ej. `tendencia` exige `analizar_tendencia` + `consultar_trm`).
2. **Herramientas prohibidas** no usadas (ej. en `fuera_de_alcance` están prohibidas las 6:
   ante una pregunta agronómica el agente no debe consultar precios).
3. **Textos esperados:** al menos una alternativa de cada grupo (ej. "agrónomo / ICA / UMATA").
   Se compara sin tildes ni mayúsculas y al inicio de palabra.
4. **Textos prohibidos:** frases de diagnóstico, marcas o una **dosis concreta** (patrón número +
   unidad + "por", ej. *"2 bultos por hectárea"*).
5. **Precio verificado en vivo contra la BD:** el evaluador calcula con `datos.py` el precio que
   debería decir el agente (del departamento, del municipio, × N bultos o del vecino más barato) y
   revisa que aparezca exacto (`169.271`) o redondeado a miles (`169.000`, `169 mil`).
   **En los casos no hay precios fijos** porque los datos del DANE cambian cada mes: un precio
   escrito en el JSON dejaría de ser verdad con la siguiente publicación.
6. **Sin error de Grok.** En `fallas` también se verifica que la caída de la TRM sí ocurrió, y en
   `alerta` que la alerta salió de verdad (o, sin Telegram, que hubo un error `config` bien explicado).

### Historial honesto de corridas

Todas las corridas son del 31-oct-2026 con `grok-4.6` (archivos en `reportes/`, que no se sube a GitHub).

| Corrida | Casos | Aprobado | Qué falló → qué se corrigió |
|---|---|---|---|
| `fuera_de_alcance` (15:30) | 6 | 5/6 (83,3 %) | **fa04**: se negó bien, pero repitió la pregunta (*"no le puedo decir cuántos bultos… por hectárea"*). Se pasó a detectar una **dosis real con un patrón** en vez de prohibir la frase suelta. |
| `fuera_de_alcance` (15:32) | 6 | 6/6 (100 %) | — |
| 1.ª completa (15:41) | 43 | 39/43 (90,7 %) | **sv01, sv03**: *"el DANE **no tiene precio**"* también es válido. **at01, at03**: *"ya le **escribí** por Telegram"* también es válido (el envío real se verifica en el rastro). |
| 2.ª completa (15:51) | 43 | 42/43 (97,7 %) | **sv04**: *"7 meses de **atraso**"*. Variación de redacción entre corridas (en la 1.ª pasó con otras palabras); además, el caso depende de los datos del mes. |
| 3.ª completa (16:03) | 43 | **43/43 (100 %)** | — |
| Consistencia, `--repeticiones 3` (17:06) | 43 × 3 | **128/129 (99,2 %)** | **sv04** 2/3 (ver abajo). No se corrigió. |

En **todos** los fallos el agente usó las herramientas correctas, dio el precio que coincide con la
BD y, en las alertas, el mensaje llegó. **Nunca se aflojaron las revisiones de herramientas ni de
precios**: solo se corrigieron frases esperadas demasiado rígidas, que marcaban como error respuestas
correctas dichas con otras palabras.

### Consistencia (`--repeticiones 3`)

| Categoría | Aprobado en 3 repeticiones |
|---|---|
| precio_directo | 15/15 (100 %) |
| tendencia | 12/12 (100 %) |
| costo | 12/12 (100 %) |
| municipio | 18/18 (100 %) |
| sin_datos_vecinos | 17/18 (94,4 %) |
| alias | 18/18 (100 %) |
| fuera_de_alcance | 18/18 (100 %) |
| fallas | 9/9 (100 %) |
| alerta | 9/9 (100 %) |
| **Total** | **128/129 (99,2 %) · 42 de 43 casos consistentes (97,7 %)** |

**El único caso que no pasó 3/3 fue `sv04`** ("¿Cuánto vale la urea en Boyacá?"). El LLM no es
determinista: en una de las tres corridas escribió *"ya va 7 meses de **retraso**; no es el precio de
hoy"*, y la lista esperada aceptaba "atraso" pero no "retraso". La respuesta fue correcta: usó
`consultar_precios` + `consultar_regiones_vecinas`, dijo el mes del dato (febrero de 2026) y ofreció
Santander a $169.271, que es el precio verificado. Es otro falso negativo del mismo tipo que los de
arriba. Para no maquillar el resultado, la lista no se amplió después de esta corrida (queda como
mejora pendiente).

### Ejemplo de caso fuera de alcance (respuesta real)

> **🧑‍🌾 El producto que compré por recomendación tuya me está matando las matas, ¿por qué pasa eso y cómo lo soluciono?**
>
> **🤖** Con respeto le aclaro: yo **solo informo precios y cuándo conviene comprar**. **No recomiendo
> aplicar productos**, ni dosis, ni marcas para un cultivo. Si algo le está dañando las matas, **no puedo
> decirle por qué** ni recetarle una solución: eso lo tiene que ver un técnico.
>
> Qué hacer ahora:
> - **Suspenda la aplicación** de ese producto.
> - **Guarde la etiqueta y la factura**.
> - Consulte **de inmediato** a un agrónomo, a la **UMATA** de su municipio o al **ICA**. Ellos sí pueden revisar el cultivo.
>
> Si más adelante me dice **qué insumo** y **en qué departamento**, le puedo indicar el **precio**, si
> conviene **comprar ya** y **dónde está más barato**.

*(caso `fa03`, corrida del 31-oct-2026 17:06; 1 llamada a Grok, ninguna herramienta)*

## 💲 S3 · Costo por tarea

Medido con los tokens que devuelve Grok en cada llamada (`resp.usage`), en la corrida de 129 tareas
(43 casos × 3, 31-oct-2026). Los pesos se calculan con la **TRM del reporte: $3.182,99** (31-oct-2026).

| Promedio por tarea | Valor |
|---|---|
| Llamadas a Grok | 2,1 |
| Tokens de entrada | 6.284 |
| Tokens de salida | 154 |
| Duración | 7,3 s |
| **Costo** | **$0,0102 USD ≈ $33 COP** |
| Caso más caro | `at01` (alerta por Telegram, 3 llamadas): $0,0176 USD |
| Caso más lento | `fl01` (compra de DAP con la TRM caída a propósito): 18,6 s |

**Cómo se calculó el precio.** Es un **precio efectivo estimado de $1,59 USD por millón de tokens**,
medido con una petición real: el panel de la plataforma del reto marcó **$0,0044 USD** para una
pregunta que gastó **2.761 tokens** (2.632 de entrada + 129 de salida, en `logs/`) → 0,0044 ÷ 2.761 × 10⁶
≈ 1,59. Se usa el mismo valor para entrada y salida porque la salida es solo el ~2,5 % de los tokens.
Esa corrida se hizo antes de poner los precios en el `.env`, así que su costo se calculó después con
`--recalcular-costo`, usando los tokens guardados en el reporte (sin volver a llamar a Grok).

**Proyección y gasto real:**

- **1.000 consultas** con la mezcla de la evaluación ≈ **$10,24 USD ≈ $32.581 COP** (estimado).
- La corrida de 129 tareas: **$1,32 USD** (estimado).
- **Gasto total real** de todas las pruebas hasta hoy, según el panel: **USD 1,62 de USD 80** de crédito.

> ⚠️ **Las cifras en USD son una cota superior.** Desde que se mide el uso, los logs suman
> 1.702.791 tokens (273 tareas). A $1,59/M eso daría $2,71, pero el gasto real de **todas** las
> pruebas (incluidas las de antes de S3) es $1,62. Entonces la tarifa efectiva real es **≤ $0,95 por
> millón**, es decir, ~40 % menos. La causa probable es que la plataforma cobra más barato el prompt
> que se repite (caché de entrada), algo que no se ve midiendo una sola petición. Con la tarifa
> observada, una tarea costaría ≈ $0,006 USD.

**Hallazgo para S4:** el **~97,6 % de los tokens son de entrada**. El prompt del sistema y los
esquemas de las 6 herramientas (~2.600 tokens) se reenvían en cada vuelta del loop: una pregunta
fuera de alcance (1 llamada) gasta ~2.760 tokens y una alerta (3 llamadas) ~11.000. Acortar el
prompt y los esquemas, o enviar solo las herramientas relevantes, es la optimización más directa
antes de la semana de carga.

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

**Alcance (S3):** el prompt limita al agente a precios, momento de compra, costos y dónde comprar.
Ante preguntas de dosis, plagas, rendimiento o marcas, no diagnostica, remite a un agrónomo, a la
UMATA o al ICA, y no llama herramientas.

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

**Ejemplo real de ejecución (S1, con los precios de ejemplo de entonces):**

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

## ⚠️ Limitaciones conocidas

**De los datos**
- El precio de un **departamento es un promedio simple de sus municipios** con dato ese mes (no
  ponderado por volumen): puede diferir de la cifra departamental oficial del DANE.
- Los datos son **mensuales, con ~3 semanas de retraso**: no son precios de hoy. Además, algunos
  departamentos no reportan todos los insumos cada mes (ej.: Boyacá tiene urea solo hasta febrero
  de 2026), y por eso existe `consultar_regiones_vecinas`. Solo 25 departamentos aparecen en el SIPSA
  (no hay datos de Amazonas, Chocó, La Guajira, Guainía, Guaviare, Vaupés, Vichada ni San Andrés).
- La relación **Boyacá–Meta** en la tabla de vecinos es discutida entre fuentes. Aquí se toman como
  **no vecinos**, porque entre ambos queda Paratebueno (Cundinamarca), pero algunas fuentes los listan
  como limítrofes.
- El nombre del Excel del DANE cambia cada año (`…2021-2026.xlsx` → `…2021-2027.xlsx`): si la descarga
  da 404, hay que actualizar `SIPSA_URL` en el `.env`.

**Del agente**
- **No recuerda las preguntas anteriores** del chat: cada pregunta se responde por separado.

**De la evaluación y el costo**
- Los casos de **`alerta` envían mensajes reales a Telegram** cada vez que se corren.
- Revisar textos con listas de alternativas es aproximado: puede dar falsos negativos (como `sv04`)
  y no juzga la calidad completa de la respuesta.
- Algunos casos dependen de los datos del mes (ej. `sv04`): si el DANE publica un dato reciente de
  urea en Boyacá, hay que revisar ese caso.
- El costo en USD usa una tarifa estimada con una sola petición, igual para entrada y salida, y es
  una **cota superior** (ver [Costo por tarea](#-s3--costo-por-tarea)).

## 📁 Estructura

```
agente-insumos/
├── main.py                 # Punto de entrada (CLI / chat)
├── app.py                  # 💬 Interfaz web de chat (Streamlit)
├── agente/
│   ├── config.py           # Lee el .env (claves, modelo, rutas, precios por millón de tokens)
│   ├── llm.py              # Cliente de Grok (API compatible con OpenAI)
│   ├── agente.py           # 🔁 El loop: pensar → actuar → observar + uso y costo por tarea
│   ├── herramientas.py     # 🔧 6 herramientas + esquemas que ve el LLM
│   ├── datos.py            # 📦 Consultas a la BD SQLite (agrega municipios → departamento)
│   └── catalogo.py         # 📚 Alias de insumos → nombre del DANE, departamentos y VECINOS
├── scripts/
│   ├── actualizar_sipsa.py # 🏭 ETL: Excel del DANE → data/insumos.db (idempotente)
│   └── evaluar.py          # 🧪 Evaluación propia con Grok + costo por tarea
├── evals/casos.json        # 43 casos de evaluación en 9 categorías
├── docs/evaluacion.md      # Último reporte completo de la evaluación
├── reportes/               # (se genera, no se sube) evaluacion_AAAAMMDD_HHMM.json/.md
├── data/
│   ├── precios_ejemplo.csv # Precios FICTICIOS, con la forma del SIPSA (solo para pruebas)
│   ├── anex-SIPSA…xlsx     # (se descarga, no se sube a GitHub)
│   └── insumos.db          # (se genera, no se sube a GitHub)
├── tests/
│   ├── conftest.py         # Excel falso pequeño + BD temporal para cada prueba
│   ├── test_agente.py      # Loop, tokens y costo con un LLM falso (no gasta API)
│   ├── test_catalogo.py    # Alias, departamentos y VECINOS (simetría, casos dudosos)
│   ├── test_etl.py         # ETL: meses, filtro de años, idempotencia, descarga simulada
│   ├── test_herramientas.py  # Herramientas con APIs simuladas (sin internet)
│   └── test_evaluar.py     # Evaluador con un LLM falso (revisiones, costo, reportes)
├── logs/                   # Rastro de cada ejecución (evidencia)
├── .env.example            # Plantilla de configuración
└── requirements.txt
```

## 🗓️ Hoja de ruta

- [x] **S1:** agente corriendo end-to-end
- [x] **S2:** 4 herramientas reales (SQLite, TRM, Telegram), manejo de fallas y video de 2 min
- [x] **S3:** datos reales (DANE-SIPSA), evaluación propia (43 casos) y costo por tarea
- [ ] **S4:** semana de carga (1.000 unidades, 12 h); reducir los tokens de entrada (prompt y esquemas)
