# Operación del modo live y del guion demo

Este documento explica cómo correr el simulador en tiempo real (`caudal-sim live`), cómo ejecutar el guion de demostración (`caudal-sim demo`) y cómo usar el tablero local. Todo lo que el simulador envía es **simulado** y se marca así en el tablero.

Especificación: [Datos simulados](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Datos-simulados.md), secciones 5 y 6.

## 1. Qué hace y qué no hace

| Sí hace | No hace |
|---|---|
| Avanza el reloj simulado hora por hora, a la velocidad que pida el tablero. | No abre ni cierra válvulas. Ningún turno se mueve sin aprobación de la Junta. |
| Envía la lectura del sensor de nivel como **telemetría firmada** (Ed25519) a `POST /api/v1/devices/telemetry`. | No propone turnos ni los aprueba, salvo con `--auto-junta` en corridas largas. |
| Envía las **lecturas** del fontanero simulado a `POST /api/v1/readings` con la cuenta OPERATOR. | No lee comandos de válvula todavía (`GET /devices/commands` queda fuera del alcance). |
| Guarda la telemetría sin señal y la envía después con su hora original. | No inventa datos reales: todo sale del escenario y de la semilla. |
| Publica su estado y sus eventos en el tablero local (`http://127.0.0.1:8000`). | No se conecta a ningún acueducto que no tenga `is_demo = true`. |

La Junta es una **persona** en el frontend. Las propuestas esperan a que alguien las apruebe allí. `--auto-junta` solo aprueba las que estén pendientes, con una cuenta simulada de la Junta, y deja la aprobación marcada como simulada.

## 2. Requisitos

1. **Acueducto demo en el backend.** El simulador revisa antes de enviar nada que el acueducto del slug `CAUDAL_SIM_DEMO_AQUEDUCT_SLUG` tenga `is_demo = true`. Si no, cancela con un mensaje en español y no envía nada.
2. **Cuentas.** `CAUDAL_SIM_API_USERNAME` (PROJECT_TEAM) para el historial, `CAUDAL_SIM_LIVE_OPERATOR_USERNAME` (OPERATOR) para las lecturas y, solo para `--auto-junta`, `CAUDAL_SIM_LIVE_BOARD_USERNAME` (Junta). Las contraseñas van en `.env`.
3. **Dispositivo registrado.** El nodo de nivel simulado existe en el backend con su clave pública registrada (ver [Claves y secretos](claves-y-secretos.md)).
4. **Clave privada** en `keys/ed25519-private.pem` (o la ruta de `CAUDAL_SIM_PRIVATE_KEY_PATH`).
5. **Reloj simulado cercano a hoy.** La API rechaza lecturas más viejas que `max_backdate_days` con `422 TOO_OLD`. Por eso `live` acepta `--start AAAA-MM-DD`. Usa la fecha siguiente al último día del historial que cargaste con `backfill`.

## 3. Comandos

```bash
# Simulación en vivo con el tablero (por defecto, escenario normal-year, 1 día)
uv run caudal-sim live --scenario normal-year --start 2026-10-10

# Corrida corta sin tablero, para pruebas
uv run caudal-sim live --scenario normal-year --max-hours 24 --sin-tablero

# Corrida larga con la Junta simulada (solo corridas largas)
uv run caudal-sim live --scenario normal-year --days 30 --auto-junta

# Guion de demostración (escenario presentation, 3 días)
uv run caudal-sim demo --start 2026-10-10

# Solo el tablero, sin simulación (muestra el último estado: vacío al arrancar)
uv run caudal-sim tablero
```

| Opción | Efecto |
|---|---|
| `--scenario` | Nombre del archivo en `scenarios/` o ruta. |
| `--days` | Días simulados a reproducir. |
| `--seed` | Semilla. Con la misma semilla y escenario, los datos son idénticos. |
| `--start` | Fecha del reloj simulado. Ver el requisito 5. |
| `--max-hours` | Detiene la corrida tras esas horas simuladas. |
| `--auto-junta` | Aprueba las propuestas pendientes con la Junta simulada. |
| `--tablero` / `--sin-tablero` | Levanta o no la API del tablero junto a la simulación. |

