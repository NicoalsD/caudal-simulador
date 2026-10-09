"""Reloj de la simulación: fuente única de tiempo y de números aleatorios reproducibles."""

from __future__ import annotations

import zlib
from datetime import datetime, timedelta
from typing import ClassVar

import numpy as np

RNG_STREAM_NAME_ENCODING = "utf-8"


class SimulationClock:
    """Reloj único de la simulación y fábrica de flujos aleatorios reproducibles.

    Todos los actores leen el tiempo y el azar desde esta instancia. Cada flujo se
    identifica por nombre: agregar un componente nuevo (por ejemplo, las fugas) no cambia
    los datos de los demás (por ejemplo, la lluvia).

    @pattern P01 Singleton
    """

    _instance: ClassVar[SimulationClock | None] = None
    _start: datetime | None
    _seed: int | None

    def __new__(cls) -> SimulationClock:
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._start = None
            instance._seed = None
            cls._instance = instance
        return cls._instance

    def configure(self, start: datetime, seed: int) -> None:
        """Fija el inicio (con zona horaria) y la semilla. Puede llamarse de nuevo al reiniciar."""
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("el inicio de la simulación debe tener zona horaria")
        if seed < 0:
            raise ValueError("la semilla debe ser un entero no negativo")
        self._start = start
        self._seed = seed

    @property
    def start(self) -> datetime:
        """Instante de la hora 0 de la simulación."""
        if self._start is None:
            raise RuntimeError("el reloj de la simulación no está configurado")
        return self._start

    @property
    def seed(self) -> int:
        """Semilla de la corrida actual."""
        if self._seed is None:
            raise RuntimeError("el reloj de la simulación no está configurado")
        return self._seed

    def timestamp_at(self, hour_index: int) -> datetime:
        """Instante correspondiente a una hora de la simulación (0 es el inicio)."""
        return self.start + timedelta(hours=hour_index)

    def stream(self, name: str) -> np.random.Generator:
        """Flujo aleatorio con nombre estable: misma semilla y mismo nombre, misma secuencia."""
        spawn_key = zlib.crc32(name.encode(RNG_STREAM_NAME_ENCODING))
        sequence = np.random.SeedSequence(entropy=self.seed, spawn_key=(spawn_key,))
        return np.random.Generator(np.random.PCG64(sequence))
