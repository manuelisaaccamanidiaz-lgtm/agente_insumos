# 🎬 Guion del video S2 (~2 minutos)

**Antes de grabar**
- `python scripts/cargar_bd.py` y `pytest -v` en verde.
- `.env` con Grok **y** Telegram configurados (para que el caso 1 muestre las 4 herramientas en ✅).
- Telegram abierto en el celular o en una ventana al lado de la terminal.
- Terminal con letra grande; `README.md` abierto en la sección de arquitectura.

---

## 1. El problema · 0:00 – 0:15 (15 s)

**En pantalla:** título del README.

> "El fertilizante define si la cosecha da ganancia o no, y el pequeño productor compra
> cuando lo necesita, no cuando conviene. Este agente sigue los precios por región y le
> dice al campesino si comprar ya o esperar, y por qué."

## 2. La arquitectura · 0:15 – 0:35 (20 s)

**En pantalla:** diagrama ASCII del README (sección "Arquitectura").

> "Grok es el cerebro y el loop decide qué hacer. Tiene cuatro herramientas reales: dos
> consultan una base SQLite de precios, una trae el dólar oficial de datos.gov.co, porque
> los fertilizantes son importados, y otra envía la alerta por Telegram. Si una falla,
> devuelve un error claro y el agente sigue: nunca inventa datos."

## 3. Demo · 0:35 – 1:35 (60 s)

**En pantalla:** `python main.py --demo`

### Caso 1 · Caso feliz (≈ 25 s)
> "Le pregunto si me conviene comprar urea en Santander y que me avise por Telegram."

- Señalar las 4 líneas `🔧 ... ✅ ... ms`: precios, tendencia, TRM y alerta.
- Leer la recomendación ("esperar") y el porqué en lenguaje sencillo.
- Mostrar el mensaje que llegó a Telegram.
- Remarcar: "aclara que los precios son de ejemplo".

### Caso 2 · Sin datos (≈ 15 s)
> "¿Y el glifosato en Nariño? No tenemos ese dato."

- Señalar `❌ sin_datos`.
- "No inventa un precio: dice que no hay y ofrece los insumos que sí tiene."

### Caso 3 · Se cae una API (≈ 20 s)
> "Ahora tumbo a propósito la API del dólar con `SIMULAR_FALLA_TRM=1`."

- Señalar `🔧 consultar_trm({}) ❌ red: ...`.
- "El agente reintentó, explicó que no pudo ver el dólar y aun así dio la recomendación
  con los precios y la tendencia que sí tenía."

## 4. Cierre · 1:35 – 1:50 (15 s)

**En pantalla:** `pytest -v` en verde, o un `logs/ejecucion_*.json` abierto.

> "Cada llamada queda registrada con argumentos, resultado y milisegundos, y hay pruebas
> automáticas sin internet para cada herramienta. La próxima semana: precios reales del
> DANE/SIPSA."
