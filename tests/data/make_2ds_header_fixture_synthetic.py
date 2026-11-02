# SPDX-License-Identifier: BSD-3-Clause
"""Write ``2DS_header_fixture.nc`` from made-up values.

The fixture stands in for a decoded 2D-S image file: what the tests read is its
*structure* -- dimension names and creation order (``time``, ``ImgRowlen``,
``ImgBlocklen``), variable names and order, dtypes (MATLAB's ``'byte'`` maps to
int8), no global or variable attributes, NETCDF3_CLASSIC -- plus one property of
record 0: sixteen whole slices of the boundary marker 43690 (0xAAAA) lying along
the last axis, and no all-43690 run along the other.

Every value here is invented: the date fields are fixed placeholders and the
image words come from ``numpy.random.default_rng(0)``, with the 43690 word
excluded outside the sixteen boundary slices.

Regenerate::

    python tests/data/make_2ds_header_fixture_synthetic.py
"""

import os

import numpy as np
from netCDF4 import Dataset

HERE = os.path.dirname(os.path.abspath(__file__))
SYNTHETIC_OUTPUTS = ("2DS_header_fixture.nc",)
FIXTURE = os.path.join(HERE, SYNTHETIC_OUTPUTS[0])

N_RECORDS = 3
ROWLEN = 8
BLOCKLEN = 1700
BOUNDARY = 43690
N_BOUNDARY_SLICES = 16


def _image_words(rng: np.random.Generator) -> np.ndarray:
    data = rng.integers(0, 65536, size=(N_RECORDS, BLOCKLEN, ROWLEN), dtype=np.int64)
    data[data == BOUNDARY] = BOUNDARY - 1
    slices = np.sort(rng.choice(BLOCKLEN, size=N_BOUNDARY_SLICES, replace=False))
    data[0, slices, :] = BOUNDARY
    return data.astype(np.int32)


def build(fixture: str = FIXTURE) -> str:
    rng = np.random.default_rng(0)
    with Dataset(fixture, "w", format="NETCDF3_CLASSIC") as dst:
        dst.createDimension("time", N_RECORDS)
        dst.createDimension("ImgRowlen", ROWLEN)
        dst.createDimension("ImgBlocklen", BLOCKLEN)
        fields = (
            ("year", np.int16, 2000),
            ("month", np.int8, 1),
            ("day", np.int8, 1),
            ("hour", np.int8, 0),
            ("minute", np.int8, 0),
            ("second", np.int8, 0),
            ("millisec", np.int16, 0),
            ("wkday", np.int8, 1),
        )
        for name, dtype, value in fields:
            var = dst.createVariable(name, dtype, ("time",))
            var.set_auto_maskandscale(False)
            var[:] = np.full(N_RECORDS, value, dtype=dtype)
        dst["second"][:] = np.arange(N_RECORDS, dtype=np.int8)  # one record per second
        data = dst.createVariable("data", np.int32, ("time", "ImgBlocklen", "ImgRowlen"))
        data.set_auto_maskandscale(False)
        data[:] = _image_words(rng)
    return fixture


if __name__ == "__main__":
    print(build())
