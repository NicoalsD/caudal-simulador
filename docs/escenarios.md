# Escenarios del simulador

Un escenario es un archivo YAML en `scenarios/` que declara **todos** los parámetros de una corrida: tanque, clima, fuente, sectores, consumo, horario de turnos, fugas, lecturas del fontanero y dispositivos. El código no tiene valores de negocio propios. Todo lo que produce un escenario son **datos simulados** (`meta.simulated: true` es obligatorio).

Especificación: [Datos simulados](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Datos-simulados.md). Operación en vivo: [operacion-live.md](operacion-live.md).

## 1. Supuestos: valores que no salen de una medición

Ningún valor de los escenarios se midió en Guaitarilla. Los YAML lo marcan en sus comentarios, en inglés como todo el código, con la fórmula **"Assumption, verify"** (supuesto, verificar), casi siempre con la fuente con la que habría que contrastarlo: IDEAM o una estación cercana para el clima, un aforo para la fuente, un censo local para los hogares, la norma RAS 0330/2017 para la dotación, la Junta para el horario y los registros de reparación para las fugas. Los ajustes hechos solo para la presentación se marcan como **"Presentation setting, not a measurement"**.

Si un valor se llega a medir en campo, cámbialo en el YAML, quita la marca y anota la fuente en el comentario.

## 2. Catálogo

Los cinco escenarios comparten la misma estructura. `normal-year` es la línea base; los demás cambian solo las secciones que se indican. La prueba `tests/test_scenario_catalog.py` comprueba que todos cargan y que cada variante mueve su variable en la dirección correcta frente a `normal-year` (con 365 días y semilla 42).

Valores comunes a los cinco (sacados de los YAML):

| Sección | Valores |
|---|---|
| `meta` | `timezone: America/Bogota`, `start_date: 2026-01-01`, `default_seed: 42` |
| `tank` | `area_m2: 12.0`, regla `gauge_min: 0.0` a `gauge_max: 5.0`, `gauge_step: 0.1`, `initial_gauge: 3.4` |
| `source` | `base_flow_m3_per_hour: 0.4`, `rain_gain_m3_per_hour_per_mm: 0.03`, `response_lag_hours: 36`, `muddy_rain_threshold_mm: 20.0`, `muddy_duration_hours: 48` |
| `sectors` | `alto` (38 hogares), `centro` (52), `bajo` (45) |
| `demand` | `liters_per_person_per_day: 100`, `persons_min: 3`, `persons_max: 4`, 24 pesos horarios con picos a las 6-7 y 17-18 |
| `schedule` | turnos `alto` 5 a 9, `centro` 9 a 13, `bajo` 13 a 17, `alto` 17 a 21; cumplimiento `p_completed: 0.80`, `p_partial: 0.15`, `p_not_executed: 0.05` |
| `leaks` (salvo variantes) | `flow_m3_per_hour: 0.3`, `repair_days_min: 1`, `repair_days_max: 5` |
| `readings` | `hours: [6, 17]`, `noise_sd_m: 0.03`, `duplicate_probability: 0.02`, `no_signal_probability: 0.05`, `max_delay_hours: 12` |
| `devices.valve` | `travel_seconds: 15`, `max_travel_seconds: 60` |
| `devices.sensor` | `noise_sd_m: 0.01`, `drift_m_per_day: 0.0005` desde `drift_start_hour: 0`, pegado entre `stuck_from_hour: 1000` y `stuck_until_hour: 1012` |
| `devices.buffer` | `capacity_batches: 500`, `max_attempts: 5` |

### 2.1 `normal-year`

**Qué representa.** La operación típica del acueducto con el régimen andino bimodal: dos temporadas de lluvia al año (abril y mayo, octubre y noviembre). Es el escenario por defecto de todos los comandos y la línea base de las pruebas.

**Parámetros clave.**

- Clima: cadena de Markov de días secos y húmedos por mes, con lluvia gamma (`gamma_shape: 0.8`). En los meses lluviosos (4, 5, 10 y 11) `p_wet_after_dry: 0.55`, `p_wet_after_wet: 0.70` y `gamma_scale_mm: 9.0`; en los más secos (1, 7 y 8) `0.25`, `0.45` y entre `5.0` y `6.0` mm.
- Fuente: caudal base de `0.4` m³/h, calibrado para que la entrada media se acerque a la entrega media (ver `tests/test_normal_scenario.py`).
- Fugas: `rate_per_month: 0.8` y `report_probability_per_day: 0.3`.

**Qué produce.** Además del clima y el consumo, los fallos de campo de la línea base: lecturas del fontanero con ruido (0.03 m), duplicadas (2 %) o enviadas sin señal y entregadas hasta 12 horas después (5 %); turnos parciales o no ejecutados; agua con barro durante 48 horas tras un día de 20 mm o más; fugas ocasionales; y un sensor de nivel con ruido, deriva lenta y una ventana pegado entre las horas 1000 y 1012.

```bash
uv run caudal-sim generate --scenario normal-year --days 365 --seed 42
```

### 2.2 `dry-year`

