# Abona

**Abone con datos, no con corazonadas.**

Abona es un agente de IA que asesora a pequeños productores de Colombia en la compra de fertilizantes.
Con precios reales del DANE (SIPSA-Insumos) responde cuánto vale un insumo en su departamento o
municipio, si conviene comprar ya o esperar, cuánto le cuesta su compra y dónde está más barato.

**El problema:** el precio del fertilizante define la rentabilidad de la cosecha, y el pequeño productor
compra cuando lo necesita, no cuando conviene. **Quién paga:** cooperativas, almacenes agropecuarios y
gremios.

| | |
|---|---|
| Modelo | Grok (`grok-4.6`) por la pasarela del reto, con tool calling |
| Datos | DANE · SIPSA-Insumos, precios mensuales por municipio (10 fertilizantes, 2025–2026) + TRM de datos.gov.co |
| Evaluación | 43 casos en 9 categorías × 3 repeticiones: 128 de 129 correctos (99,2 %) |
| Carga | Corrida desatendida de más de 12 h con bitácora de cada tarea ([REPORTE_S4.md](REPORTE_S4.md)) |
| Costo | ≈ US$ 0,01 por consulta (cota superior) |

## Avances por semana

| Semana | Entregable | Documento |
|---|---|---|
| S1 | Agente corriendo de principio a fin | [docs/semanas/S1.md](docs/semanas/S1.md) |
| S2 | Herramientas reales, manejo de fallas y video | [docs/semanas/S2.md](docs/semanas/S2.md) |
| S3 | Datos reales, evaluación propia y costo por tarea | [docs/semanas/S3.md](docs/semanas/S3.md) |
| S4 | Semana de carga: 1.000+ tareas, 12 h, bitácora | [docs/semanas/S4.md](docs/semanas/S4.md) · [REPORTE_S4.md](REPORTE_S4.md) |

## Qué hace

- **Precio:** "¿Cuánto vale el bulto de urea en Santander?" → precio promedio del último mes publicado,
  con el rango entre municipios.
- **Comprar ya o esperar:** tendencia de los últimos 6 meses, comparación con el mismo mes del año
  anterior y el dólar como contexto. Responde con una de tres etiquetas: Comprar ya, Esperar o Sin apuro.
- **Costo de una compra:** "¿Cuánto me cuestan 20 bultos de 15-15-15 en Bucaramanga?"
- **Dónde está más barato:** si en la región no hay dato vigente, busca en los departamentos vecinos.
- **Alcance claro:** no da consejo agronómico (dosis, plagas, daños en cultivos); remite a un agrónomo, a
  la UMATA o al ICA.

Siempre dice de qué mes es el dato y nunca inventa cifras: todo número sale de una herramienta.

## Cómo correrlo

```powershell
python -m venv .venv
.venv\Scripts\activate                 # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                   # Linux/Mac: cp .env.example .env
# Llenar en .env: XAI_API_KEY (llave del reto, pk_...) y GROK_MODEL. XAI_BASE_URL ya apunta a la pasarela.

python scripts/actualizar_sipsa.py       # descarga los precios del DANE y crea data/insumos.db
python -m servidor                       # interfaz web de Abona en http://127.0.0.1:8000
```

Otras formas de usarlo:

```powershell
python main.py "¿Cuánto vale la urea en el Meta?"   # una pregunta por consola
python main.py                                      # chat por consola
pytest -v                                           # pruebas, sin internet ni gasto de API
python scripts/evaluar.py                           # evaluación propia con Grok (ver S3)
python scripts/carga.py --prueba 5                  # prueba corta de la corrida de carga (ver S4)
```

**Telegram (opcional, para `enviar_alerta`):** crea un bot con @BotFather (`/newbot`), copia el token en
`TELEGRAM_BOT_TOKEN`, escríbele cualquier mensaje al bot y copia tu `chat.id` desde
`https://api.telegram.org/bot<TOKEN>/getUpdates` en `TELEGRAM_CHAT_ID`.

## Arquitectura

```
 Entradas                         Núcleo                            Fuentes y acciones
 ┌──────────────────────┐   ┌─────────────────────────────┐
 │ web/ + servidor/     │   │ agente/agente.py            │──► agente/llm.py ──► Grok (pasarela del reto)
 │  (FastAPI, Abona)    │──►│  loop: pensar → actuar →    │
 │ main.py (consola)    │   │  observar, máx. 5 vueltas   │
 │ scripts/carga.py     │   │  + tokens, tiempo y costo   │
 │ scripts/evaluar.py   │   │ agente/voz_abona.py (voz)   │
 └──────────────────────┘   │ agente/herramientas.py      │──► agente/datos.py ──► SQLite (data/insumos.db)
                            │  6 herramientas + esquemas  │──► datos.gov.co (TRM)
                            └─────────────────────────────┘──► Telegram (alertas)

 ETL mensual: scripts/actualizar_sipsa.py   Excel del DANE ──► hoja 1.3 ──► catálogo ──► precios_sipsa
```

| Herramienta | Qué hace |
|---|---|
| `consultar_precios` | Últimos 12 meses de un insumo en un departamento o municipio: promedio, rango y mes del dato |
| `analizar_tendencia` | Pendiente de 6 meses, comparación anual y recomendación con su porqué |
| `calcular_costo_compra` | Total de N bultos al último precio real |
| `consultar_regiones_vecinas` | Último precio en los departamentos vecinos, del más barato al más caro |
| `consultar_trm` | Dólar oficial (TRM) y su variación de la semana |
| `enviar_alerta` | Envía la recomendación por Telegram, solo si el usuario lo pide |

Todas devuelven un dict y nunca rompen el loop: si algo falla, el agente recibe
`{"error", "tipo_error"}`, lo explica y sigue con lo que sí tiene.

## Limitaciones conocidas

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
  una **cota superior** (ver [Costo por tarea](docs/semanas/S3.md#costo-por-tarea)).

## Estructura

```
agente-insumos/
├── agente/            loop, cliente de Grok, herramientas, datos, catálogo y voz de Abona
├── servidor/          API web (FastAPI): /api/preguntar, /api/estado, /api/carga
├── web/               interfaz de Abona (HTML, CSS y JS sin librerías)
├── scripts/           ETL del DANE, evaluación, cola y ejecutor de carga, supervisor y reporte S4
├── evals/casos.json   43 casos de evaluación
├── data/              cola de la S4 y precios de ejemplo (el Excel y la BD se generan)
├── bitacora/          bitácora de la corrida de carga de la S4
├── docs/              reporte de evaluación y documentos por semana (docs/semanas/)
├── tests/             pruebas sin internet (LLM falso, Excel falso, APIs simuladas)
├── main.py, app.py    consola e interfaz Streamlit de la S2
└── REPORTE_S4.md      resultados de la semana de carga
```