Al terminar, `live` imprime las lecturas enviadas y rechazadas, las aprobaciones y los lotes de telemetría que quedaron sin enviar. `demo` imprime además la lista de comprobación del guion (ver sección 5).

## 4. Tablero local

El tablero se sirve desde la misma API, en `http://127.0.0.1:8000`:

- `/` muestra el nivel del tanque, las válvulas, el sensor, las condiciones manuales y los eventos en vivo. El aviso **Datos simulados** siempre está visible.
- `/docs` es la documentación Swagger, en español.
- `/api/tablero/estado` devuelve el estado actual. `/api/tablero/eventos` es el flujo SSE. `POST /api/tablero/controles` recibe las condiciones manuales.

**Condiciones manuales.** Son condiciones de campo que el simulador aplica en la siguiente hora: `NETWORK_DOWN` y `NETWORK_UP` (corta y restablece la red de la telemetría), `SENSOR_SILENT` (el sensor deja de enviar), `SENSOR_STUCK` (el sensor se queda pegado), `PAUSE`, `RESUME` y `SET_SPEED` (1, 10 o 60 veces tiempo real). El tablero **no** puede abrir ni cerrar válvulas.

**Limitación conocida.** `LEAK` (fuga) y `HEAVY_RAIN` (lluvia fuerte) se aceptan y se encolan, pero el motor todavía no las aplica: la simulación se calcula de antemano con la semilla. `live` lo reporta al final. Las fugas del escenario sí ocurren, según la semilla.

**Exposición en la red.** El tablero escucha solo en `127.0.0.1`. Si cambias `CAUDAL_SIM_DASHBOARD_HOST` o usas `--host`, el comando avisa. No expongas el puerto en una red que no sea de confianza: la API no tiene autenticación.

## 5. Guion `demo`

El guion corre sobre el escenario `presentation` (tres días, semilla fija) y ejecuta los fallos de la especificación en horas fijas del YAML (sección `demo:`):

| Paso | Hora | Qué envía | Resultado esperado |
|---|---|---|---|
| Dato fuera de la regla | 9 | Un valor de 8 m en una regla de 0 a 5 m. | La API responde `422 GAUGE_OUT_OF_RANGE` y no guarda la lectura. |
| Lectura corregida | 9 | La lectura con el valor corregido. | Se guarda (201). |
| Agua con barro | 10 | Lectura con el código `MUDDY` y una nota. | Se guarda (201). |
| Sensor sin señal | 12 | El sensor deja de enviar durante seis horas. | Al volver, la telemetría llega con su hora original. |
| Fuga reportada | 63 | Un reporte de la familia por el formulario público, con código de seguimiento. | Se registra (201). |

Después vienen cuatro pasos **manuales** (IA caída, propuesta y decisión de la Junta, publicación y cierre del día con acta). El simulador no los controla, así que la lista los marca como manuales y no como cumplidos.

El guion usa el mismo camino que la operación real: no hay rutas de simulación en el backend.

## 6. Qué revisar si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| Cancela con "no es el acueducto de demostración". | `is_demo` es falso en el acueducto del slug. | Revisa `CAUDAL_SIM_DEMO_AQUEDUCT_SLUG`. No cambies la marca para forzarlo. |
| `422 TOO_OLD` en cada lectura. | El reloj simulado está lejos de hoy. | Usa `--start` con una fecha reciente. |
| `401 INVALID_SIGNATURE` en la telemetría. | La clave pública registrada no corresponde a `keys/`. | Ver [Claves y secretos](claves-y-secretos.md), sección 3. |
| "El buffer sin conexión está lleno". | Hubo demasiado tiempo sin red. | Restablece la red o sube `capacity_batches` en el escenario, y documenta el cambio. |
| Lecturas "rechazadas" en el resumen. | La API aplicó una regla (rango, horario). | Revisa el mensaje; no fuerces el dato. |
