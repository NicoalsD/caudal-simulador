"""Tests of shift compliance from the published schedule."""

from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from caudal_sim.builder import load_scenario
from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.scenario import ScheduleSpec, TurnSpec
from caudal_sim.shifts import ShiftOutcome, ShiftSimulator

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal.yaml"
SEED_MAX = 2**32 - 1
LONG_RUN_DAYS = 2000
OUTCOME_TOLERANCE = 0.03
SIMULATED_DAYS = 2
ALL_COMPLETED = 1.0
ALL_PARTIAL = 1.0
ALL_NOT_EXECUTED = 1.0
PROBABILITY_SUM_MISMATCH = 0.5


def _schedule(p_completed: float, p_partial: float, p_not_executed: float) -> ScheduleSpec:
    scenario = load_scenario(NORMAL_YAML)
    return scenario.schedule.model_copy(
        update={
            "p_completed": p_completed,
            "p_partial": p_partial,
            "p_not_executed": p_not_executed,
        }
    )


def _single_turn_schedule(p_completed: float, p_partial: float) -> ScheduleSpec:
    """Schedule with a single shift (the scenario's first one), to isolate its window."""
    schedule = _schedule(p_completed, p_partial, 1.0 - p_completed - p_partial)
    return schedule.model_copy(update={"turns": [schedule.turns[0]]})


def _sector_ids() -> list[str]:
    return [sector.id for sector in load_scenario(NORMAL_YAML).sectors]


def test_completed_turns_open_the_whole_window() -> None:
    simulator = ShiftSimulator(_single_turn_schedule(ALL_COMPLETED, 0.0), _sector_ids())
    turn = load_scenario(NORMAL_YAML).schedule.turns[0]

    run = simulator.simulate(1, np.random.default_rng(1))
    opened = np.flatnonzero(run.valve_open[turn.sector])

    assert opened.tolist() == list(range(turn.start_hour, turn.end_hour))


def test_partial_turns_close_halfway_through_the_window() -> None:
    simulator = ShiftSimulator(_single_turn_schedule(0.0, ALL_PARTIAL), _sector_ids())
    turn = load_scenario(NORMAL_YAML).schedule.turns[0]
    window = turn.end_hour - turn.start_hour

    run = simulator.simulate(1, np.random.default_rng(1))
    opened = np.flatnonzero(run.valve_open[turn.sector])

    assert opened.tolist() == list(range(turn.start_hour, turn.start_hour + window // 2))


def test_not_executed_turns_never_open_the_valve() -> None:
    simulator = ShiftSimulator(_schedule(0.0, 0.0, ALL_NOT_EXECUTED), _sector_ids())

    run = simulator.simulate(SIMULATED_DAYS, np.random.default_rng(1))

    assert all(not valve.any() for valve in run.valve_open.values())
    assert all(item.outcome is ShiftOutcome.NOT_EXECUTED for item in run.executions)


def test_outcome_frequencies_approach_the_configured_probabilities() -> None:
    schedule = load_scenario(NORMAL_YAML).schedule
    simulator = ShiftSimulator(schedule, _sector_ids())

    run = simulator.simulate(LONG_RUN_DAYS, np.random.default_rng(2026))
    total = len(run.executions)
    completed = sum(item.outcome is ShiftOutcome.COMPLETED for item in run.executions) / total

    assert abs(completed - schedule.p_completed) < OUTCOME_TOLERANCE


@settings(max_examples=100)
@given(seed=st.integers(min_value=0, max_value=SEED_MAX))
def test_open_valves_only_during_the_published_windows(seed: int) -> None:
    schedule = load_scenario(NORMAL_YAML).schedule
    simulator = ShiftSimulator(schedule, _sector_ids())

    run = simulator.simulate(SIMULATED_DAYS, np.random.default_rng(seed))

    for sector_id, valve in run.valve_open.items():
        allowed = np.zeros(SIMULATED_DAYS * HOURS_PER_DAY, dtype=np.bool_)
        for day in range(SIMULATED_DAYS):
            for turn in schedule.turns:
                if turn.sector == sector_id:
                    start = day * HOURS_PER_DAY + turn.start_hour
                    allowed[start : start + (turn.end_hour - turn.start_hour)] = True
        assert not np.any(valve & ~allowed)


def test_turn_that_ends_before_it_starts_is_rejected() -> None:
    with pytest.raises(ValidationError, match="start_hour debe ser menor"):
        TurnSpec(sector="alto", start_hour=9, end_hour=5)


def test_probabilities_must_add_up_to_one() -> None:
    with pytest.raises(ValidationError, match="deben sumar 1"):
        ScheduleSpec.model_validate(
            {
                "turns": [{"sector": "alto", "start_hour": 5, "end_hour": 9}],
                "p_completed": PROBABILITY_SUM_MISMATCH,
                "p_partial": 0.0,
                "p_not_executed": 0.0,
            }
        )


def test_unknown_sector_in_the_schedule_is_rejected() -> None:
    schedule = load_scenario(NORMAL_YAML).schedule

    with pytest.raises(ValueError, match="sectores desconocidos"):
        ShiftSimulator(schedule, ["solo-uno"])
