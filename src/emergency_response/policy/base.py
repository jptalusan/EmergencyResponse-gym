"""Base class for dispatch policies."""

from __future__ import annotations

from abc import ABC, abstractmethod

from emergency_response.models.core import Action, State


class DispatchPolicy(ABC):
    """Abstract base class for dispatch policies.

    A policy takes the current state (including the new incident) and returns
    dispatch actions.
    """

    @abstractmethod
    def dispatch(self, state: State) -> Action:
        """Decide how to respond to state.new_incident.

        Returns:
            A list of DispatchActions, or None to skip/ignore the incident.
        """
        ...
