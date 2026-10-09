"""Simulated field devices: the identity of each node and the factory that creates it.

A node is either a level sensor (tank) or a valve node (sector valve). Each node signs its
requests with its own Ed25519 key, so its identifier is a UUID that never changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

MAX_DEVICE_NAME_LENGTH = 60


class DeviceKind(StrEnum):
    """Kind of field node. Each kind has its own creator."""

    LEVEL_SENSOR = "LEVEL_SENSOR"
    VALVE_NODE = "VALVE_NODE"


@dataclass(frozen=True)
class SimulatedDevice:
    """Identity of one simulated node: its UUID, its name and its kind."""

    device_id: UUID
    name: str
    kind: DeviceKind


class DeviceCreator(ABC):
    """Creator of simulated devices. `create` checks the name and calls the factory method.

    Callers depend only on this class, so a new kind of node needs a new subclass and
    nothing else changes.

    @pattern P02 Factory Method
    """

    def create(self, device_id: UUID, name: str) -> SimulatedDevice:
        """Creates a device with a clean name, or raises `ValueError`."""
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("el nombre del dispositivo no puede estar vacío")
        if len(clean_name) > MAX_DEVICE_NAME_LENGTH:
            raise ValueError(
                f"el nombre del dispositivo no puede superar {MAX_DEVICE_NAME_LENGTH} caracteres"
            )
        return self.create_device(device_id, clean_name)

    @abstractmethod
    def create_device(self, device_id: UUID, name: str) -> SimulatedDevice:
        """Factory method: builds the concrete device. The name is already checked."""


class LevelSensorCreator(DeviceCreator):
    """Creates the level sensor of a tank."""

    def create_device(self, device_id: UUID, name: str) -> SimulatedDevice:
        return SimulatedDevice(device_id=device_id, name=name, kind=DeviceKind.LEVEL_SENSOR)


class ValveNodeCreator(DeviceCreator):
    """Creates the node that operates the valve of a sector."""

    def create_device(self, device_id: UUID, name: str) -> SimulatedDevice:
        return SimulatedDevice(device_id=device_id, name=name, kind=DeviceKind.VALVE_NODE)
