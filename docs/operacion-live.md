# Operación del modo live y del guion demo

Este documento explica cómo correr el simulador en tiempo real (`caudal-sim live`), cómo ejecutar el guion de demostración (`caudal-sim demo`), cómo usar el tablero local y cómo correr la maqueta virtual (`caudal-sim maqueta`, sección 7). Todo lo que el simulador envía es **simulado** y se marca así en el tablero.

Especificación: [Datos simulados](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Datos-simulados.md), secciones 5 y 6.

**Alcance B2B (2026-11-20).** Este documento describe la operación actual, contra el acueducto demo. En el modelo B2B el destino es una institución simulada (`is_simulated`), el guion y los comandos de Junta y de lecturas manuales salen del producto, y la maqueta física pasa al puente `maqueta-usb`. Lo nuevo se marca como *por implementar* o *por definir*.

## 1. Qué hace y qué no hace

| Sí hace | No hace |
|---|---|
| Avanza el reloj simulado hora por hora, a la velocidad que pida el tablero. | No ejecuta comandos de válvula: `live` reproduce la simulación ya calculada y no consulta `GET /devices/commands`. Los comandos los ejecuta la maqueta (sección 7). Los turnos salen del producto B2B (por definir). |
| Envía la lectura del sensor de nivel como **telemetría firmada** (Ed25519) a `POST /api/v1/devices/telemetry`. | No propone turnos ni los aprueba (los turnos salen del producto B2B). |
| Envía las **lecturas** del fontanero simulado a `POST /api/v1/readings` con la cuenta OPERATOR. Hoy; el endpoint sale del producto B2B (por definir). | Los comandos de válvula no pasan por `live`: ver la maqueta virtual, sección 7. |
| Guarda la telemetría sin señal y la envía después con su hora original. | No inventa datos reales: todo sale del escenario y de la semilla. |
| Publica su estado y sus eventos en el tablero local (`http://127.0.0.1:8000`). | No se conecta a ninguna institución que no tenga `is_simulated = true` (hoy la columna se llama `is_demo`). |

En el modelo B2B no hay Junta ni propuestas de turnos. Este párrafo describe la operación actual y se reescribe con el guion (por definir).

## 2. Requisitos

1. **Institución simulada en el backend** (hoy, acueducto demo). El simulador revisa antes de enviar nada que la institución del slug `CAUDAL_SIM_DEMO_AQUEDUCT_SLUG` tenga `is_demo = true` (B2B: `is_simulated = true`). Si no, cancela con un mensaje en español y no envía nada.
2. **Cuentas.** `CAUDAL_SIM_API_USERNAME` (hoy PROJECT_TEAM; en B2B, PLATFORM_ADMIN, porque la importación pasa al superadmin) para el historial, `CAUDAL_SIM_LIVE_OPERATOR_USERNAME` (OPERATOR) para las lecturas (por definir en B2B) y, solo para `--auto-junta`, `CAUDAL_SIM_LIVE_BOARD_USERNAME` (Junta; sale del producto B2B). Las contraseñas van en `.env`.
3. **Dispositivo registrado.** El nodo de nivel simulado existe en el backend con su clave pública registrada (ver [Claves y secretos](claves-y-secretos.md)).
4. **Clave privada** en `keys/ed25519-private.pem` (o la ruta de `CAUDAL_SIM_PRIVATE_KEY_PATH`).
5. **Reloj simulado cercano a hoy.** La API rechaza lecturas más viejas que `max_backdate_days` con `422 TOO_OLD`. Por eso `live` acepta `--start AAAA-MM-DD`. Usa la fecha siguiente al último día del historial que cargaste con `backfill`.

## 3. Comandos

