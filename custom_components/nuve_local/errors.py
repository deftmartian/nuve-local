"""Safe control failures and the internal invariant error shared by the integration."""

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


class RuntimeInvariantError(AssertionError):
    """An internal runtime invariant was violated.

    This is never a safe control failure. It subclasses ``AssertionError`` so
    the former ``assert`` guards keep their exact outcome, but the check no
    longer disappears when Python runs with ``-O``.
    """


def require[T](value: T | None, description: str) -> T:
    """Return ``value``, or raise when an invariant guaranteed it is present."""

    if value is None:
        raise RuntimeInvariantError(f"{description} is unexpectedly missing")
    return value
