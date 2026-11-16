"""`caudal-sim maqueta-usb`: the physical maqueta with the Arduino UNO (user texts in Spanish).

Subcommands:
- `puertos`: lists the USB serial ports.
- `probar`: checks the UNO and shows the distance and the level for a few seconds.
- `servo`: moves one servo to an angle, to test the mechanics by hand.
- `calibrar`: guided calibration of the sensor and the servos; saves it in the YAML file.
- `correr`: connects the UNO to caudal-backend (telemetry and valve commands).
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Annotated

import httpx
import typer

from caudal_sim.maqueta_spec import MaquetaSpecError
from caudal_sim.maqueta_usb import (
    UsbMaquetaSpec,
    UsbSensorSpec,
    UsbServoSpec,
    build_usb_maqueta_device,
    load_usb_spec,
    save_usb_spec,
)
from caudal_sim.offline_buffer import BufferFullError
from caudal_sim.serial_link import (
    MAX_ANGLE_DEG,
    MIN_ANGLE_DEG,
    SerialLink,
    SerialLinkError,
    list_serial_ports,
    open_serial_link,
)

DEFAULT_USB_CONFIG = Path("scenarios/maqueta-usb.yaml")
EXIT_CONFIG_ERROR = 2
EXIT_DEVICE_ERROR = 6
DEFAULT_PROBE_SECONDS = 10.0
PROBE_INTERVAL_SECONDS = 1.0
CALIBRATION_SAMPLES = 7
CALIBRATION_GAP_SECONDS = 0.4
SERVO_SETTLE_SECONDS = 2.0

usb_app = typer.Typer(
    help="Maqueta física con Arduino UNO por USB: prueba, calibración y conexión con la API.",
    no_args_is_help=True,
)

ConfigOption = Annotated[Path, typer.Option("--config", help="Archivo de la maqueta USB (YAML).")]
PortOption = Annotated[
    str | None, typer.Option("--puerto", help="Puerto serie. Por defecto, el del archivo.")
]


def _spec_or_exit(path: Path) -> UsbMaquetaSpec:
    try:
        return load_usb_spec(path)
    except MaquetaSpecError as error:
        typer.echo(f"Error: {error.message}", err=True)
        raise typer.Exit(code=EXIT_CONFIG_ERROR) from error


def _link_or_exit(spec: UsbMaquetaSpec, port: str | None) -> SerialLink:
    name = port or spec.serial.port
    try:
        link = open_serial_link(
            name, spec.serial.baud, ready_timeout_seconds=spec.serial.ready_timeout_seconds
        )
    except SerialLinkError as error:
        typer.echo(f"Error: {error.message}", err=True)
        raise typer.Exit(code=EXIT_DEVICE_ERROR) from error
    typer.echo(f"Arduino conectado en {name}.")
    return link


def _fail(error: SerialLinkError) -> typer.Exit:
    typer.echo(f"Error: {error.message}", err=True)
    return typer.Exit(code=EXIT_DEVICE_ERROR)


@usb_app.command("puertos")
def ports() -> None:
    """Lista los puertos serie USB conectados."""
    found = list_serial_ports()
    if not found:
        typer.echo("No hay puertos serie. Conecta el Arduino y revisa el cable USB.")
        return
    for device, description in found:
        typer.echo(f"{device}\t{description}")


@usb_app.command("probar")
def probe(
    *,
    config: ConfigOption = DEFAULT_USB_CONFIG,
    port: PortOption = None,
    seconds: Annotated[float, typer.Option(help="Segundos de lectura.", min=1.0)] = (
        DEFAULT_PROBE_SECONDS
    ),
) -> None:
    """Comprueba el Arduino y muestra la distancia y el nivel calibrado, una vez por segundo."""
    spec = _spec_or_exit(config)
    link = _link_or_exit(spec, port)
    try:
        info = link.info()
        typer.echo(f"Firmware caudal-uno {info.version}.")
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            distance = link.distance_mm()
            if distance is None:
                typer.echo("Sin eco: revisa el HC-SR04 o apúntalo al agua.")
            else:
                level = spec.sensor.level_m(distance)
                full = level / spec.sensor.max_level_m * 100
                typer.echo(f"Distancia {distance} mm, nivel {level:.3f} m ({full:.0f} %)")
            time.sleep(PROBE_INTERVAL_SECONDS)
    except SerialLinkError as error:
        raise _fail(error) from error
    finally:
        link.close()


@usb_app.command("servo")
def servo(
    number: Annotated[int, typer.Argument(help="Servo 1 o 2.", min=1, max=2)],
    angle: Annotated[
        int, typer.Argument(help="Ángulo en grados.", min=MIN_ANGLE_DEG, max=MAX_ANGLE_DEG)
    ],
    *,
    config: ConfigOption = DEFAULT_USB_CONFIG,
    port: PortOption = None,
) -> None:
    """Mueve un servo a un ángulo, para probar la mecánica a mano."""
    spec = _spec_or_exit(config)
    link = _link_or_exit(spec, port)
    try:
        link.move_servo(number, angle)
        _wait_servo(link, number, angle)
        typer.echo(f"Servo {number} en {angle} grados.")
    except SerialLinkError as error:
        raise _fail(error) from error
    finally:
        link.close()


def _wait_servo(link: SerialLink, number: int, angle: int) -> None:
    end = time.monotonic() + SERVO_SETTLE_SECONDS
    while not link.reached(number, angle) and time.monotonic() < end:
        link.ping()


def _median_distance(link: SerialLink) -> int | None:
    values: list[int] = []
    for _ in range(CALIBRATION_SAMPLES):
        distance = link.distance_mm()
        if distance is not None:
            values.append(distance)
        time.sleep(CALIBRATION_GAP_SECONDS)
    return round(statistics.median(values)) if values else None


def _measure(link: SerialLink, prompt: str, current: int) -> int:
    typer.echo(prompt)
    while True:
        answer = typer.prompt(
            f"Enter para medir, un número para escribirlo a mano, o 's' para dejar {current} mm",
            default="",
            show_default=False,
        ).strip()
        if answer.lower() == "s":
            return current
        if answer.isdigit():
            return int(answer)
        distance = _median_distance(link)
        if distance is None:
            typer.echo("Sin eco. Revisa el sensor y vuelve a intentar.")
            continue
        typer.echo(f"Medido: {distance} mm.")
        if typer.confirm("¿Lo guardo?", default=True):
            return distance


def _calibrate_sensor(link: SerialLink, sensor: UsbSensorSpec) -> UsbSensorSpec:
    typer.echo("\n== Sensor de nivel (HC-SR04) ==")
    empty = _measure(
        link,
        "Deja la botella VACÍA (o sin agua bajo el sensor) con el sensor ya montado arriba.",
        sensor.empty_distance_mm,
    )
    full = _measure(
        link, "Llena la botella hasta el nivel MÁXIMO que vas a usar.", sensor.full_distance_mm
    )
    try:
        return UsbSensorSpec(
            empty_distance_mm=empty, full_distance_mm=full, blind_zone_mm=sensor.blind_zone_mm
        )
    except ValueError as error:
        typer.echo(f"Calibración inválida: {error}. Se deja la anterior.", err=True)
        return sensor


def _jog(link: SerialLink, number: int, label: str, current: int) -> int:
    typer.echo(f"Busca el ángulo {label}. Escribe un ángulo para probarlo; Enter lo acepta.")
    angle = current
    link.move_servo(number, angle)
    _wait_servo(link, number, angle)
    while True:
        answer = typer.prompt(f"Servo {number} en {angle} grados", default="", show_default=False)
        answer = answer.strip()
        if not answer:
            return angle
        if not answer.isdigit() or not MIN_ANGLE_DEG <= int(answer) <= MAX_ANGLE_DEG:
            typer.echo("Escribe un número de 0 a 180.")
            continue
        angle = int(answer)
        link.move_servo(number, angle)
        _wait_servo(link, number, angle)


def _calibrate_servo(link: SerialLink, number: int, servo: UsbServoSpec) -> UsbServoSpec:
    typer.echo(f"\n== Servo {number} ({servo.name}) ==")
    open_deg = _jog(
        link, number, "ABIERTO (la manguera queda libre y el agua pasa)", servo.open_deg
    )
    closed_deg = _jog(
        link,
        number,
        "CERRADO (la manguera queda pisada y no gotea; sin forzar el servo)",
        servo.closed_deg,
    )
    try:
        return UsbServoSpec(name=servo.name, open_deg=open_deg, closed_deg=closed_deg)
    except ValueError as error:
        typer.echo(f"Calibración inválida: {error}. Se deja la anterior.", err=True)
        return servo


@usb_app.command("calibrar")
def calibrate(
    *,
    config: ConfigOption = DEFAULT_USB_CONFIG,
    port: PortOption = None,
    sensor_only: Annotated[bool, typer.Option("--solo-sensor", help="No calibra servos.")] = False,
    servos_only: Annotated[bool, typer.Option("--solo-servos", help="No calibra el sensor.")] = (
        False
    ),
) -> None:
    """Calibración guiada del sensor y de los dos servos. Guarda el resultado en el YAML."""
    spec = _spec_or_exit(config)
    link = _link_or_exit(spec, port)
    try:
        sensor = spec.sensor if servos_only else _calibrate_sensor(link, spec.sensor)
        servos = spec.servos
        if not sensor_only:
            servos = tuple(
                _calibrate_servo(link, number, servo)
                for number, servo in enumerate(spec.servos, start=1)
            )
            for number, servo_spec in enumerate(servos, start=1):
                link.move_servo(number, servo_spec.closed_deg)
    except SerialLinkError as error:
        raise _fail(error) from error
    finally:
        link.close()
    serial = spec.serial.model_copy(update={"port": port}) if port else spec.serial
    updated = spec.model_copy(update={"sensor": sensor, "servos": servos, "serial": serial})
    save_usb_spec(updated, config)
    typer.echo(
        f"\nGuardado en {config}: vacío {sensor.empty_distance_mm} mm, lleno "
        f"{sensor.full_distance_mm} mm (nivel máximo {sensor.max_level_m:.3f} m); "
        + "; ".join(f"{s.name}: abierto {s.open_deg}°, cerrado {s.closed_deg}°" for s in servos)
    )


@usb_app.command("correr")
def run(
    *,
    config: ConfigOption = DEFAULT_USB_CONFIG,
    port: PortOption = None,
    api_url: Annotated[
        str | None,
        typer.Option(
            help="URL base de caudal-backend. Por defecto, CAUDAL_SIM_MAQUETA_API_BASE_URL."
        ),
    ] = None,
    seconds: Annotated[
        float | None,
        typer.Option(help="Segundos de la corrida. Sin valor, corre hasta Ctrl+C.", min=0.0),
    ] = None,
) -> None:
    """Conecta el Arduino con caudal-backend: nivel real y comandos de las dos llaves.

    Ejecuta lo que manda la app o el piloto. Usa las identidades de la maqueta del .env.
    """
    from caudal_sim.cli import (  # noqa: PLC0415 - avoids a cycle: cli registers this app
        _maqueta_identities_or_exit,
        _maqueta_settings_or_exit,
        _print_maqueta_report,
    )

    spec = _spec_or_exit(config)
    settings = _maqueta_settings_or_exit()
    identities = _maqueta_identities_or_exit(settings)
    link = _link_or_exit(spec, port)
    base_url = api_url or settings.api_base_url
    try:
        with httpx.Client(base_url=base_url, timeout=settings.http_timeout_seconds) as http:
            device = build_usb_maqueta_device(spec, identities, http, link)
            typer.echo(f"Maqueta USB conectada a {base_url}. Ctrl+C para salir.")
            try:
                report = device.run(seconds)
            except KeyboardInterrupt:
                report = device.finish()
            except BufferFullError as error:
                typer.echo(f"Error: {error}", err=True)
                _print_maqueta_report(device.report)
                raise typer.Exit(code=EXIT_DEVICE_ERROR) from error
    except SerialLinkError as error:
        raise _fail(error) from error
    finally:
        link.close()
    _print_maqueta_report(report)
