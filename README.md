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

## ✅ Estado: Semana 1, agente corriendo end-to-end

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

> ⚠️ Los precios en `data/precios_ejemplo.csv` son **ficticios**. Los datos reales llegan en la Semana 3.

### Lo que todavía falta (próximas semanas)
- Proyección de la ventana de compra y recomendación "comprar / esperar".
- 3 herramientas (S2), datos reales del DANE/SIPSA y distribuidores (S3), pruebas de carga (S4).

## 📁 Estructura

```
agente-insumos/
├── main.py                 # Punto de entrada (CLI / chat)
├── agente/
│   ├── config.py           # Lee el .env (claves, modelo, rutas)
│   ├── llm.py              # Cliente de Grok (API compatible con OpenAI)
│   ├── agente.py           # 🔁 El loop: pensar → actuar → observar
│   ├── herramientas.py     # 🔧 Funciones + esquemas que ve el LLM
│   └── datos.py            # 📦 Lectura y filtrado de precios
├── data/precios_ejemplo.csv
├── tests/test_agente.py    # Pruebas con un LLM falso (no gastan API)
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
# ⚠️ MANUAL: abre .env y llena XAI_API_KEY y GROK_MODEL

pytest -v                   # 1) pruebas sin gastar API
python main.py "¿Cómo está la urea en Santander?"   # 2) agente real
python main.py              # 3) modo chat
```

## 🗓️ Hoja de ruta

- [x] **S1:** agente corriendo end-to-end
- [ ] **S2:** 3 herramientas y video de 2 min
- [ ] **S3:** datos reales, evaluación propia y costo por tarea
- [ ] **S4:** semana de carga (1.000 unidades, 12 h)
