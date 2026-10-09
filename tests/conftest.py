"""Configuración compartida de pytest y Hypothesis para el simulador."""

from hypothesis import settings

# La simulación de un año puede superar el límite por defecto de 200 ms por ejemplo.
settings.register_profile("caudal", deadline=None)
settings.load_profile("caudal")
