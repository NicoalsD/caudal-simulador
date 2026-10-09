# Política de seguridad

Gracias por ayudar a proteger CAUDAL. Este repositorio contiene `caudal-simulador`, el simulador de datos de la región y del hardware propuesto. Genera datos simulados, los envía a la API del backend como si fueran un fontanero o un dispositivo, y ofrece un tablero local. No contiene datos reales de personas ni del acueducto.

La política global de seguridad del proyecto, con las reglas del backend, la base de datos y la infraestructura, está en [`docs/Seguridad.md`](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Seguridad.md) del repositorio `caudal-backend`. Este documento solo cubre lo que pasa en `caudal-simulador`.

## Versiones soportadas

| Versión | Soporte de seguridad |
|---|---|
| Última versión etiquetada en `main` | Sí |
| Versiones anteriores a la última etiqueta | No |
| Rama `develop` | No garantizada (es la rama de integración) |

Propuesta a confirmar: la política de versiones soportadas se revisará al publicar la versión `v1.0.0` del proyecto.

## Cómo reportar una vulnerabilidad

**No abras un issue público, un PR ni un comentario** con los detalles de una vulnerabilidad. Esto incluye cualquier clave privada o credencial que encuentres, aunque sea simulada.

Repórtala de forma privada:

1. Ve a la pestaña **Security** del repositorio.
2. Elige **Report a vulnerability** (reporte privado de vulnerabilidades de GitHub).
3. Completa el formulario con la información que se indica abajo.

Solo los integrantes del equipo con acceso al repositorio pueden leer el reporte.

## Qué incluir en el reporte

- Descripción breve del problema y el tipo de riesgo (por ejemplo, clave privada versionada, credencial en un escenario YAML, firma que se puede falsificar, repetición de solicitudes aceptada).
- Archivo o componente afectado (por ejemplo, el módulo de firmas o un escenario) y versión o commit.
- Pasos para reproducirlo.
- Impacto esperado.
- Evidencia mínima. Si la evidencia contiene una clave o una credencial, **no la publiques en el reporte**: indica la ruta y el commit donde aparece, y el equipo la rotará.
- Propuesta de corrección, si la tienes (opcional).

## Tiempos de respuesta

| Etapa | Tiempo objetivo |
|---|---|
| Acuse de recibo | Por definir |
| Confirmación o descarte del problema | Por definir |
| Corrección o plan de mitigación | Por definir |
| Publicación de la corrección y, si aplica, del aviso | Por definir |

Los tiempos se confirmarán antes de la versión `v1.0.0`. Mientras tanto, son objetivos y no garantías.

## Alcance

**Dentro del alcance:**

- El código de este repositorio: generación de datos, escenarios, cliente de la API, firmas de dispositivos y tablero local.
- El manejo de claves privadas Ed25519 y de credenciales simuladas: su generación, su almacenamiento local y su uso.
- La construcción de las firmas de las solicitudes de dispositivo.
- Las rutas de la API local del tablero (FastAPI y SSE).
- La configuración de `.gitignore` y de los archivos de ejemplo (`.env.example`).

**Fuera del alcance:**

- Vulnerabilidades del backend, la base de datos o el servicio de IA. Repórtalas según la política global o en el repositorio correspondiente.
- Servicios de terceros. Repórtalos a cada proveedor.
- Pruebas contra cualquier sistema de agua real. El proyecto no tiene sistemas reales conectados. Cualquier prueba debe usar el entorno del proyecto.

## Reglas para quien investiga

- Prueba solo en tu entorno local o en el entorno de pruebas que indique el equipo.
- No intentes conectar el simulador a un sistema que no sea del proyecto.
- No copies claves ni credenciales a un reporte, a un issue ni a un chat.

## Notas de seguridad del simulador

Estas notas describen el diseño y no sustituyen el reporte. Están sujetas a confirmación técnica:

- **Claves privadas Ed25519.** Se generan localmente y se guardan solo en el directorio de claves, que está ignorado por git (`keys/` o `secrets/`), o en archivos `*.pem` o `*.key` que también están ignorados. Nunca se escriben en escenarios YAML, en la documentación ni en el código.
- **Credenciales simuladas.** Contraseñas y tokens de los usuarios simulados (fontanero y, si aplica, usuario simulado de la Junta con `--auto-junta`) se leen de `.env`. Nunca van en YAML. El archivo `.env` está ignorado por git. Solo se versiona `.env.example`, con marcadores.
- **Escenarios sin secretos.** Los archivos YAML de escenarios describen parámetros (clima, fuente, tanque, sectores, fallas). No contienen credenciales, claves ni URLs con credenciales.
- **Firmas de dispositivo.** Ed25519 sobre `método\nruta\ntimestamp\nnonce\nsha256(cuerpo)`, en base64url, con las cabeceras `X-Device-Id`, `X-Timestamp`, `X-Nonce` y `X-Signature`. El backend acepta una ventana de ±300 s y rechaza un nonce repetido durante 10 min. El simulador no debe reutilizar nonces.
- **Rotación de claves.** Si una clave de dispositivo se expone, se revoca y se registra una clave nueva con `POST /devices/{id}/keys`. El procedimiento completo está en la documentación del backend.
- **Datos solo simulados.** Las importaciones (`backfill`) solo llegan al acueducto demo (`aqueducts.is_demo = true`). La UI, la página pública y las actas muestran "Datos simulados".
- **Salidas.** Los datasets, la verdad de terreno y los resultados viven en `outputs/`, ignorado por git. La verdad de terreno nunca se envía al backend.
- **Tablero local.** La API local del tablero es para uso en la máquina del equipo. No se publica en una red abierta. Por definir si se protege con un token local.

Relacionados: [Política global de seguridad](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Seguridad.md), [Política de seguridad del servicio de IA](https://github.com/NicoalsD/caudal-ia/blob/develop/SECURITY.md), [Validación de entradas del backend](https://github.com/NicoalsD/caudal-backend/blob/develop/.agents/input-validation.md)
