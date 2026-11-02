# SPDX-License-Identifier: BSD-3-Clause
"""Import-time side effect: registers ``stock-v3.5-image-assisted`` (label-based hollow setting).

Meant to be named as ``[fidelity].profile_module`` (``config.py``) or
``run_flight.PROFILE_MODULE`` (the CIP lane scripts under
``_decoded/cip160906/``), never imported for any symbol of its own. Both call
sites exist for exactly one reason, spelled out in ``config.py``'s own
``[fidelity].profile_module`` docstring: a profile reached through
:func:`arrayprobe.profiles.register_profile` (which is how
:func:`arrayprobe.profiles.register_stock_v35_image_assisted` adds this one --
see its docstring for why this profile is registered rather than shipped as a
module-level constant) lives only in the ``_REGISTRY`` of the process that
registered it. A chunk worker (``scripts/run_flight.py --_run-chunk``) is a
*fresh* subprocess that re-imports ``arrayprobe.profiles`` from scratch and so
starts with an empty registry for anything not shipped -- ``PROFILE.name``
alone does not survive the re-exec, only ``PROFILE_MODULE`` does. Importing
this module is what makes ``PROFILES["stock-v3.5-image-assisted"]`` resolve
there too.
"""

from __future__ import annotations

from arrayprobe_uiops.profiles import register_stock_v35_image_assisted

register_stock_v35_image_assisted()
