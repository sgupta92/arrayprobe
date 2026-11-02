# SPDX-License-Identifier: BSD-3-Clause
"""F1 -- a missing or misnamed shadow-diode mask stops being silent.

**What it corrects.**  The nine-argument ``imgProc_sm.m:288`` (the form that produced the
ORACLES products) looks the mask up by constructed name and has an **empty ``else``**::

    if exist([path '/' 'diode.' flight file '.' infile(end-4) '.mat'],'file')==2;
        load([...],'shadow_diode');
        c(:,shadow_diode)='1';
    else
    end

If the file is absent, or present under any other name, the run proceeds with unmodified images
and *nothing anywhere records that the intended correction did not happen*.  The product is
byte-identical to a run where masking was never requested, and the ORACLES variant writes no
netCDF attributes at all (F4), so it cannot be interrogated afterwards either.

This is not hypothetical.  ``find_shadow_diodes.m:104`` writes
``diode.<date><time>.<orientation>.mat`` while ``imgProc_sm`` looks for
``diode.<flight><file>.<orientation>.mat``; the masks recovered for one 2016 campaign carry **no
orientation letter at all** (``diode.160906064403.mat``) and would never have been found.
``find_shadow_diodes.m:103-107`` additionally saves an *empty* mask as ``...<or>empty.mat``, a
name the loader cannot construct (F2).  Determining after the fact whether a four-year-old
product had been diode-corrected took a filesystem sweep and a recomputation of the selection
criterion.

The port reproduces the silence deliberately: ``arrayprobe.masks.find_shadow_diode_mask``
returns ``None`` and says in its own docstring that ``None`` is the honest result.  This module
is the opt-in loud version.

**What it changes.**  Nothing in ``arrayprobe``, and no image and no number anywhere.  It
changes what the *caller knows*:

* :func:`check_mask` performs the same lookup and, with ``required=True`` (the default), raises
  :class:`MaskNotFoundError` naming the exact path MATLAB would have looked for;
* it lists **near misses** -- files that plainly are the mask under a name the loader can never
  construct -- so the silent missing mask file failure is diagnosed rather than merely reported;
* :func:`provenance_entry` renders the outcome as one line to store beside the product, which is
  the thing the archived ORACLES products do not have.

``required=False`` reproduces the MATLAB's own silence and returns the same report, so a caller
can audit a directory without any run failing.

**What this module does NOT claim.**

* **It cannot tell whether an existing product was diode-corrected.**  That information was
  never written (the silent missing mask file and the unrecorded image pre-processing together), and no amount of post-hoc checking recovers it; this
  module only prevents the *next* run from having the same hole.  The ORACLES-era determination
  described above stands as the only way, and it was a filesystem-archaeology exercise.
* **It does not decide that a near miss is the right mask.**  A ``diode.160906064403.mat`` with
  no orientation letter may be the horizontal mask, the vertical one, or neither; the module
  reports it and refuses to guess.  Loading it is the caller's explicit act.
* **No measured effect on any ORACLES number is claimed.**  For the 09/06/2016 2D-S the
  recovered masks are empty, so the block is inert for that product
  (``arrayprobe.masks`` module docstring); this correction changes what a run *reports*, not
  what it computes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from arrayprobe.masks import (
    ShadowDiodeMask,
    load_shadow_diode_mask,
    matlab_mask_filename,
    orientation_from_infile,
)

__all__ = [
    "MaskNotFoundError",
    "MaskLookup",
    "expected_mask_path",
    "near_miss_candidates",
    "check_mask",
    "provenance_entry",
]


class MaskNotFoundError(FileNotFoundError):
    """The mask ``imgProc_sm.m:288`` would have loaded is not there.

    A subclass of :class:`FileNotFoundError` so an existing ``except OSError`` still catches it,
    and a distinct type so a caller can tell "the mask is missing" from "the directory is".
    """


@dataclass
class MaskLookup:
    """The outcome of one ``:288`` lookup, said out loud."""

    expected: Path
    """The exact path MATLAB constructs -- ``diode.<flight><file>.<orientation>.mat``."""

    found: bool
    orientation: str
    mask: ShadowDiodeMask | None = None
    near_misses: list[Path] = field(default_factory=list)
    """Files that are almost certainly the mask under a name the loader cannot construct."""

    @property
    def verdict(self) -> str:
        if self.found:
            n = len(self.mask) if self.mask is not None else 0
            return (f"mask found at {self.expected.name}: {n} diode(s)"
                    + ("" if n else " -- an empty mask, which changes nothing"))
        if self.near_misses:
            names = ", ".join(p.name for p in self.near_misses)
            return (f"NO mask at {self.expected.name}, but {len(self.near_misses)} near "
                    f"miss(es) exist that imgProc_sm can never construct: {names}. "
                    "MATLAB would proceed silently with unmasked images.")
        return (f"NO mask at {self.expected.name}. MATLAB's else branch is empty, so the run "
                "would proceed with unmasked images and record nothing.")

    def __bool__(self) -> bool:
        return self.found


def expected_mask_path(path, flight: str, file: str, infile) -> Path:
    """The path ``:288`` builds -- the port's own name construction, not a second copy."""
    orientation = orientation_from_infile(infile)
    return Path(path) / matlab_mask_filename(flight, file, orientation)


