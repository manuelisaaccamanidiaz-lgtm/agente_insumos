# REPORTE S4 · Semana de carga de Abona

> **Corrida en curso.** Corte del 08/11/2026 00:58 (hora de Colombia): 1.267 de 1.400 tareas. El reporte se regenera al terminar.

## Resumen

| Indicador | Valor |
|---|---|
| Unidades de trabajo completadas | **1.267** de 1.400 en cola |
| Tasa de éxito | **100,0 %** (1.267 de 1.267) |
| Duración desatendida | **11,63 h** (07/11 13:20 → 08/11 00:58, hora de Colombia) |
| Tramo continuo más largo | 11,63 h |
| Costo total | **US$ 12,21** (≈ $39.527 COP) |
| Costo por tarea | **US$ 0,0096** (≈ $31 COP) |
| Llamadas a Grok | 2.597 (2,05 por tarea) |
| Tokens | 7.677.936 (7.490.409 de entrada · 187.527 de salida) |
| Duración por tarea | mediana 9,8 s · p95 21,8 s |
| Modelo y ruta | `grok-4.6` por la pasarela del reto (llave del reto) |

El costo usa un precio efectivo de US$ 1,59 por millón de tokens medido en el panel de la plataforma; es una **cota superior** (la pasarela cobra más barato el prompt repetido). Pesos con la TRM de hoy: $3.237,83.

## Cómo corrió sin intervención

- **Cola:** 1.400 preguntas únicas generadas con `scripts/generar_cola.py` a partir de la BD real del DANE.
- **Ejecutor:** `scripts/carga.py` toma una tarea cada 33 s y escribe la bitácora después de cada una (reanudable).
- **Supervisor:** `scripts/carga_supervisor.ps1` relanza el proceso si se cae.
- **Recuperación:** reintentos a Grok con espera de 5, 15 y 45 s; pausa de 5 min tras 10 fallos seguidos.

| Evento | Veces |
|---|---|
| Arranques del proceso | 1 |
| Reinicios automáticos del supervisor | 0 |
| Reintentos a Grok | 0 (en 0 tareas) |
| Pausas por fallos seguidos | 0 |
| Excepciones atrapadas | 0 |

Errores de herramientas que el agente manejó sin fallar la tarea: `sin_datos` × 169.

## Éxito por tipo de pregunta

| Tipo | Tareas | Éxito |
|---|---|---|
| Precio por departamento | 383 | 383 (100,0 %) |
| Precio por municipio | 184 | 184 (100,0 %) |
| Comprar ya o esperar | 263 | 263 (100,0 %) |
| Costo de N bultos | 187 | 187 (100,0 %) |
| Sin dato vigente (vecinos) | 128 | 128 (100,0 %) |
| Nombres comunes (alias) | 57 | 57 (100,0 %) |
| Fuera de alcance (agronomía) | 65 | 65 (100,0 %) |

## Tareas por hora

| Hora | Tareas |
|---|---|
| 2026-11-07 13:00 | 71 |
| 2026-11-07 14:00 | 109 |
| 2026-11-07 15:00 | 109 |
| 2026-11-07 16:00 | 109 |
| 2026-11-07 17:00 | 109 |
| 2026-11-07 18:00 | 109 |
| 2026-11-07 19:00 | 108 |
| 2026-11-07 20:00 | 109 |
| 2026-11-07 21:00 | 109 |
| 2026-11-07 22:00 | 108 |
| 2026-11-07 23:00 | 110 |
| 2026-11-08 00:00 | 107 |

## Fallos

Ninguna tarea falló.

## Archivos

- `bitacora/s4_bitacora.csv`: una fila por tarea (hora, entrada, resultado, éxito, motivo, herramientas, reintentos, tokens, costo).
- `bitacora/s4_bitacora.jsonl`: lo mismo con la respuesta completa y el rastro de herramientas.
- `bitacora/s4_eventos.jsonl`: arranques, reinicios, reintentos, pausas y resúmenes por hora.

## Para la entrega

```
Unidades: 1.267 tareas completas en 11,63 h desatendidas
Tasa de éxito: 100,0 %
Costo total: US$ 12,21 (≈ $39.527 COP)
Costo por tarea: US$ 0,0096 (≈ $31 COP)
```
