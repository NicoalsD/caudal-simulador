# CAUDAL Simulador

Simulador virtual del acueducto (gemelo digital) en **Python 3.12**: como no hay datos reales de la región, genera lo que llegaría del campo (clima, fuente, tanque, consumo por sector, fugas, fontanero con errores humanos, sensores con fallas, válvulas motorizadas y reportes de la comunidad) y lo envía al backend **por las mismas puertas que usaría la realidad**. Incluye un tablero web.

## Estado

**Fase 0: planeación.** La especificación está en el backend: [Datos simulados](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Datos-simulados.md), [Simulador y hardware](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Simulador-y-hardware.md) y [Protocolo de dispositivos](https://github.com/NicoalsD/caudal-backend/blob/develop/docs/Protocolo-de-dispositivos.md). La implementación queda a cargo de Nicolas Mora (`nicomora70`) cuando se una al proyecto.

## Documentación

- [AGENTS.md](AGENTS.md): reglas obligatorias para personas y agentes.
- [Flujo de trabajo](.agents/workflow.md): cuentas, ramas, commits y PR.
- [Política de seguridad](SECURITY.md).

## Equipo

Nicolas Diaz (`NicoalsD`) · Drako Salazar (`Drako2305`) · Nicolas Mora (`nicomora70`). Proyecto de la materia Patrones de Software.
