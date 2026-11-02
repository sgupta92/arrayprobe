# SPDX-License-Identifier: BSD-3-Clause
"""Shim: the driver lives in arrayprobe.driver.run_flight;
this path stays for scripts and tests."""

import importlib.util as _ilu
from pathlib import Path as _P

_spec = _ilu.find_spec("arrayprobe.driver.run_flight")
exec(compile(_P(_spec.origin).read_bytes(), _spec.origin, "exec"), globals())
