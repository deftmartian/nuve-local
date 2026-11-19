"""Internal invariant guard used instead of bare ``assert`` narrowing."""

from __future__ import annotations

import pytest

from custom_components.nuve_local.errors import (
    NuveControlError,
    RuntimeInvariantError,
    require,
)


def test_require_returns_present_values_unchanged() -> None:
    value = {"temp": 21.0}

    assert require(value, "settings baseline") is value
    assert require(0, "falsy but present") == 0


def test_require_raises_an_assertion_compatible_internal_error() -> None:
    with pytest.raises(RuntimeInvariantError, match="settings baseline is unexpectedly missing"):
        require(None, "settings baseline")

    # The former asserts raised AssertionError; keep that outcome and never let
    # an invariant breach masquerade as a safe, user-facing control failure.
    assert issubclass(RuntimeInvariantError, AssertionError)
    assert not issubclass(RuntimeInvariantError, NuveControlError)
