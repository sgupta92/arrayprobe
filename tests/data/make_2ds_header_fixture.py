# SPDX-License-Identifier: BSD-3-Clause
"""Cut a small, tracked fixture out of the shipped MATLAB-written 2DS file.

Why this exists: ``2DS.20151205_subset1.V.cdf`` is the only MATLAB-authored
netCDF file in the tree, and therefore the only oracle for the dimension
reversal, the ``'byte'``->int8 type map and the NETCDF3_CLASSIC format.  It is
52 MB, so ``.gitignore`` excludes it -- which would leave every S0 acceptance
test **silently skipped on a fresh clone**, exactly the failure mode where a
regression hides.

So this script copies the file's *structure* (dimension names and order,
variable names and order, dtypes, attributes) plus the first few records into a
~160 KB fixture that is small enough to track.  The structure is MATLAB's, byte
for byte in header terms, so the fixture is a real oracle rather than something
we invented; ``test_ncio.py`` additionally asserts fixture and original still
agree whenever the original is present, so it cannot drift.

Regenerate::

    python tests/data/make_2ds_header_fixture.py

Requires the 52 MB original, which lives at the path below and is fetched
separately (see README).  Data-level checks that need many records still skip
without it -- deliberately: this fixture stands in for the header, not the flight.
"""

import os
import sys

import numpy as np
from netCDF4 import Dataset

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, os.pardir)))
import _upstream  # noqa: E402  (tests/_upstream.py)

SOURCE = str(_upstream.source("uiops314") / "minimal_working_example"
             / "2DS.20151205_subset1.V.cdf")
FIXTURE = os.path.join(HERE, "2DS_header_fixture.nc")

N_RECORDS = 3
"""Enough for the boundary-orientation check (record 0 carries 16 boundary rows)
and for a start/count read that is not degenerate."""


def build(source: str = SOURCE, fixture: str = FIXTURE, n_records: int = N_RECORDS) -> str:
    with Dataset(source) as src, Dataset(fixture, "w", format="NETCDF3_CLASSIC") as dst:
        # Dimension creation ORDER is part of what we are preserving: MATLAB
        # identifies dimensions by integer ID in creation order and UIOOPS reads
        # dimension 0 and 2 by bare number (imgProc_sm.m:205-206).
        for name, dim in src.dimensions.items():
            if dim.isunlimited():
                dst.createDimension(name, None)
            elif name == "time":
                dst.createDimension(name, n_records)
            else:
                dst.createDimension(name, len(dim))

        for attname in src.ncattrs():
            dst.setncattr(attname, src.getncattr(attname))

        # Variable creation order matters for the same reason.
        for name, var in src.variables.items():
            var.set_auto_maskandscale(False)
            out = dst.createVariable(name, var.dtype, var.dimensions)
            out.set_auto_maskandscale(False)
            for attname in var.ncattrs():
                out.setncattr(attname, var.getncattr(attname))
            if var.dimensions and var.dimensions[0] == "time":
                out[:n_records, ...] = np.asarray(var[:n_records, ...])
            else:
                out[...] = np.asarray(var[...])

    return fixture


if __name__ == "__main__":
    if not os.path.exists(SOURCE):
        sys.exit(
            f"source not found: {SOURCE}\n"
            "The 52 MB MATLAB-written 2DS file is gitignored and fetched separately."
        )
    path = build()
    print(f"wrote {path} ({os.path.getsize(path) / 1024:.0f} KiB)")