```bash
# Simulación en vivo con el tablero (por defecto, escenario normal-year, 1 día)
uv run caudal-sim live --scenario normal-year --start 2026-10-10

# Corrida corta sin tablero, para pruebas
uv run caudal-sim live --scenario normal-year --max-hours 24 --sin-tablero

# Corrida larga con la Junta simulada (por definir en B2B: la Junta sale del producto)
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
| `--auto-junta` | Aprueba las propuestas pendientes con la Junta simulada. Por definir en B2B. |
| `--tablero` / `--sin-tablero` | Levanta o no la API del tablero junto a la simulación. |

Comando de la maqueta virtual (sección 7):

```bash
# Corre la maqueta contra la API (sin --seconds, corre hasta Ctrl+C)
uv run caudal-sim maqueta --scenario scenarios/maqueta.yaml --api-url http://localhost:8080 --seconds 600
```

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

El guion corre sobre el escenario `presentation` (tres días, semilla fija) y ejecuta los fallos de la especificación en horas fijas del YAML (sección `demo:`). Por definir en B2B: los pasos que usan lecturas, reporte público y Junta dependen de funciones que salen del producto.

| Paso | Hora | Qué envía | Resultado esperado |
|---|---|---|---|
| Dato fuera de la regla | 9 | Un valor de 8 m en una regla de 0 a 5 m. | La API responde `422 GAUGE_OUT_OF_RANGE` y no guarda la lectura. |
| Lectura corregida | 9 | La lectura con el valor corregido. | Se guarda (201). |
| Agua con barro | 10 | Lectura con el código `MUDDY` y una nota. | Se guarda (201). |
| Sensor sin señal | 12 | El sensor deja de enviar durante seis horas. | Al volver, la telemetría llega con su hora original. |
| Fuga reportada | 63 | Un reporte de la familia por el formulario público, con código de seguimiento (el reporte público sale del producto B2B: por definir). | Se registra (201). |

Después vienen cuatro pasos **manuales** (IA caída, propuesta y decisión de la Junta, publicación y cierre del día con acta). La propuesta, la Junta y la publicación salen del producto B2B (por definir). El simulador no los controla, así que la lista los marca como manuales y no como cumplidos.

El guion usa el mismo camino que la operación real: no hay rutas de simulación en el backend.

## 6. Qué revisar si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| Cancela con "no es la institución simulada". | `is_demo` (B2B: `is_simulated`) es falso en la institución del slug. | Revisa `CAUDAL_SIM_DEMO_AQUEDUCT_SLUG`. No cambies la marca para forzarlo. |
| `422 TOO_OLD` en cada lectura. | El reloj simulado está lejos de hoy. | Usa `--start` con una fecha reciente. |
| `401 INVALID_SIGNATURE` en la telemetría. | La clave pública registrada no corresponde a `keys/`. | Ver [Claves y secretos](claves-y-secretos.md), sección 3. |
| "El buffer sin conexión está lleno". | Hubo demasiado tiempo sin red. | Restablece la red o sube `capacity_batches` en el escenario, y documenta el cambio. |
| Lecturas "rechazadas" en el resumen. | La API aplicó una regla (rango, horario). Hoy; las reglas versionadas salen del modelo B2B (por definir). | Revisa el mensaje; no fuerces el dato. |

## 7. Maqueta virtual (`caudal-sim maqueta`)

La maqueta virtual es el gemelo de la maqueta física con ESP32 (`caudal-maqueta`). El montaje actual de la maqueta es el Arduino UNO por USB (`caudal-maqueta/docs/arduino-uno.md`), que usa el puente `maqueta-usb` y no esta maqueta virtual. Es un dispositivo firmado que habla con la API por el mismo protocolo de [Protocolo de dispositivos](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Protocolo-de-dispositivos.md): firma cada petición con Ed25519, envía la telemetría de nivel y ejecuta los comandos de sus válvulas. Así el lazo "bomba y tanque, nivel, comando, válvula, confirmación" se prueba sin hardware.

### 7.1 Qué hace

`caudal-sim maqueta` es un comando aparte y no `live --scenario maqueta`: `live` reproduce un `Scenario` ya calculado, hora por hora, con clima y consumo, mientras que la maqueta es un dispositivo en tiempo real con su propio formato de escenario (`scenarios/maqueta.yaml`, sin clima ni consumo).

| Paso | Qué ocurre |
|---|---|
| Modelo | Un tanque de 0,07 m² con una bomba de 4 L/min, un flotador alto que corta la bomba y dos salidas de 1/4". El nivel sigue `dV/dt = Q_in - Σ Cd·A·apertura·√(2gh) - rebose`. El rebose está a 0,32 m. |
| Ciclo | Cada `tick_seconds` (1 s): mueve las válvulas, avanza el tanque y agrega el nivel al lote de telemetría. |
| Telemetría | Cada `telemetry_interval_seconds` (10 s) envía el lote de puntos `LEVEL` a `POST /api/v1/devices/telemetry`, firmado por el sensor. Si la red falla, el lote queda en el buffer sin conexión y se reenvía en orden. |
| Comandos | Cada `command_poll_seconds` (2 s) cada válvula consulta `GET /api/v1/devices/commands` y ejecuta `OPEN` o `CLOSE` dentro de su ventana. Responde cada comando con `POST /api/v1/devices/commands/{id}/ack`: `ACKED` cuando la válvula llega a la posición, `FAILED` si la válvula falla o el comando no es de esta maqueta. |

Un comando desconocido (acción o válvula que la maqueta no tiene) se confirma como `FAILED` con un detalle en español. Un comando vencido no se ejecuta ni se confirma: lo marca el servidor como `EXPIRED`.

### 7.2 Prerrequisitos en el backend

La maqueta son **tres dispositivos firmados**, porque así los modela el backend: el sensor de nivel del tanque (`LEVEL_SENSOR`) y un actuador por salida (`VALVE_ACTUATOR`, con su `valve_id`). Los comandos se entregan al dispositivo del actuador, no al sensor. Para cada dispositivo:

1. Alta con `POST /api/v1/devices` (permiso `DEVICE_MANAGE`).
2. Generar su par Ed25519 en `keys/` (ignorado por git) y registrar la clave pública con `POST /api/v1/devices/{id}/keys`.
3. Anotar su identificador en `.env`.

Hoy, el tanque del dispositivo sensor debe tener la regla de medida de 0 a 0,32 m, porque la telemetría de nivel se valida contra `gauge_min` y `gauge_max`. En B2B, el nivel se convierte con la geometría del tanque de la institución (`empty_distance_mm`, `full_distance_mm`) y la regla de medida desaparece (por implementar; la geometría de la maqueta virtual, por definir).

### 7.3 Variables de entorno

| Variable | Para qué sirve |
|---|---|
| `CAUDAL_SIM_MAQUETA_API_BASE_URL` | URL base de `caudal-backend`, sin barra final. Lo puede sustituir `--api-url`. |
| `CAUDAL_SIM_MAQUETA_SENSOR_DEVICE_ID` | Identificador del sensor de nivel. |
| `CAUDAL_SIM_MAQUETA_SENSOR_PRIVATE_KEY_PATH` | Clave privada del sensor (por defecto `keys/maqueta-sensor.pem`). |
| `CAUDAL_SIM_MAQUETA_VALVE_1_DEVICE_ID`, `CAUDAL_SIM_MAQUETA_VALVE_1_VALVE_ID`, `CAUDAL_SIM_MAQUETA_VALVE_1_PRIVATE_KEY_PATH` | Actuador de la salida 1: dispositivo, válvula y clave (por defecto `keys/maqueta-valve-1.pem`). |
| `CAUDAL_SIM_MAQUETA_VALVE_2_DEVICE_ID`, `CAUDAL_SIM_MAQUETA_VALVE_2_VALVE_ID`, `CAUDAL_SIM_MAQUETA_VALVE_2_PRIVATE_KEY_PATH` | Lo mismo para la salida 2 (por defecto `keys/maqueta-valve-2.pem`). |
| `CAUDAL_SIM_MAQUETA_HTTP_TIMEOUT_SECONDS` | Tiempo máximo de cada petición (por defecto 10). |

Ver `.env.example`. Ninguna clave privada va en el repositorio.

### 7.4 Parámetros del modelo

Todo está en `scenarios/maqueta.yaml`, sin valores en el código: área, altura, rebose, nivel inicial, flotador alto y de arranque (histéresis), caudal de la bomba, diámetro y coeficiente de cada salida, tiempos de recorrido de la válvula y periodos del ciclo. Los valores marcados como *assumption, verify* se contrastan con la maqueta física antes de usarla para decisiones.

### 7.5 Límites conocidos

- **Solo el nivel.** El protocolo no admite una métrica de caudal por salida (`FLOW`), y `VALVE_POSITION` no distingue dos válvulas en un mismo actuador. Por eso la maqueta envía solo `LEVEL`. El caudal sale del modelo, no de una medición: el hueco queda documentado y no se resuelve con datos inventados.
- **Una lectura por punto.** Cada punto `LEVEL` genera una fila en `ops.readings` del backend. Con el intervalo de 10 s son unas 8.600 lecturas al día. Para una demostración corta está bien; en una corrida larga, sube `telemetry_interval_seconds` en el YAML.
- **Reglas de validación del backend.** Las lecturas de la maqueta pasan por la misma cadena que cualquier lectura (`Reglas-de-negocio.md`, sección 8). Con los valores de ejemplo de la regla, casi todas las lecturas durante el llenado quedarían `FLAGGED` por `SUDDEN_JUMP`: el llenado de la maqueta sube unos 3,5 m/h (9,5·10⁻⁴ m/s), y el ejemplo de la regla es 0,30 m/h. Con la bomba cortada y sin salidas, el nivel no cambia y el backend puede marcar `SENSOR_FAULT` (valor pegado). Para la maqueta hay que dar a su conjunto de reglas un `max_level_change_per_hour` por encima de ese ritmo y una ventana de duplicados corta. Las lecturas se marcan, no se rechazan. Hoy; en B2B la validación pasa a anomalías y el límite de cambio sale de `max_level_change_per_minute` en `institution_settings` (por implementar).
- **Límite de peticiones.** La API permite 60 peticiones por minuto por dispositivo. El intervalo de consulta de 2 s deja holgura. Un `429` no detiene la maqueta: los lotes esperan en el buffer y la consulta se reintenta en el siguiente ciclo.
- **Apertura en el recorrido.** Una válvula en movimiento se modela con apertura lineal en el tiempo. Si una válvula cambia de sentido a mitad de recorrido, la apertura salta (aproximación del modelo sencillo). En `FAULT` se supone cerrada.
- **Tiempo real.** La maqueta usa el reloj del equipo, no el reloj simulado de `live`. Con `--seconds` corre esa cantidad de segundos; sin él, corre hasta `Ctrl+C`, y el resumen se imprime al salir.
- **Sin pantalla en vivo.** La maqueta imprime un resumen al final. Para ver el estado en vivo, usa la aplicación de la institución o el tablero del backend.

### 7.6 Pruebas

Las pruebas usan un transporte HTTP falso (`httpx.MockTransport`), sin red. El falso servidor verifica las firmas con su propia implementación de la cadena canónica, para comprobar que la maqueta firma bien y no solo que se firma algo. Cubren la física (vaciado con nivel alto, rebose, corte por flotador), la ejecución de comandos con su ack, y el comando desconocido confirmado como `FAILED`. Se corren con `uv run pytest`.

