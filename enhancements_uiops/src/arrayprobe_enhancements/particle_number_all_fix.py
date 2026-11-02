# SPDX-License-Identifier: BSD-3-Clause
"""C5b -- stop a proc file carrying a ``Particle_number_all`` that was never written.

**What it corrects.**  ``imgProc_sm.m`` guards the same variable twice, with different
operators::

    :265   if probetype~=0 || probetype~=3     % defVar + putAtt
    :879   if probetype~=0 && probetype~=3     % putVar

No integer is simultaneously ``0`` and ``3``, so ``:265`` is true for every probetype and the
*definition* is unconditional; only the *write* is guarded.  Every 2DC, 2DP and Fast2DC proc file
therefore carries a ``Particle_number_all`` variable of pure fill values, described in its own
attribute as "Index of particle in 2-D buffer".  The port reproduces both sides faithfully --
``imgproc.py`` defines the variable in its spec table and writes it only for
``probetype not in (0, 3)`` (``imgproc.py:1312-1313``) -- so this correction lives here.

**What it changes.**  Nothing inside ``arrayprobe``.  This module reads a written proc file and:

* :func:`audit_proc_file` reports whether the variable is present, and whether every one of its
  values is the netCDF fill -- the state a user filtering on it would silently consume;
* :func:`corrected_proc_file` writes a *copy* with the variable omitted, which is exactly what
  the finding's own suggested edit (``||`` to ``&&`` at ``:265``) produces.  A consumer then gets
  a missing-variable error instead of a column of ``-2147483647``.

**Why it removes the variable rather than filling it in.**  ``Particle_number_all`` for these
probetypes comes from the raw buffer word ``data(header_loc, 4)`` (``imgProc_sm.m:356``, the port
at ``imgproc.py:897``) -- a number that exists only in the raw file, never in the proc file.  It
cannot be recovered from a proc file, and inventing a plausible 1..n index per record would put
fabricated values under a real variable name, which is worse than the defect.  So the correction
makes the *definition* consistent with the write, the direction the finding itself suggests.

**What this module does NOT claim.**

* **It has never been run against a real 2DC/2DP/Fast2DC product, because none exists on this
  machine.**  ORACLES is a 2D-S/HVPS campaign (probetype 2), where the variable is both defined
  and written and this module is a no-op.  The defective state is therefore exercised on a
  synthetic proc file built by the tests, honestly labelled -- the same standing as
  ``pms_c6_routing_fix.py``'s synthetic validation.
* **It does not claim the defect changes any number.**  It does not: ``sizeDist.m:673``/``:796``
  never read ``Particle_number_all`` for probetype 0 or 3, so no computed quantity depends on it.
  The consequence is a fill-valued variable presented to a downstream user as data, and that is
  the whole of it.
* **It does not recover the missing values** (see above), and it will refuse to remove a variable
  that carries any real value rather than guess which file it is looking at.
"""

from __future__ import annotations

from pathlib import Path

import netCDF4
import numpy as np

#: Rows per write when a rebuild is unavoidable: bounded memory.
_BLOCK = 16_384

__all__ = [
    "VARIABLE",
    "DEFINED_AT",
    "WRITTEN_AT",
    "defines_variable",
    "writes_variable",
    "is_inconsistent",
    "audit_proc_file",
    "corrected_proc_file",
]

#: The variable the two guards disagree about.
VARIABLE = "Particle_number_all"

#: ``if probetype~=0 || probetype~=3`` -- defVar + putAtt.
DEFINED_AT = "imgProc_sm.m:265"

#: ``if probetype~=0 && probetype~=3`` -- putVar.
WRITTEN_AT = "imgProc_sm.m:879"


def defines_variable(probetype: int) -> bool:
    """``:265`` as written -- ``probetype~=0 || probetype~=3``, i.e. always true.

    Spelled out rather than returned as a literal ``True`` so the tautology is visible at the
    place that reproduces it: no integer is both 0 and 3.
    """
    return probetype != 0 or probetype != 3


def writes_variable(probetype: int) -> bool:
    """``:879`` as written -- ``probetype~=0 && probetype~=3``."""
    return probetype != 0 and probetype != 3


def is_inconsistent(probetype: int) -> bool:
    """Whether this probetype gets a defined-but-never-written variable."""
    return defines_variable(probetype) and not writes_variable(probetype)


