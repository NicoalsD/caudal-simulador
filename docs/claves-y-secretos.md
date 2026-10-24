# Claves y secretos del simulador

El simulador maneja tres tipos de secreto: la contraseña de cada cuenta de la API, la clave privada Ed25519 de cada nodo simulado, y el token de acceso que obtiene al entrar. Ninguno se escribe en el código, en los YAML ni en git.

Especificación: [Seguridad](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Seguridad.md) y [Protocolo de dispositivos](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Protocolo-de-dispositivos.md), sección 2.

## 1. Dónde vive cada secreto

| Secreto | Dónde va | Quién lo lee | Git |
|---|---|---|---|
| Contraseñas de PROJECT_TEAM, OPERATOR y Junta | `.env` (variables `CAUDAL_SIM_API_PASSWORD` y `CAUDAL_SIM_LIVE_*_PASSWORD`) | El simulador, en memoria | Ignorado (`.env`). |
| Clave privada Ed25519 de cada nodo | `keys/ed25519-private.pem` | Solo el simulador, para firmar | Ignorada (`keys/` y `*.pem`). |
| Token de acceso de la API | Solo en memoria del proceso | El cliente de la API | Nunca se escribe. |

Los archivos del repositorio que sí se suben son `.env.example` (con marcadores, sin valores reales) y los YAML de escenarios. Un YAML con una contraseña o una clave debe rechazarse en la revisión. El simulador no imprime contraseñas, tokens ni la clave en ningún mensaje ni en los manifiestos.

## 2. Generar la clave de un nodo

```bash
mkdir -p keys
openssl genpkey -algorithm ed25519 -out keys/ed25519-private.pem
chmod 600 keys/ed25519-private.pem
```

Un nodo tiene una clave propia. No compartas la clave privada entre nodos ni la copies a otra máquina por un canal que no esté cifrado.

## 3. Registrar la clave pública en el backend

El backend solo recibe la clave **pública**. Se calcula desde la privada con este comando, que no imprime la privada:

```bash
uv run python -I - <<'PY'
import base64
from pathlib import Path
from cryptography.hazmat.primitives import serialization

key = serialization.load_pem_private_key(
    Path("keys/ed25519-private.pem").read_bytes(), password=None
)
raw = key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
)
print(base64.urlsafe_b64encode(raw).rstrip(b"=").decode())
PY
```

El valor que imprime (43 caracteres, base64url sin relleno) se envía a `POST /api/v1/devices/{id}/keys` con un usuario que tenga el permiso `DEVICE_REGISTER`. La respuesta trae el `fingerprint` de la clave. Compáralo con el que calcula `public_key_fingerprint` (módulo `caudal_sim.signing`, SHA-256 de la clave pública cruda en hexadecimal) antes de dar por buena la carga.

## 4. Rotar una clave

1. Genera una clave nueva (sección 2) en otra ruta, por ejemplo `keys/ed25519-private-2.pem`.
2. Registra su clave pública con `POST /api/v1/devices/{id}/keys`. La clave anterior sigue válida 7 días (configurable en el backend).
3. Cambia `CAUDAL_SIM_PRIVATE_KEY_PATH` a la clave nueva y prueba con una corrida corta (`caudal-sim live --max-hours 2 --sin-tablero`).
4. Si la clave anterior se filtró, revócala ya con `DELETE /api/v1/devices/{id}/keys/{keyId}`. Desde ese momento sus firmas dejan de aceptarse.
5. Borra la clave anterior del disco cuando ya no la necesites.

## 5. Si una clave o una contraseña se filtra

1. Revoca la clave en el backend (sección 4, paso 4) o cambia la contraseña de la cuenta.
2. Borra el archivo local del secreto y genera uno nuevo.
3. Si el secreto llegó a git, **no basta con borrarlo en un commit nuevo**: queda en el historial. Avisa a Drako Salazar (`Drako2305`), que responde por seguridad, y reescribe el historial solo con su aprobación.
4. El escaneo de secretos del CI (gitleaks) marca estos casos en cada cambio.

## 6. Reglas que el código ya cumple

- Las contraseñas se leen con `SecretStr` y no aparecen en `repr` ni en los mensajes de error.
- La clave se lee solo para firmar. Si el archivo no existe o no es Ed25519, el mensaje dice la ruta, nunca el contenido.
- El tablero local no tiene credenciales ni CORS, y su respuesta no incluye usuarios, tokens ni claves.
