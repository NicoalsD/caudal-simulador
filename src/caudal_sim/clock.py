"""Simulation clock: single source of time and reproducible random numbers."""

from __future__ import annotations

import zlib
from datetime import datetime, timedelta
from typing import ClassVar

import numpy as np

RNG_STREAM_NAME_ENCODING = "utf-8"
HOURS_PER_DAY = 24


class SimulationClock:
    """Single simulation clock and factory of reproducible random streams.

    Every actor reads time and randomness from this instance. Each stream is
    identified by name: adding a new component (for example, leaks) does not change
    the data of the others (for example, rain).

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
        """Sets the start (with time zone) and the seed. Can be called again to restart."""
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("el inicio de la simulación debe tener zona horaria")
        if seed < 0:
            raise ValueError("la semilla debe ser un entero no negativo")
        self._start = start
        self._seed = seed

    @property
    def start(self) -> datetime:
        """Instant of hour 0 of the simulation."""
        if self._start is None:
            raise RuntimeError("el reloj de la simulación no está configurado")
        return self._start

    @property
    def seed(self) -> int:
        """Seed of the current run."""
        if self._seed is None:
            raise RuntimeError("el reloj de la simulación no está configurado")
        return self._seed

    def timestamp_at(self, hour_index: int) -> datetime:
        """Instant corresponding to a simulation hour (0 is the start)."""
        return self.start + timedelta(hours=hour_index)

    def stream(self, name: str) -> np.random.Generator:
        """Named random stream: same seed and same name, same sequence."""
        spawn_key = zlib.crc32(name.encode(RNG_STREAM_NAME_ENCODING))
        sequence = np.random.SeedSequence(entropy=self.seed, spawn_key=(spawn_key,))
        return np.random.Generator(np.random.PCG64(sequence))
