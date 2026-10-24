# Despliegue del simulador

Este documento explica cómo correr el simulador en un equipo local, con `uv` o con la imagen de contenedor del `Dockerfile`, cómo configurarlo y cómo construir el tablero. Todo lo que el simulador produce es **simulado**.

**Destino de despliegue.** El repositorio no tiene un destino de despliegue configurado: no hay registro de imágenes, servidor, nube ni flujo de CI que publique la imagen. El CI (`.github/workflows/ci.yml`) solo valida el código Python, el tablero (incluido `pnpm build`) y busca secretos. El simulador está pensado para correr en el equipo de quien hace la demostración.

## 1. Requisitos

| Para | Necesitas |
|---|---|
| Correr con `uv` | Python 3.12 (`requires-python = ">=3.12,<3.13"`) y `uv`. |
| Construir el tablero fuera de la imagen | Node y `pnpm` (`packageManager: pnpm@12.6.0`, se activa con `corepack enable`). |
| Correr en contenedor | `podman` o `docker`. |
| Modo `live`, `demo` o `backfill` | El backend (`caudal-backend`) con un acueducto `is_demo = true`, las cuentas y la clave del nodo (ver [operacion-live.md](operacion-live.md#2-requisitos)). |

## 2. Modo local con `uv`

```bash
uv sync
cp .env.example .env        # y completa los valores (sección 4)
uv run caudal-sim --help
```

Comandos principales:

```bash
# Sin backend: genera datos en outputs/
uv run caudal-sim generate --scenario normal-year --days 365 --seed 42

# Con backend: importa 90 días de historial al acueducto demo
uv run caudal-sim backfill readings --scenario normal-year --days 90

# Con backend: simulación en vivo con el tablero en http://127.0.0.1:8000
uv run caudal-sim live --scenario normal-year --start 2026-10-10

# Solo el tablero
uv run caudal-sim tablero
```

El catálogo de escenarios y sus comandos está en [escenarios.md](escenarios.md).

## 3. Imagen de contenedor

El `Dockerfile` tiene dos etapas:

1. `dashboard-build` (`node:24-alpine`): `pnpm install --frozen-lockfile` y `pnpm build` del tablero.
2. `runtime` (`python:3.12-slim`): instala `uv` 0.12.15, ejecuta `uv sync --locked --no-dev`, copia `src/`, `scenarios/` y el tablero construido (`dashboard/dist`) y corre como el usuario sin privilegios `caudal` (UID 10001).

El punto de entrada es `caudal-sim` y el comando por defecto es `tablero`. La imagen fija `CAUDAL_SIM_DASHBOARD_HOST=0.0.0.0` y `CAUDAL_SIM_DASHBOARD_PORT=8000`, y expone el puerto 8000. Ninguna clave, contraseña ni `.env` entra a la imagen: `.dockerignore` excluye `.env`, `.env.*` (salvo `.env.example`), `keys/`, `*.pem`, `*.key` y `secrets/`.

### 3.1 Construir

```bash
# podman
podman build -t caudal-sim .

# docker
docker build -t caudal-sim .
```

Los argumentos `NODE_IMAGE`, `PYTHON_IMAGE`, `UV_VERSION`, `APP_USER` y `APP_UID` se pueden cambiar con `--build-arg`, por ejemplo `--build-arg UV_VERSION=0.12.15`.

### 3.2 Ejecutar el tablero

Publica el puerto **solo en loopback**, como indica el `Dockerfile`, porque la API del tablero no tiene autenticación:

```bash
# podman
podman run --rm -p 127.0.0.1:8000:8000 caudal-sim

# docker
docker run --rm -p 127.0.0.1:8000:8000 caudal-sim
```

Abre `http://127.0.0.1:8000` (tablero) y `http://127.0.0.1:8000/docs` (Swagger). Sin simulación en curso, el tablero muestra el estado vacío.

### 3.3 Ejecutar otros comandos

Lo que va después del nombre de la imagen reemplaza a `tablero`. Las variables se pasan con `--env-file` y la clave se monta en `/app/keys` (la ruta por defecto `keys/ed25519-private.pem` se resuelve desde `/app`), en solo lectura:

```bash
# podman (la opción :Z ajusta la etiqueta de SELinux del volumen)
podman run --rm -p 127.0.0.1:8000:8000 \
  --env-file .env \
  -v ./keys:/app/keys:ro,Z \
  caudal-sim live --scenario normal-year --start 2026-10-10

# docker
docker run --rm -p 127.0.0.1:8000:8000 \
  --env-file .env \
  -v ./keys:/app/keys:ro \
  caudal-sim live --scenario normal-year --start 2026-10-10
```

Tenlo en cuenta al usar la imagen:

- **Host del tablero.** `.env.example` trae `CAUDAL_SIM_DASHBOARD_HOST=127.0.0.1`. Si tu archivo de entorno lleva ese valor, reemplaza el `0.0.0.0` de la imagen y el tablero no se alcanza desde fuera del contenedor. Para el contenedor, usa `CAUDAL_SIM_DASHBOARD_HOST=0.0.0.0` en el archivo que pasas con `--env-file`; la exposición real la limita `-p 127.0.0.1:8000:8000`.
- **URL del backend.** Dentro del contenedor, `localhost` es el propio contenedor. `CAUDAL_SIM_API_BASE_URL=http://localhost:8080` no llega al backend que corre en tu equipo; usa una dirección alcanzable desde el contenedor.
- **Permisos.** `/app` pertenece a `root` y es de solo lectura para `caudal`. Los comandos que escriben archivos (`generate`, `export-actas`, `export-backtest` y `backfill`, que guarda su manifiesto firmado en `outputs/imports/`) necesitan un volumen escribible en `/app/outputs`, por ejemplo `-v ./outputs:/app/outputs`. El usuario del contenedor (UID 10001) debe poder leer la clave y escribir en ese volumen; con `podman` sin root, el mapeo de usuarios puede impedirlo.

## 4. Variables de entorno

Se leen de `.env` (o del entorno) con pydantic-settings. Copia `.env.example` a `.env` y completa los valores; `.env` está ignorado por git. Aquí no se muestran valores reales.

| Variable | Para qué sirve | Clase que la lee |
|---|---|---|
| `CAUDAL_SIM_API_BASE_URL` | URL base de `caudal-backend`, sin barra final. | `SimulatorSettings` |
| `CAUDAL_SIM_API_USERNAME` | Usuario PROJECT_TEAM que importa el historial. | `SimulatorSettings` |
| `CAUDAL_SIM_API_PASSWORD` | **Secreto.** Contraseña de ese usuario. | `SimulatorSettings` |
| `CAUDAL_SIM_DEMO_AQUEDUCT_SLUG` | Slug público del acueducto demo. Si no es demo, se cancela. | `SimulatorSettings` |
| `CAUDAL_SIM_AQUEDUCT_ID` | Identificador del acueducto demo en el backend. | `SimulatorSettings` |
| `CAUDAL_SIM_TANK_ID` | Identificador del tanque del acueducto demo. | `SimulatorSettings` |
| `CAUDAL_SIM_PRIVATE_KEY_PATH` | Ruta de la clave privada Ed25519 (por defecto `keys/ed25519-private.pem`). | `SimulatorSettings` |
| `CAUDAL_SIM_HTTP_TIMEOUT_SECONDS` | Tiempo máximo de cada llamada HTTP, en segundos (por defecto 10, mínimo 1). | `SimulatorSettings` |
| `CAUDAL_SIM_DASHBOARD_HOST` | Dirección donde escucha el tablero (por defecto `127.0.0.1`). | `DashboardSettings` |
| `CAUDAL_SIM_DASHBOARD_PORT` | Puerto del tablero (por defecto 8000). | `DashboardSettings` |
| `CAUDAL_SIM_LIVE_OPERATOR_USERNAME` | Usuario OPERATOR que envía las lecturas en `live`. | `LiveSettings` |
| `CAUDAL_SIM_LIVE_OPERATOR_PASSWORD` | **Secreto.** Contraseña del OPERATOR. | `LiveSettings` |
| `CAUDAL_SIM_LIVE_BOARD_USERNAME` | Usuario de la Junta, solo para `--auto-junta`. | `LiveSettings` |
| `CAUDAL_SIM_LIVE_BOARD_PASSWORD` | **Secreto.** Contraseña de la Junta, solo para `--auto-junta`. | `LiveSettings` |
| `CAUDAL_SIM_LIVE_DEVICE_ID` | Identificador del nodo de nivel simulado registrado en el backend. | `LiveSettings` |
| `CAUDAL_SIM_LIVE_HOUR_SECONDS` | Segundos reales por hora simulada a velocidad 1 (por defecto 1.0). | `LiveSettings` |

`generate`, `export-actas`, `export-backtest` y `tablero` no necesitan credenciales. `backfill` (también con `--dry-run`), `live` y `demo` sí: si falta una variable obligatoria o es inválida, el comando termina con código 2 y un mensaje que nombra esas variables, sin mostrar sus valores.

## 5. Puertos

| Puerto | Qué escucha | Dónde se cambia |
|---|---|---|
| 8000 | API del tablero, tablero construido (`/`) y Swagger (`/docs`). | `CAUDAL_SIM_DASHBOARD_PORT`, o `--port` en `caudal-sim tablero`. |
| Puerto de desarrollo de Vite | `pnpm dev` del tablero, con proxy de `/api` a `http://127.0.0.1:8000` (`dashboard/vite.config.ts`). | Configuración de Vite. |
| 8080 | El backend, según el valor de ejemplo de `CAUDAL_SIM_API_BASE_URL`. No lo abre el simulador. | `CAUDAL_SIM_API_BASE_URL`. |

## 6. Modo sin backend, `live` y `demo`

| Modo | Comandos | Contacta el backend | Necesita secretos |
|---|---|---|---|
| Sin backend | `generate`, `export-actas`, `export-backtest`, `tablero` | No | No |
| Ensayo del historial | `backfill ... --dry-run` | No: solo cuenta los lotes | Lee igual las variables de `SimulatorSettings` (sección 4), así que deben estar definidas |
| Historial | `backfill readings`, `backfill shift-executions`, `backfill incidents` | Sí, como PROJECT_TEAM | Contraseña PROJECT_TEAM y clave Ed25519 |
| En vivo | `live` | Sí, como OPERATOR (y Junta con `--auto-junta`) | Contraseñas y clave del nodo |
| Demostración | `demo` (escenario `presentation`, 3 días) | Sí, igual que `live` | Igual que `live` |

`live` y `demo` comparten la misma operación; `demo` añade el guion de fallos del escenario `presentation`. Antes de enviar nada, ambos y `backfill` comprueban que el acueducto de `CAUDAL_SIM_DEMO_AQUEDUCT_SLUG` tenga `is_demo = true`. Detalle completo: [operacion-live.md](operacion-live.md).

## 7. Claves y secretos

Las contraseñas van solo en `.env` y la clave privada Ed25519 en `keys/` (ignorados por git y por `.dockerignore`). En el contenedor se pasan en tiempo de ejecución con `--env-file` y un volumen de solo lectura, nunca dentro de la imagen. Cómo generar la clave, registrar la pública en el backend, rotarla y qué hacer si se filtra: [claves-y-secretos.md](claves-y-secretos.md).

## 8. Tablero

El tablero (Vite, React y TypeScript) está en `dashboard/`. La API lo sirve desde `dashboard/dist` cuando esa carpeta existe.

```bash
cd dashboard
corepack enable
pnpm install --frozen-lockfile

# Desarrollo: servidor de Vite con proxy de /api a la API del simulador
pnpm dev            # en otra terminal: uv run caudal-sim tablero

# Producción: tsc --noEmit y vite build, deja el resultado en dashboard/dist
pnpm build
```

Otros scripts de `dashboard/package.json`: `pnpm typecheck`, `pnpm lint`, `pnpm test` y `pnpm preview`. La imagen de contenedor construye el tablero por su cuenta, así que no hace falta `pnpm build` antes de `podman build`.

## 9. Límites conocidos

- **Sin destino de despliegue.** No hay imagen publicada ni servidor configurado (ver el inicio de este documento).
- **El tablero no tiene autenticación ni CORS.** Escucha en `127.0.0.1` por defecto; si escucha en otra dirección, el comando avisa. Publica el puerto del contenedor solo en `127.0.0.1`.
- **`LEAK` y `HEAVY_RAIN` no se aplican.** El tablero los acepta, pero el motor todavía no los aplica porque la simulación se calcula de antemano con la semilla; `live` lo reporta al final.
- **Comandos de válvula.** `live` no lee `GET /devices/commands`: el simulador no abre ni cierra válvulas.
- **Reloj cercano a hoy.** La API rechaza lecturas viejas con `422 TOO_OLD`; usa `--start` con una fecha reciente.
- **Buffer sin conexión limitado.** Guarda hasta `capacity_batches` lotes (500 en los escenarios del repositorio).
- **Imagen de solo lectura.** Los comandos que escriben archivos necesitan un volumen en `/app/outputs` (sección 3.3).
