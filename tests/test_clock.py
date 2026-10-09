"""Tests of the simulation clock (Singleton) and its random streams."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from caudal_sim.clock import SimulationClock

BOGOTA = ZoneInfo("America/Bogota")
SEED_MAX = 2**32 - 1
START = datetime(2026, 1, 1, tzinfo=BOGOTA)
RECONFIGURED_SEED = 2


def _fresh_clock() -> SimulationClock:
    """Resets the Singleton so each test starts without previous configuration."""
    SimulationClock._instance = None
    return SimulationClock()


def test_clock_is_a_single_instance() -> None:
    clock = _fresh_clock()

    assert clock is SimulationClock()


def test_reconfiguring_keeps_the_same_instance() -> None:
    first = _fresh_clock()
    first.configure(START, seed=1)

    second = SimulationClock()
    second.configure(START, seed=RECONFIGURED_SEED)

    assert first is second
    assert first.seed == RECONFIGURED_SEED


def test_clock_refuses_to_run_before_configuration() -> None:
    clock = _fresh_clock()

    with pytest.raises(RuntimeError, match="no está configurado"):
        _ = clock.start
    with pytest.raises(RuntimeError, match="no está configurado"):
        clock.stream("lluvia")


def test_naive_start_is_rejected() -> None:
    naive_start = datetime(2026, 1, 1)  # no time zone on purpose

    with pytest.raises(ValueError, match="zona horaria"):
        _fresh_clock().configure(naive_start, seed=1)


def test_timestamp_at_counts_whole_hours_from_start() -> None:
    clock = _fresh_clock()
    clock.configure(START, seed=1)
    hours_later = 25

    assert clock.timestamp_at(hours_later) == START + timedelta(hours=hours_later)
    assert clock.timestamp_at(0).tzinfo is not None


def test_timestamps_are_timezone_aware_utc_comparable() -> None:
    clock = _fresh_clock()
    clock.configure(datetime(2026, 1, 1, tzinfo=UTC), seed=1)

    assert clock.timestamp_at(0) == datetime(2026, 1, 1, tzinfo=UTC)


@given(seed=st.integers(min_value=0, max_value=SEED_MAX), name=st.text(min_size=1, max_size=20))
def test_same_seed_and_stream_name_give_the_same_numbers(seed: int, name: str) -> None:
    clock = _fresh_clock()
    clock.configure(START, seed=seed)

    first = clock.stream(name).random(16)
    second = clock.stream(name).random(16)

    np.testing.assert_array_equal(first, second)


@given(seed=st.integers(min_value=0, max_value=SEED_MAX))
def test_different_stream_names_are_independent(seed: int) -> None:
    clock = _fresh_clock()
    clock.configure(START, seed=seed)

    rain = clock.stream("lluvia").random(16)
    leaks = clock.stream("fugas").random(16)

    assert not np.array_equal(rain, leaks)
