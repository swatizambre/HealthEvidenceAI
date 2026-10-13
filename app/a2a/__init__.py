"""A2A package."""

from app.a2a.bus import get_a2a_bus
from app.a2a.handlers import consult_imaging_via_a2a, register_default_handlers

__all__ = ["consult_imaging_via_a2a", "get_a2a_bus", "register_default_handlers"]
