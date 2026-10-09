"""ScenarioBuilder tests: YAML merging, overrides and final validation."""

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from caudal_sim.builder import ScenarioBuilder, load_scenario
from caudal_sim.scenario import Scenario, ScenarioError

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal.yaml"
SEED_MAX = 2**32 - 1
OVERRIDDEN_GAUGE = 1.5
OVERRIDDEN_SEED = 7


def test_builder_from_normal_yaml_matches_load_scenario() -> None:
    built = ScenarioBuilder().from_yaml(NORMAL_YAML).build()

    assert built == load_scenario(NORMAL_YAML)
    assert isinstance(built, Scenario)


def test_override_changes_the_seed_without_touching_the_file() -> None:
    before = NORMAL_YAML.read_text(encoding="utf-8")

    scenario = (
        ScenarioBuilder()
        .from_yaml(NORMAL_YAML)
        .override("meta.default_seed", OVERRIDDEN_SEED)
        .build()
    )

    assert scenario.meta.default_seed == OVERRIDDEN_SEED
    assert NORMAL_YAML.read_text(encoding="utf-8") == before


def test_later_yaml_overrides_earlier_values(tmp_path: Path) -> None:
    extra = tmp_path / "extra.yaml"
    extra.write_text(f"tank:\n  initial_gauge: {OVERRIDDEN_GAUGE}\n", encoding="utf-8")

    scenario = ScenarioBuilder().from_yaml(NORMAL_YAML).from_yaml(extra).build()

    assert scenario.tank.initial_gauge == OVERRIDDEN_GAUGE
    assert scenario.tank.gauge_max == load_scenario(NORMAL_YAML).tank.gauge_max


def test_unknown_override_key_is_rejected_at_build() -> None:
    builder = ScenarioBuilder().from_yaml(NORMAL_YAML).override("meta.semilla_inventada", 1)

    with pytest.raises(ScenarioError, match="Extra inputs are not permitted"):
        builder.build()


def test_invalid_value_is_rejected_at_build() -> None:
    builder = ScenarioBuilder().from_yaml(NORMAL_YAML).override("tank.gauge_min", 9.0)

    with pytest.raises(ScenarioError, match="gauge_min debe ser menor"):
        builder.build()


def test_override_through_a_non_mapping_is_rejected() -> None:
    builder = ScenarioBuilder().from_yaml(NORMAL_YAML)

    with pytest.raises(ScenarioError, match="no es un mapa"):
        builder.override("meta.name.inside", "x")


@given(seed=st.integers(min_value=0, max_value=SEED_MAX))
def test_any_valid_seed_is_carried_into_the_scenario(seed: int) -> None:
    scenario = ScenarioBuilder().from_yaml(NORMAL_YAML).override("meta.default_seed", seed).build()

    assert scenario.meta.default_seed == seed
