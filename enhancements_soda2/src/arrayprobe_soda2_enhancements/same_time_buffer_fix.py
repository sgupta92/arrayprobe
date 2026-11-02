# SPDX-License-Identifier: BSD-3-Clause
# Reproduces SODA-2, Copyright (c) 2016 UCAR; see LICENSES/BSD-3-Clause.txt and NOTICE.md.
"""S4-o: a same-time buffer stamps its first particle with the
previous buffer's last time.

``soda2_processbuffer.pro:362-365``: when a buffer's time equals the
previous buffer's (``:362``), ``:363`` sets the first particle's time to
the previous buffer's ``maxsfm``, and ``:364`` builds each later
particle's time by adding its own ``inttime`` to its predecessor's.

When consecutive buffers carry the same time stamp, the forward count
starts the new buffer's first particle at the previous buffer's
``maxsfm`` and never adds that particle's own ``inttime[0]``.

**Correction**: the register's own suggested edit --
``time_sfm[0] = maxsfm + inttime[0]``. Because every later
``time_sfm[i]`` (``i >= 1``) is built by repeatedly adding ``inttime[i]``
onto ``time_sfm[i-1]``, adding the missing ``inttime[0]`` to
``time_sfm[0]`` shifts the *entire* array by that one constant -- so
this module does not need to re-run the cascading loop, only shift the
port's own output.

``src/arrayprobe_soda2/processbuffer_spec.py`` is never
imported for writing and never modified. This module calls the real,
unmodified ``process_spec_buffer`` and, only on the same-time branch,
shifts its returned ``time_sfm`` by ``inttime[0]`` and corrects
``misc.maxsfm`` (which the port already advanced to the *uncorrected*
max) to match. Whether the same-time branch fired is read from
``misc.lastbufftime`` **before** the call -- the port itself
overwrites that field at the very end of its own run, so it cannot be
read afterwards. Tests: ``tests/test_same_time_buffer_fix.py``.
"""
from __future__ import annotations

from typing import BinaryIO

from arrayprobe_soda2.processbuffer_spec import (
    NullBuffer,
    SpecBufferParticles,
    SpecMisc,
    SpecOp,
    process_spec_buffer,
)

from arrayprobe_soda2_enhancements.registry import EnhancementSpec, register

__all__ = ["corrected_process_spec_buffer"]


def corrected_process_spec_buffer(
    f: BinaryIO, buffer_time: float, op: SpecOp, misc: SpecMisc,
) -> SpecBufferParticles | NullBuffer:
    """``process_spec_buffer`` with S4-o corrected: on a same-time
    buffer, ``time_sfm`` (and ``misc.maxsfm``) are shifted by
    ``inttime[0]`` -- the first particle's own interarrival time,
    which the port's own ``:362-365`` never adds."""
    same_time = buffer_time == misc.lastbufftime  # read before the call mutates it
    result = process_spec_buffer(f, buffer_time, op, misc)

    if isinstance(result, NullBuffer) or not same_time or result.num_images == 0:
        return result

    shift = float(result.inttime[0])
    result.time_sfm = result.time_sfm + shift
    misc.maxsfm = float(result.time_sfm.max())
    return result


register(EnhancementSpec(
    name="same_time_buffer_fix",
    summary="on a same-time buffer, time_sfm[0] (and every later "
            "time_sfm[i], which cascades from it) is shifted by "
            "inttime[0] -- the first particle's own interarrival time, "
            "which soda2_processbuffer.pro:362-365 never adds.",
    finding="S4-o",
    reachability="live",
    entry_point="corrected_process_spec_buffer",
))
