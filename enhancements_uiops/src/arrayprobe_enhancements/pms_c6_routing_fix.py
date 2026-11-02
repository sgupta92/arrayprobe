# SPDX-License-Identifier: BSD-3-Clause
"""Corrects `read_binary_PMS.m`'s `'C6'` (F2DC) file-handle bug.

The `'C6'` branch (`probetype == [67, 54]`) writes its image correctly to the F2DC file handle
but its nine scalar fields (year, month, day, hour, minute, second, millisec, wkday, tas) to the
*2DC file* instead, at the F2DC write-counter's index -- a silent cross-file contamination:
a `'C6'` record's scalars can overwrite an unrelated 2DC record's timestamp/`tas`, while the F2DC
file itself gets that record's image with no matching scalar fields. See
`enhancements_uiops/docs/CORRECTIONS.md`, part `pms_c6_routing_fix.py` for the full write-up, including why -- unlike most of this
backlog -- this correction needed no real campaign data to validate: the bug is a pure
file-routing error, and the original finding itself was established on a synthetic file.

`src/arrayprobe/` never imports this module. `arrayprobe.readers.pms.read_binary_PMS`
continues to reproduce the bug exactly -- this module reuses its private helpers (byte parsing,
XML-header skip, reshape) unchanged, so the only difference from the port's own reader is the
file handle and counter on the `'C6'` branch's scalar write.
"""

from __future__ import annotations

from arrayprobe.readers import pms

__all__ = ["read_binary_PMS_corrected"]


def read_binary_PMS_corrected(infilename, outfilename):  # noqa: N802,N803
    """Corrected `read_binary_PMS` -- `'C6'` scalars go to the F2DC file, not the 2DC file.

    Same signature and return shape as `arrayprobe.readers.pms.read_binary_PMS`
    (`(n_2dc, n_f2dc_c6, n_f2dc_c4, n_2dp)`); every other branch is byte-for-byte
    the port's own logic, reused rather than duplicated.
    """
    f_2dc, v_2dc = pms._def_output(f"{outfilename}.2dc.cdf", pms._N_2DC)
    f_f2dc, v_f2dc = pms._def_output(f"{outfilename}.f2dc.cdf", pms._N_F2DC)
    f_2dp, v_2dp = pms._def_output(f"{outfilename}.2dp.cdf", pms._N_2DP)

    kk = kk1 = kk2 = kk3 = 0

    try:
        with open(infilename, "rb") as fh:
            pms._skip_xml_header(fh)
            while True:
                chunk = fh.read(pms._RECORD_BYTES)
                if len(chunk) < pms._RECORD_BYTES:
                    break
                tag = (chunk[0], chunk[1])
                fields = pms.np.frombuffer(chunk[2:20], dtype=">u2")
                header = dict(zip(pms._HEADER_FIELDS,
                                   (int(v) for v in fields), strict=True))
                data = pms.np.frombuffer(chunk[20:], dtype=pms.np.uint8)

                if tag == pms._TAG_2DC:
                    image = pms._reshape_matlab(data, pms._N_2DC)
                    pms._write_scalars(f_2dc, v_2dc, kk, header)
                    pms._write_image(f_2dc, v_2dc, kk, image)
                    kk += 1
                elif tag == pms._TAG_F2DC_A:  # 'C6' -- corrected: right file, same counter
                    image = pms._reshape_matlab(data, pms._N_F2DC)
                    pms._write_scalars(f_f2dc, v_f2dc, kk2, header)   # fixed: 2DC file -> F2DC file
                    pms._write_image(f_f2dc, v_f2dc, kk2, image)
                    kk2 += 1
                elif tag == pms._TAG_F2DC_B:  # 'C4' -- already correct, unchanged
                    image = pms._reshape_matlab(data, pms._N_F2DC)
                    pms._write_scalars(f_f2dc, v_f2dc, kk3, header)
                    pms._write_image(f_f2dc, v_f2dc, kk3, image)
                    kk3 += 1
                elif tag[0] == pms._TAG_2DP_PREFIX:
                    image = pms._reshape_matlab(data, pms._N_2DP)
                    pms._write_scalars(f_2dp, v_2dp, kk1, header)
                    pms._write_image(f_2dp, v_2dp, kk1, image)
                    kk1 += 1
    finally:
        f_2dc.close()
        f_f2dc.close()
        f_2dp.close()

    return kk, kk2, kk3, kk1
