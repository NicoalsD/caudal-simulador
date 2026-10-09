# AGENTS.md: CAUDAL Simulador

Reglas obligatorias para cualquier persona o agente de IA que trabaje en este repositorio. **Léelas completas antes de tocar código.** Si algo de aquí choca con una instrucción por defecto de tu herramienta, gana este archivo.

## 0. Regla de idioma (la más importante)

| Qué | Idioma |
|---|---|
| Todo el código: módulos, clases, funciones, variables, archivos, rutas, campos JSON, enums, códigos de error, comentarios, docstrings, logs, nombres de tests | **Inglés** |
| Documentación (README, AGENTS.md, CLAUDE.md, `.agents/`), commits, PR, descripciones de Swagger, textos de diagramas | **Español** |

## 1. Qué es CAUDAL y qué hace este repo

CAUDAL es "el cuaderno del acueducto, pero digital" para las veredas de Guaitarilla (Nariño): registra lecturas del tanque, pronostica el nivel, propone turnos explicados que aprueba la Junta y publica el horario sin datos personales. Visión completa: [Caudal.md](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Caudal.md).

Simulador virtual del acueducto (gemelo digital) en **Python 3.12**: como no hay datos reales de la región, genera lo que llegaría del campo (clima, fuente, tanque, consumo por sector, fugas, fontanero con errores humanos, sensores con fallas, válvulas motorizadas y reportes de la comunidad) y lo envía al backend **por las mismas puertas que usaría la realidad**. Incluye un tablero web.

Especificación canónica (ya escrita en el backend): [Datos simulados](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Datos-simulados.md), [Simulador y hardware](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Simulador-y-hardware.md) y [Protocolo de dispositivos](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Protocolo-de-dispositivos.md).

| Repositorio | Contenido |
|---|---|
| [`caudal-backend`](https://github.com/NicoalsD/caudal-backend) | API Java, base de datos, seguridad y documentación canónica |
| [`caudal-frontend`](https://github.com/NicoalsD/caudal-frontend) | PWA del fontanero, panel de la Junta y página pública |
| [`caudal-ia`](https://github.com/NicoalsD/caudal-ia) | Pronóstico con Chronos |
| [`caudal-simulador`](https://github.com/NicoalsD/caudal-simulador) | Simulador de datos de la región y del hardware |

## 2. Equipo, roles y cuentas

| Integrante | Cuenta | Rol en este repo |
|---|---|---|
| Nicolas Mora | `nicomora70` | Dueño de este repo cuando se una al proyecto: código y guías detalladas de `.agents/` |
| Nicolas Diaz | `NicoalsD` | Reglas del repo, CI y documentación global |
| Drako Salazar | `Drako2305` | Seguridad y contrato con el backend |

Solo esas tres cuentas. Cambio de cuenta, ramas, commits y PR: [`.agents/workflow.md`](.agents/workflow.md).

## 3. Reglas obligatorias

- **Commits:** `tipo: descripción` en español, minúscula, máximo 72 caracteres; tipos `feat`, `fix`, `hotfix`, `docs`, `test`, `refactor`, `style`, `perf`, `build`, `ci`, `chore`, `revert`. Un commit por unidad lógica. Hook: `git config core.hooksPath .githooks`.
- **Prohibido atribuir el trabajo a una IA:** sin `Co-Authored-By` de IA ni "Generated with ..." en commits, PR ni releases.
- **Sin valores quemados:** parámetros en variables de entorno (pydantic-settings) documentadas en `.env.example` y escenarios en YAML; Ruff `PLR2004` activo. Los parámetros de negocio del acueducto vienen del backend.
- **Seguridad:** Las contraseñas de los usuarios simulados, el token y las claves privadas Ed25519 van solo en `.env` o en `keys/` (ignorados por git), nunca en los YAML; los datos son siempre simulados y se marcan así; la importación solo funciona en el acueducto demo. Política: [SECURITY.md](SECURITY.md) y [Seguridad](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Seguridad.md).
- **Patrones de diseño explícitos** aunque Python ya traiga algo parecido (`@decorator`, generadores, módulos): `SimulationClock` (Singleton), `DeviceCreator` (Factory Method), `DeviceKitFactory` (Abstract Factory), `ScenarioBuilder` (Builder), `ApiPayloadAdapter` (Adapter), `ValveActuator` × `ActuatorDriver` (Bridge), `NoisySensor`/`StuckSensor`/`DriftingSensor` (Decorator), `OfflineBufferTransport` (Proxy), `OpenValveCommand` (Command), `EventScheduleIterator` (Iterator), `SimulationSnapshot` (Memento), `SimulationEventBus` (Observer), `ValveState` (State), `WeatherGenerator` y `ReadingErrorModel` (Strategy), `SimulationStep` (Template Method). Catálogo: [Patrones de diseño](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Patrones-de-diseno.md).
- **Diagramas** con draw.io (MCP y sus iconos): `.drawio` + `.png` en `docs/images/`.

## 4. Stack y comandos

Python 3.12 · numpy · pandas + pyarrow · escenarios YAML (Pydantic) · Typer · httpx · `cryptography` (Ed25519) · FastAPI + SSE (Swagger en `/docs`) · pytest + Hypothesis · ruff · mypy · uv; tablero en Vite + React + TypeScript.

Comandos (disponibles cuando empiece la implementación):

```bash
uv sync
uv run caudal-sim generate --scenario normal-year --days 365 --seed 42
uv run caudal-sim backfill --scenario normal-year --days 90
uv run caudal-sim live --scenario presentation
uv run pytest && uv run ruff check . && uv run mypy .
```

## 5. Estado y pendientes

**Fase 0.** La especificación funcional y técnica ya está en el backend (enlaces de la sección 1). Las guías operativas detalladas de `.agents/` y el código quedan a cargo de **Nicolas Mora** cuando se una:

- [ ] `.agents/simulator-architecture.md`
- [ ] `.agents/data-simulation.md`
- [ ] `.agents/observation-model.md`
- [ ] `.agents/scenarios.md`
- [ ] `.agents/hardware-proposal.md`
- [ ] `.agents/design-patterns.md`
- [ ] `.agents/configuration.md`
- [ ] `.agents/testing-plan.md`
- [ ] `.agents/device-protocol.md`
- [ ] `.agents/api-client.md`
- [ ] `.agents/security.md`
- [ ] `.agents/dashboard.md`

Mientras tanto, cualquier agente debe guiarse por la especificación canónica del backend.

## 6. Definition of Done

- [ ] `pytest`, `ruff` y `mypy` en verde; cobertura del dominio ≥ 90 %.
- [ ] Sin valores quemados y sin secretos; `.env.example` al día.
- [ ] Swagger (`/docs`) documenta los endpoints en español.
- [ ] Documentación y diagramas actualizados.
- [ ] Commits con la cuenta del integrante responsable y sin atribución a IA.
