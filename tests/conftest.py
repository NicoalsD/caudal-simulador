"""Shared pytest and Hypothesis configuration for the simulator."""

from hypothesis import settings

# A simulated year can exceed the default 200 ms deadline per example.
settings.register_profile("caudal", deadline=None)
settings.load_profile("caudal")