def near_miss_candidates(path, flight: str, file: str, infile) -> list[Path]:
    """Mask files for this flight under names the loader can never construct.

    Three real shapes, all seen: no orientation letter at all
    (``diode.160906064403.mat`` -- the 2016 delivery), the other channel's letter, and F2's
    ``...<or>empty.mat``.  Matching is by the ``<flight><file>`` stem, so a file for a
    *different* flight is not offered as a candidate for this one.
    """
    directory = Path(path)
    if not directory.is_dir():
        return []
    expected = expected_mask_path(directory, flight, file, infile)
    stem = f"diode.{flight}{file}"
    # `sorted()` on Path objects is NOT platform-independent: pathlib compares
    # WindowsPath case-INsensitively and PosixPath case-sensitively, so the same
    # directory came back as [".mat", ".Vempty.mat"] on Windows and
    # [".Vempty.mat", ".mat"] on Linux -- found by the first cross-platform CI
    # run, 2026-09-08. This report is read by people and asserted by tests, so
    # it has to be one order everywhere. Sort by the name as a plain string.
    return sorted((p for p in directory.glob(f"{stem}*.mat") if p != expected),
                  key=lambda p: p.name)


def check_mask(path, flight: str, file: str, infile, *, required: bool = True) -> MaskLookup:
    """Reproduce ``:288``'s lookup, then say what happened instead of falling through.

    ``required=True`` (default) raises :class:`MaskNotFoundError` when the file is absent --
    the correction.  ``required=False`` returns the same :class:`MaskLookup` without raising,
    which is MATLAB's own behaviour plus a report; use it to audit a directory.
    """
    expected = expected_mask_path(path, flight, file, infile)
    orientation = orientation_from_infile(infile)
    if expected.is_file():
        return MaskLookup(expected=expected, found=True, orientation=orientation,
                          mask=load_shadow_diode_mask(expected))
    lookup = MaskLookup(expected=expected, found=False, orientation=orientation,
                        near_misses=near_miss_candidates(path, flight, file, infile))
    if required:
        raise MaskNotFoundError(lookup.verdict)
    return lookup


def provenance_entry(lookup: MaskLookup) -> str:
    """One ``key=value`` line to store beside the product, as F1's suggested edit asks for.

    Deliberately *beside* the netCDF and never inside it: the port's outputs are byte-compared
    against MATLAB's, so an attribute of our own would break the fidelity the package exists to
    demonstrate -- the same reasoning as ``last_record_fix.write_provenance``.
    """
    if lookup.found:
        n = len(lookup.mask) if lookup.mask is not None else 0
        return f"diode_mask={lookup.expected.name} diodes={n}"
    return f"diode_mask=none expected={lookup.expected.name}"
