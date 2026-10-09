"""Scenario builder: merges YAML files with overrides and validates at the end."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import ValidationError

from caudal_sim.scenario import Scenario, ScenarioError


class ScenarioBuilder:
    """Builds a scenario step by step from YAML files and overrides.

    Values accumulate without validation. Pydantic validation happens only once,
    in `build()`, which returns an immutable `Scenario` or raises `ScenarioError`.

    @pattern P04 Builder
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._sources: list[str] = []

    def from_yaml(self, path: Path) -> Self:
        """Merges a YAML file over what has been accumulated. Later values win."""
        raw = _read_yaml_mapping(path)
        self._data = _deep_merge(self._data, raw)
        self._sources.append(str(path))
        return self

    def override(self, dotted_key: str, value: object) -> Self:
        """Replaces a value by its dotted path, for example `meta.default_seed`."""
        keys = dotted_key.split(".")
        node: dict[str, Any] = self._data
        for key in keys[:-1]:
            child = node.setdefault(key, {})
            if not isinstance(child, dict):
                raise ScenarioError(f"la clave {dotted_key} no es un mapa en el escenario")
            node = child
        node[keys[-1]] = value
        return self

    def build(self) -> Scenario:
        """Validates the accumulated data and returns the scenario. Fails with ScenarioError."""
        origen = ", ".join(self._sources) or "sin archivo"
        try:
            return Scenario.model_validate(self._data)
        except ValidationError as error:
            detalles = "; ".join(
                f"{'.'.join(str(parte) for parte in item['loc'])}: {item['msg']}"
                for item in error.errors()
            )
            raise ScenarioError(f"escenario inválido ({origen}): {detalles}") from error


def load_scenario(path: Path) -> Scenario:
    """Shortcut to load a single validated YAML scenario."""
    return ScenarioBuilder().from_yaml(path).build()


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ScenarioError(f"no se puede leer el escenario {path}") from error
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ScenarioError(f"YAML inválido en {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ScenarioError(f"el escenario {path} debe ser un mapa YAML")
    return raw


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged
