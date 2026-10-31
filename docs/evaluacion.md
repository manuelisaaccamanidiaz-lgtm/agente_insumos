# 🧪 Evaluación propia del agente

- **Fecha:** 2026-10-31 17:06 · **Modelo:** `grok-4.6`
- **Casos:** 43 · **Repeticiones:** 3 · **Corridas:** 129
- **Aprobado total:** 99.2 % (128/129)
- **Consistencia:** 97.7 % de los casos dieron el mismo resultado en todas sus repeticiones
- 💲 Costo recalculado el 2026-10-31 17:21 con los tokens guardados y $1,59 (entrada) / $1,59 (salida) USD por millón de tokens
- **Costo total de la corrida:** $1,3205 USD

## Por categoría

| Categoría | Aprobado | % |
|---|---|---|
| precio_directo | 15/15 | 100.0 % |
| tendencia | 12/12 | 100.0 % |
| costo | 12/12 | 100.0 % |
| municipio | 18/18 | 100.0 % |
| sin_datos_vecinos | 17/18 | 94.4 % |
| alias | 18/18 | 100.0 % |
| fuera_de_alcance | 18/18 | 100.0 % |
| fallas | 9/9 | 100.0 % |
| alerta | 9/9 | 100.0 % |

## Costo por tarea

| Promedio por tarea | Valor |
|---|---|
| Llamadas a Grok | 2,1 |
| Tokens de entrada | 6.284 |
| Tokens de salida | 154 |
| Tokens totales | 6.438 |
| Duración | 7,3 s |
| **Costo USD** | **$0,0102** |
| **Costo COP** | **$33 COP** |
| Caso más caro | `at01` ($0,0176 USD) |
| Caso más lento | `fl01` (18,6 s) |
| TRM usada | $3.182,99 (2026-10-31) |

## Por caso