**Qué representa.** Un año seco tipo El Niño, para probar racionamiento severo.

**Parámetros clave.** Solo cambia `climate.monthly`. Según la cabecera del YAML, frente a `normal-year`: `p_wet_after_dry` por 0.5, `p_wet_after_wet` por 0.6 y `gamma_scale_mm` por 0.7. Por ejemplo, abril queda en `p_wet_after_dry: 0.28`, `p_wet_after_wet: 0.42`, `gamma_scale_mm: 6.3`, y julio en `0.12`, `0.27` y `3.5`. Supuesto, verificar con registros de temporada seca del IDEAM.

**Qué produce.** Menos lluvia que el año normal (lo verifica `test_dry_year_rains_less_than_the_normal_year`). Como el caudal de la fuente depende de la lluvia (`rain_gain_m3_per_hour_per_mm`), entra menos agua al tanque: es el escenario para probar el racionamiento severo. El resto de fallos es el de la línea base.

```bash
uv run caudal-sim generate --scenario dry-year --days 365
```

### 2.3 `rainy-year`

**Qué representa.** Un año lluvioso tipo La Niña, para probar desbordes y agua con barro.

**Parámetros clave.** Solo cambia `climate.monthly`: probabilidades de día húmedo por 1.2 (con tope de 0.95) y `gamma_scale_mm` por 1.3. Abril queda en `p_wet_after_dry: 0.66`, `p_wet_after_wet: 0.84`, `gamma_scale_mm: 11.7`. Supuesto, verificar con registros del IDEAM.

**Qué produce.** Más lluvia que el año normal (lo verifica `test_rainy_year_rains_more_than_the_normal_year`). Con más días por encima de `muddy_rain_threshold_mm: 20.0` hay más periodos de agua con barro, y con más caudal de entrada el tanque se acerca más al tope de la regla (5.0 m): es el escenario para probar desbordes. El resto de fallos es el de la línea base.

```bash
uv run caudal-sim generate --scenario rainy-year --days 365
```

### 2.4 `frequent-leaks`

**Qué representa.** Una red con fugas frecuentes, para probar la detección de anomalías y los reportes de la comunidad.

**Parámetros clave.** Solo cambia `leaks`: `rate_per_month: 4.0` (cinco veces la línea base) y `report_probability_per_day: 0.5`. El clima es el de `normal-year`. Supuesto, verificar con el historial del acueducto.

**Qué produce.** Más fugas que el año normal (lo verifica `test_frequent_leaks_produce_more_leaks_than_the_normal_year`), cada una de `0.3` m³/h durante 1 a 5 días, y más reportes de daño de las familias en `observed/damage_reports`.

```bash
uv run caudal-sim generate --scenario frequent-leaks --days 365
uv run caudal-sim backfill incidents --scenario frequent-leaks --days 90 --dry-run
```

### 2.5 `presentation`

**Qué representa.** El acueducto normal más el guion de `caudal-sim demo`, pensado para tres días de presentación.

**Parámetros clave.**

- `leaks.rate_per_month: 15.0` y `leaks.report_probability_per_day: 0.9`, marcados como ajuste de presentación: así aparece una fuga y una familia la reporta dentro de los tres días.
- Es el único escenario con sección `demo` (clase `DemoSpec`):

| Clave | Valor | Uso |
|---|---|---|
| `gauge_error_hour` | `9` | Hora en que el fontanero escribe un valor fuera de la regla. |
| `gauge_error_value` | `8.0` | Valor erróneo, fuera de la regla de 0 a 5 m. |
| `muddy_hour` | `10` | Hora en que se anota agua con barro. |
| `muddy_appearance_code` | `MUDDY` | Código del catálogo `WATER_APPEARANCE`. |
| `muddy_note` | `Agua con barro tras la lluvia de la noche. Dato simulado.` | Nota del fontanero. |
| `silent_sensor_hour` | `12` | Hora en que el sensor pierde la señal (durante `SENSOR_SILENT_HOURS = 6` horas, constante de `caudal_sim/live.py`). |
| `damage_report_hour_of_day` | `15` | Hora del día en que la familia reporta la fuga por el formulario público. |

Las horas cuentan desde el inicio de la corrida, salvo `damage_report_hour_of_day`, que es la hora del día en que se reporta cada fuga según la semilla.

