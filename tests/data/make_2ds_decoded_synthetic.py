# SPDX-License-Identifier: BSD-3-Clause
"""Write ``2DS_decoded_synthetic.nc``: a decoded 2D-S (probetype 2) H-channel image file.

It is the v3.5 engine's SPEC decoder (``arrayprobe_uiops.spec.read_binary_spec_v35``,
H channel only, no sidecars) run on the shipped synthetic raw file
``demo_flight_dense_raw.2DS``, which is itself written from a seeded generator
and holds no flight data. The decode is deterministic, so this script always
writes the same records; it stands in for the 25-record decode of
real data that ``test_v35_imgproc_merge_chunks.py`` used before the release.

Regenerate::

    python tests/data/make_2ds_decoded_synthetic.py
"""

import os
import shutil
import tempfile

from arrayprobe_uiops.spec import read_binary_spec_v35

HERE = os.path.dirname(os.path.abspath(__file__))
SYNTHETIC_OUTPUTS = ("2DS_decoded_synthetic.nc",)
FIXTURE = os.path.join(HERE, SYNTHETIC_OUTPUTS[0])
RAW = os.path.join(HERE, "demo_flight_dense_raw.2DS")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        prefix = os.path.join(tmp, "synthetic")
        # Fixed software and creation-time strings keep the file byte-reproducible.
        read_binary_spec_v35(RAW, prefix, software="synthetic-fixture",
                             creation_time="2026-10-19 00:00:00", sidecars=False,
                             channels="H")
        shutil.copyfile(prefix + ".H.nc", FIXTURE)
    print(f"wrote {FIXTURE}")


if __name__ == "__main__":
    main()