| Caso | Categoría | Resultado | Llamadas | Tokens entrada | Tokens salida | Duración | USD | Motivo |
|---|---|---|---|---|---|---|---|---|
| pd01 | precio_directo | ✅ 3/3 | 2,0 | 6.077 | 78 | 4,1 s | $0,0098 | — |
| pd02 | precio_directo | ✅ 3/3 | 2,0 | 6.101 | 93 | 4,8 s | $0,0098 | — |
| pd03 | precio_directo | ✅ 3/3 | 2,0 | 6.238 | 108 | 6,0 s | $0,0101 | — |
| pd04 | precio_directo | ✅ 3/3 | 2,0 | 6.079 | 80 | 5,3 s | $0,0098 | — |
| pd05 | precio_directo | ✅ 3/3 | 2,0 | 6.116 | 88 | 4,5 s | $0,0099 | — |
| td01 | tendencia | ✅ 3/3 | 2,0 | 6.020 | 231 | 9,0 s | $0,0099 | — |
| td02 | tendencia | ✅ 3/3 | 2,0 | 6.052 | 267 | 11,2 s | $0,0100 | — |
| td03 | tendencia | ✅ 3/3 | 2,0 | 6.010 | 228 | 9,0 s | $0,0099 | — |
| td04 | tendencia | ✅ 3/3 | 2,0 | 6.045 | 213 | 8,4 s | $0,0100 | — |
| co01 | costo | ✅ 3/3 | 2,0 | 5.589 | 106 | 6,8 s | $0,0091 | — |
| co02 | costo | ✅ 3/3 | 2,0 | 5.572 | 132 | 5,1 s | $0,0091 | — |
| co03 | costo | ✅ 3/3 | 2,0 | 5.922 | 118 | 7,3 s | $0,0096 | — |
| co04 | costo | ✅ 3/3 | 2,0 | 5.606 | 104 | 6,3 s | $0,0091 | — |
| mu01 | municipio | ✅ 3/3 | 2,0 | 6.158 | 97 | 4,7 s | $0,0099 | — |
| mu02 | municipio | ✅ 3/3 | 2,0 | 6.004 | 83 | 4,4 s | $0,0097 | — |
| mu03 | municipio | ✅ 3/3 | 2,0 | 6.090 | 119 | 5,0 s | $0,0099 | — |
| mu04 | municipio | ✅ 3/3 | 2,0 | 6.099 | 81 | 4,9 s | $0,0098 | — |
| mu05 | municipio | ✅ 3/3 | 2,0 | 6.008 | 73 | 5,0 s | $0,0097 | — |
| mu06 | municipio | ✅ 3/3 | 3,0 | 10.541 | 287 | 13,3 s | $0,0172 | — |
| sv01 | sin_datos_vecinos | ✅ 3/3 | 3,0 | 8.962 | 210 | 5,1 s | $0,0146 | — |
| sv02 | sin_datos_vecinos | ✅ 3/3 | 3,0 | 8.965 | 223 | 7,9 s | $0,0146 | — |
| sv03 | sin_datos_vecinos | ✅ 3/3 | 3,0 | 8.934 | 240 | 7,3 s | $0,0146 | — |
| sv04 | sin_datos_vecinos | ❌ 2/3 | 3,0 | 9.778 | 174 | 10,3 s | $0,0158 | no dice ninguno de: desactualiz / antigu / viej / no es reciente / … |
| sv05 | sin_datos_vecinos | ✅ 3/3 | 2,0 | 5.504 | 142 | 5,8 s | $0,0090 | — |
| sv06 | sin_datos_vecinos | ✅ 3/3 | 3,0 | 8.807 | 210 | 11,4 s | $0,0143 | — |
| al01 | alias | ✅ 3/3 | 2,0 | 6.126 | 125 | 5,3 s | $0,0099 | — |
| al02 | alias | ✅ 3/3 | 2,0 | 6.336 | 104 | 5,9 s | $0,0102 | — |
| al03 | alias | ✅ 3/3 | 2,0 | 6.176 | 121 | 6,6 s | $0,0100 | — |
| al04 | alias | ✅ 3/3 | 2,0 | 6.109 | 108 | 5,0 s | $0,0099 | — |
| al05 | alias | ✅ 3/3 | 2,0 | 6.287 | 80 | 5,5 s | $0,0101 | — |
| al06 | alias | ✅ 3/3 | 2,0 | 6.664 | 109 | 6,8 s | $0,0108 | — |
| fa01 | fuera_de_alcance | ✅ 3/3 | 1,0 | 2.643 | 145 | 10,1 s | $0,0044 | — |
| fa02 | fuera_de_alcance | ✅ 3/3 | 1,0 | 2.634 | 127 | 7,5 s | $0,0044 | — |
| fa03 | fuera_de_alcance | ✅ 3/3 | 1,0 | 2.636 | 160 | 10,6 s | $0,0044 | — |
| fa04 | fuera_de_alcance | ✅ 3/3 | 1,0 | 2.624 | 124 | 6,3 s | $0,0044 | — |
| fa05 | fuera_de_alcance | ✅ 3/3 | 1,0 | 2.622 | 121 | 7,7 s | $0,0044 | — |
| fa06 | fuera_de_alcance | ✅ 3/3 | 1,0 | 2.624 | 115 | 7,0 s | $0,0044 | — |
| fl01 | fallas | ✅ 3/3 | 2,0 | 5.857 | 236 | 18,6 s | $0,0097 | — |
| fl02 | fallas | ✅ 3/3 | 2,0 | 5.789 | 227 | 10,1 s | $0,0096 | — |
| fl03 | fallas | ✅ 3/3 | 2,0 | 5.927 | 203 | 14,5 s | $0,0097 | — |
| at01 | alerta | ✅ 3/3 | 3,0 | 10.900 | 174 | 4,1 s | $0,0176 | — |
| at02 | alerta | ✅ 3/3 | 3,0 | 9.741 | 332 | 5,6 s | $0,0160 | — |
| at03 | alerta | ✅ 3/3 | 3,0 | 9.238 | 222 | 5,0 s | $0,0150 | — |

## Detalle de los fallos

### sv04 · sin_datos_vecinos

**Pregunta:** ¿Cuánto vale la urea en Boyacá?

**Herramientas:** consultar_precios, consultar_regiones_vecinas

**Motivos:**
- no dice ninguno de: desactualiz / antigu / viej / no es reciente / …

> Según el DANE, el último dato de urea en Boyacá es de **febrero de 2026** (ya va 7 meses de retraso; no es el precio de hoy). En Boyacá el bulto de 50 kg estaba **alrededor de $135.000** (solo hay un municipio con dato, y min y max coinciden). La alternativa vecina **más barata con dato reciente** es **Santander**, según el DANE en **septiembre de 2026**: alrededor de **$169.271** (entre $162.667 y $177.333, según el municipio).

