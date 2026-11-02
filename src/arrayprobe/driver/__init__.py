# SPDX-License-Identifier: BSD-3-Clause
"""The flight driver: ``run_flight`` (the per-flight batch driver), ``reprocess``,
and the three helpers it reaches (``_load_record``, ``preflight_inputs``,
``tas_from_probe_housekeeping``). ``scripts/<name>.py`` stays the entry point scripts
and hooks name; each executes this package's source in its own namespace."""
