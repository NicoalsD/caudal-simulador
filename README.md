# CAUDAL Simulador

Simulador en **Python 3.12** de datos y hardware para CAUDAL B2B. Como no hay datos reales de clientes, genera datos simulados (clima, fuente, tanque, consumo por línea de servicio, fugas, operador con errores humanos, sensores con fallas y válvulas motorizadas) y los envía al backend **por las mismas puertas que usaría la realidad**, a instituciones simuladas. Incluye un tablero web y el puente USB de la maqueta física (`maqueta-usb`).

## Estado

El simulador tiene el modo de simulación con escenarios, el modo en vivo (`live`), el guion de demostración (`demo`), el tablero local y, desde la Fase 13 de CAUDAL v2, la **maqueta virtual** (`caudal-sim maqueta`): un tanque con bomba, flotador y dos salidas que habla con la API por el protocolo de dispositivos firmado, envía su nivel y ejecuta los comandos de sus válvulas. La especificación está en el backend: [Datos simulados](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Datos-simulados.md), [Simulador y hardware](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Simulador-y-hardware.md) y [Protocolo de dispositivos](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Protocolo-de-dispositivos.md).

**Alcance B2B (2026-11-20).** Las instituciones simuladas reciben los escenarios. El puente `maqueta-usb` (Arduino UNO por USB) hoy envía `LEVEL` en metros cada 20 s y lee su calibración del YAML. En el modelo B2B enviará `DISTANCE` en mm cada ~2 s y leerá `GET /devices/config` (por implementar).

## Maqueta virtual

```bash
# Corre la maqueta virtual contra la API durante 10 minutos (sin --seconds, corre hasta Ctrl+C)
uv run caudal-sim maqueta --scenario scenarios/maqueta.yaml --api-url http://localhost:8080 --seconds 600
```

Requiere tres dispositivos firmados registrados en el backend (el sensor del tanque y un actuador por salida) y sus claves en `keys/`. Detalle, variables de entorno y límites conocidos: [operacion-live.md, sección 7](docs/operacion-live.md#7-maqueta-virtual-caudal-sim-maqueta). Los datos son simulados.

## Documentación

- [AGENTS.md](AGENTS.md): reglas obligatorias para personas y agentes.
- [Flujo de trabajo](.agents/workflow.md): cuentas, ramas, commits y PR.
- [Política de seguridad](SECURITY.md).
- [Escenarios](docs/escenarios.md): catálogo de escenarios YAML, sus supuestos y cómo crear uno nuevo.
- [Operación en vivo](docs/operacion-live.md): modo `live`, guion `demo`, tablero y maqueta virtual.
- [Despliegue](docs/despliegue.md): ejecución local y en contenedor, variables de entorno, puertos y tablero.

## Equipo

Nicolas Diaz (`NicoalsD`) · Drako Salazar (`Drako2305`) · Nicolas Mora (`nicomora70`). Proyecto de la materia Patrones de Software.
