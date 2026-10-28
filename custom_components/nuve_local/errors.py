"""Safe control failures shared by the runtime, validators and entities."""

from __future__ import annotations


class NuveControlError(Exception):
    """Base class for safe control failures."""


class ControlDisabledError(NuveControlError):
    """Control was not explicitly enabled."""


class ControlNotReadyError(NuveControlError):
    """The device has not provided enough fresh state for control."""


class ControlBusyError(NuveControlError):
    """Another device command is already active."""


class ControlStateChangedError(NuveControlError):
    """A local edit superseded a queued command before delivery."""


class CommandTimeoutError(NuveControlError):
    """The device did not fetch the command before the deadline."""


class CommandOutcomeUncertainError(NuveControlError):
    """The device fetched the command but did not confirm its result."""


class RuntimeStoppedError(NuveControlError):
    """The integration stopped while a command was active."""


class PersistenceUnavailableError(NuveControlError):
    """Canonical state cannot be trusted after a persistence failure."""
