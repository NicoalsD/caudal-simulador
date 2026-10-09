"""Snapshots of a simulation run: save the whole state and go back to it later.

A run is the originator: it knows its clock, its random generator and the components whose
state it saves. A snapshot is the memento: it is immutable and holds copies, so changing the
run after taking it does not change the snapshot. Restoring a snapshot and advancing gives the
same result as the run that produced it, because the random generator is saved too.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol, TypeVar

import numpy as np

from caudal_sim.simulation_step import SimulationStep

StateT = TypeVar("StateT")


class Snapshottable(Protocol[StateT]):
    """Interface of a component that can save and restore its own state."""

    def capture(self) -> StateT:
        """Saved state, independent of later changes to the component."""

    def restore(self, state: StateT) -> None:
        """Puts the component back in `state`."""


@dataclass(frozen=True)
class SimulationSnapshot:
    """Complete state of a run at an instant: clock, random generator and component states.

    @pattern P16 Memento
    """

    at: datetime
    rng_state: Mapping[str, Any]
    component_states: tuple[object, ...]


class SimulationRun:
    """Originator of the snapshots: advances its steps and saves or restores its components.

    All the steps and components share the same random generator, so their draws depend on
    the seed and on the order of the steps.
    """

    def __init__(
        self,
        start: datetime,
        rng: np.random.Generator,
        steps: Sequence[SimulationStep],
        components: Sequence[Snapshottable[Any]],
    ) -> None:
        self._now = start
        self._rng = rng
        self._steps = tuple(steps)
        self._components = tuple(components)

    @property
    def now(self) -> datetime:
        return self._now

    def advance(self, elapsed: timedelta) -> None:
        """Runs every step over `elapsed`, in order, and moves the clock forward."""
        for step in self._steps:
            step.run(self._now, elapsed)
        self._now += elapsed

    def create_snapshot(self) -> SimulationSnapshot:
        """Copies the current state of the run into a new snapshot."""
        return SimulationSnapshot(
            at=self._now,
            rng_state=copy.deepcopy(dict(self._rng.bit_generator.state)),
            component_states=tuple(component.capture() for component in self._components),
        )

    def restore(self, snapshot: SimulationSnapshot) -> None:
        """Goes back to a snapshot taken from a run with the same components."""
        if len(snapshot.component_states) != len(self._components):
            raise ValueError("el estado guardado no corresponde a los mismos componentes")
        self._now = snapshot.at
        self._rng.bit_generator.state = copy.deepcopy(dict(snapshot.rng_state))
        for component, state in zip(self._components, snapshot.component_states, strict=True):
            component.restore(state)
