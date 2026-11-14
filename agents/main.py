"""Agent entry points for the Django API."""

from .event_agent import run_event_agent
from .events import find_events
from .impact_agent import PROFILES, run_impact_agent

__all__ = [
    "PROFILES",
    "find_events",
    "run_event_agent",
    "run_impact_agent",
    "event_agent",
    "impact_agent",
]


def event_agent(window):
    return run_event_agent(window)


def impact_agent(dossier, profile, scenario):
    return run_impact_agent(dossier, profile, scenario)