def _fill_value(var):
    """The value an unwritten element of ``var`` reads as."""
    if "_FillValue" in var.ncattrs():
        return var.getncattr("_FillValue")
    return netCDF4.default_fillvals[var.dtype.str[1:]]


def audit_proc_file(path) -> dict:
    """Report the state of ``Particle_number_all`` in a written proc file.

    Changes nothing.  ``all_fill`` is the defect's signature: the variable exists, has a
    non-zero length, and every element equals the fill value -- i.e. ``:265`` defined it and
    ``:879`` never wrote it.
    """
    path = Path(path)
    with netCDF4.Dataset(path) as ds:
        if VARIABLE not in ds.variables:
            return {"path": str(path), "present": False, "n": 0, "n_real": 0,
                    "all_fill": False,
                    "verdict": f"{VARIABLE} is absent -- already consistent with "
                               f"{WRITTEN_AT}"}
        var = ds.variables[VARIABLE]
        var.set_auto_mask(False)
        values = np.asarray(var[:])
        fill = _fill_value(var)
        real = int(np.count_nonzero(values != fill))
        n = int(values.size)
    all_fill = bool(n and real == 0)
    return {
        "path": str(path),
        "present": True,
        "n": n,
        "n_real": real,
        "fill_value": fill,
        "all_fill": all_fill,
        "verdict": (f"{VARIABLE} is defined ({DEFINED_AT}) and entirely fill values -- "
                    f"{WRITTEN_AT} never wrote it for this probetype"
                    if all_fill else
                    f"{VARIABLE} carries {real} of {n} real values -- written as intended"),
    }


def corrected_proc_file(src, dst, *, force: bool = False) -> dict:
    """Write a copy of ``src`` to ``dst`` without the all-fill ``Particle_number_all``.

    The effect of the finding's own suggested edit (``||`` to ``&&`` at ``:265``), applied to an
    already-written file.  Every other dimension, variable, value and attribute is copied
    verbatim, and the source file is never modified.

    Refuses -- raising :class:`ValueError` -- when the variable carries any real value, because
    then the file is a probetype the write guard allows and removing the variable would delete
    data.  ``force=True`` overrides that for a caller who knows what the file is; the returned
    report always says which happened.
    """
    src, dst = Path(src), Path(dst)
    report = audit_proc_file(src)
    if not report["present"]:
        drop = False
    elif report["all_fill"] or force:
        drop = True
    else:
        raise ValueError(
            f"{src}: {VARIABLE} holds {report['n_real']} real values, so this file was "
            f"written by a probetype {WRITTEN_AT} allows. Removing it would delete data; "
            "pass force=True only if you know otherwise."
        )

    if not drop:
        # Nothing to remove: a byte copy is the verbatim copy, at disk speed.
        import shutil
        shutil.copyfile(src, dst)
        report["removed"] = drop
        report["output"] = str(dst)
        return report
    # netCDF cannot delete a variable, so dropping one is a rebuild; every variable is written
    # in blocks of at most _BLOCK rows along its first dimension, never whole, because a whole
    # (time, 2) write at the default (1, 2) chunking costs ~7 KB of memory per chunk
    # (measured).
    with netCDF4.Dataset(src) as ds_in:
        fmt = ds_in.file_format
        with netCDF4.Dataset(dst, "w", format=fmt) as ds_out:
            ds_out.setncatts({k: ds_in.getncattr(k) for k in ds_in.ncattrs()})
            for name, dim in ds_in.dimensions.items():
                ds_out.createDimension(name, None if dim.isunlimited() else len(dim))
            for name, var in ds_in.variables.items():
                if drop and name == VARIABLE:
                    continue
                var.set_auto_mask(False)
                attrs = {k: var.getncattr(k) for k in var.ncattrs() if k != "_FillValue"}
                out = ds_out.createVariable(
                    name, var.dtype, var.dimensions,
                    fill_value=(var.getncattr("_FillValue")
                                if "_FillValue" in var.ncattrs() else None))
                out.setncatts(attrs)
                out.set_auto_mask(False)
                if not var.size:
                    continue
                if not var.dimensions:
                    out[:] = var[:]
                    continue
                n0 = var.shape[0]
                for i0 in range(0, n0, _BLOCK):
                    out[i0:min(i0 + _BLOCK, n0)] = var[i0:min(i0 + _BLOCK, n0)]
    report["removed"] = drop
    report["output"] = str(dst)
    return report