**Qué produce.** Los fallos del guion descritos en [operacion-live.md](operacion-live.md#5-guion-demo): `422 GAUGE_OUT_OF_RANGE` por el dato fuera de la regla, la lectura corregida, la lectura con barro, la telemetría que llega con su hora original al volver la señal y el reporte de fuga con código de seguimiento.

```bash
uv run caudal-sim demo --start 2026-10-10
```

`demo` usa `presentation` y 3 días por defecto. Necesita el acueducto demo, las cuentas y la clave del nodo (ver [operacion-live.md](operacion-live.md#2-requisitos)). Para ver solo los datos sin contactar el backend:

```bash
uv run caudal-sim generate --scenario presentation --days 3
```

## 3. Comandos que usan un escenario

Todos aceptan `--scenario` con el nombre del archivo (`scenarios/<nombre>.yaml`) o una ruta a un YAML, y `--seed` para cambiar la semilla. Con la misma semilla y el mismo escenario los datos son idénticos.

| Comando | Qué hace | Días por defecto |
|---|---|---|
| `uv run caudal-sim generate` | Escribe `truth/` (lluvia diaria, serie horaria, fugas), `observed/` (lecturas, ejecuciones de turnos, reportes de daño) y `manifest.json` en `--out` (por defecto `outputs`). `--format csv`, `parquet` o `both` (por defecto). No envía nada. | 365 |
| `uv run caudal-sim export-actas` | Exporta las ejecuciones de turnos confirmadas para las actas. | 365 |
| `uv run caudal-sim export-backtest` | Exporta ventanas históricas para el backtest de la IA. | 365 |
| `uv run caudal-sim backfill readings`, `shift-executions` o `incidents` | Importa el historial simulado al acueducto demo. `--dry-run` cuenta los lotes sin contactar la API, pero igual necesita las variables de `.env` (ver [despliegue.md](despliegue.md#4-variables-de-entorno)). | 90 |
| `uv run caudal-sim live` | Simula en tiempo real y envía los datos al acueducto demo. Acepta `--start AAAA-MM-DD`. | 1 |
| `uv run caudal-sim demo` | Guion de demostración. Exige la sección `demo`. | 3 |

Ejemplo con otra semilla y salida solo en CSV:

```bash
uv run caudal-sim generate --scenario rainy-year --days 90 --seed 7 --out outputs/rainy-7 --format csv
```

## 4. Crear un escenario nuevo

1. Copia el escenario más parecido. Por ejemplo, `cp scenarios/normal-year.yaml scenarios/mi-escenario.yaml`.
2. Cambia `meta.name` para que coincida con el nombre del archivo (la prueba del catálogo lo exige para los escenarios del repositorio) y escribe una `meta.description` en español que diga que los datos son simulados.
3. Cambia solo los parámetros que el escenario quiere probar y explica en la cabecera del archivo qué cambia frente a `normal-year` y por qué, como hacen `dry-year` y `frequent-leaks`.
4. Marca cada valor que no venga de una medición con "Assumption, verify" y la fuente con la que se debería contrastar.
5. No pongas contraseñas, tokens ni claves en el YAML: van en `.env` y en `keys/` (ver [claves-y-secretos.md](claves-y-secretos.md)).
6. Pruébalo con una corrida corta que no contacta el backend:

   ```bash
   uv run caudal-sim generate --scenario mi-escenario --days 30
   ```

7. Si el escenario entra al catálogo, agrégalo a `CATALOG` en `tests/test_scenario_catalog.py` y, si mueve una variable, agrega una prueba que lo compare con `normal-year`.

## 5. Cómo se valida

El YAML se lee con `ScenarioBuilder` (`caudal_sim/builder.py`, patrón Builder), que aplica los cambios de la línea de comandos (`--seed` sobre `meta.default_seed` y `--start` sobre `meta.start_date`) y en `build()` valida todo con el modelo Pydantic **`Scenario`** (`caudal_sim/scenario.py`). Sus secciones son las clases `ScenarioMeta`, `TankSpec`, `ClimateSpec` (con `MonthClimate`), `SourceSpec`, `SectorSpec`, `DemandSpec`, `ScheduleSpec` (con `TurnSpec`), `LeakSpec`, `ReadingSpec`, `DevicesSpec` (con `ValveSpec`, `SensorSpec` y `BufferSpec`) y la opcional `DemoSpec`.

Reglas que se comprueban al cargar:

- Todos los modelos usan `extra="forbid"`: una clave mal escrita o de más hace fallar el escenario en lugar de ignorarse.
- `meta.name` y los identificadores de sector siguen el patrón `^[a-z][a-z0-9-]*$`; `meta.simulated` solo admite `true`; `meta.timezone` debe ser una zona horaria conocida.
- La regla del tanque es coherente: `gauge_min` menor que `gauge_max`, `gauge_step` no mayor que el rango e `initial_gauge` dentro de la regla.
- `climate.monthly` tiene una fila por mes.
- `demand.hourly_weights` tiene 24 valores no negativos que suman más de 0, y `persons_min` no supera `persons_max`.
- Cada turno tiene `start_hour` menor que `end_hour`, y `p_completed + p_partial + p_not_executed` suma 1.
- Los identificadores de sector son únicos y el horario solo usa sectores que existen.
- `repair_days_min` no supera `repair_days_max`; las horas de lectura están ordenadas, sin repetir y dentro del día; `max_travel_seconds` cubre `travel_seconds`; la ventana del sensor pegado va hacia adelante.

Si algo falla, el comando termina con código 1 y un mensaje en español que nombra el archivo y cada campo con su error, por ejemplo:

```text
Error: escenario inválido (scenarios/mi-escenario.yaml): meta.name: String should match pattern '^[a-z][a-z0-9-]*$'; ...
```
