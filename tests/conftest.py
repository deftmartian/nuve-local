"""Initialize HA's validation compatibility layer before test collection."""

import importlib

# HA 2026.9 installs probatio as voluptuous. Loading HA first keeps individual
# test-file runs consistent with the complete suite and with a running Core.
importlib.import_module("homeassistant")
