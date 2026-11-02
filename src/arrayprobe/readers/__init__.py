# SPDX-License-Identifier: BSD-3-Clause
"""Raw-probe-file decoders: ``read_binary_*.m``.

Each module here turns a manufacturer's raw buffer format into the uncompressed
image netCDF (``8 x 1700 x time`` of packed 16-bit words) that ``imgProc_sm``
consumes.  The formats share nothing but that output contract.
"""

from __future__ import annotations
