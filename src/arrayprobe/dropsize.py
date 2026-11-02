# SPDX-License-Identifier: BSD-3-Clause
"""Drop sizing by chord lookup -- a port of ``dropsize.m`` (243 lines).

``imgProc_sm.m:833-835`` (stock) / ``:416-418`` (ORACLES variant) calls this once
per particle and writes all seven returns to the per-particle file:
``center_in``, ``axis_ratio``, ``diam_circle_fit``, ``diam_horiz_chord``,
``diam_vert_chord``, ``diam_horiz_mean``, ``diam_spheroid``.

The method: measure a chord across the shadow, then read the diameter of the
equivalent-volume **sphere** off a table computed from the equilibrium shape of a
falling raindrop of that chord.  The circle-fit branch is Heymsfield & Parrish
(1978) for images that touch an array edge, where the true width is unknown and
a circle is fitted through the two edge chords.

**Stock v3.1.4 and the ORACLES variant ship byte-identical copies of this file**
(verified 2026-08-20 by md5), so nothing here takes a
:class:`~arrayprobe.profiles.FidelityProfile`.  Both callers also pass
``corrected_horizontal_diode_size = diode_size = handles.diodesize``
(``imgProc_sm.m:826-827`` / ``:409-410``), which matters more than it looks --
see "Latent defects" below.

Phase neutrality (binding directive, 2026-08-19)
-----------------------------------------------------------

This module is the one the directive names explicitly.  The tables answer *"what
raindrop would have cast this shadow"*, which is not a question an ice crystal
has an answer to, so :mod:`arrayprobe.sizing` registers it as ``phase="liquid"``
and bars it from the universal sizing path.  MATLAB has no such guard: it calls
``dropsize`` on every particle, in every cloud, and writes the result.

Preserved defects, each with a test
-----------------------------------

* ``dropsize.m:198-201, 219-222`` -- **the table lookup extrapolates forward
  using the previous segment's slope.**  ``i = round(chord * 10)`` is one less
  than the index of the entry *for* that chord, because ``chords(1)`` is 0.0.
  The code then evaluates ``D(i) + slope[i, i+1] * (chord - chords(i))`` where
  ``chord - chords(i)`` runs up to 0.15.  At a grid point this is exact.  Above
  one it extrapolates with the slope of the segment *below*, so the sign of the
  error follows each table's curvature: the horizontal table is nearly straight
  and its error stays under 0.4 um (0.03%), while the vertical table is strongly
  convex at the top and reads **low** by up to 23 um (0.29%).  The function is
  also discontinuous at half-grid chords, by the same 23 um.  See
  :func:`_chord_to_spherical_dia`.
* ``dropsize.m:199, 220`` -- the bound is ``i + 1 < max_chords`` where
  ``<=`` would still be in range, so **the last entry of each table is
  unreachable**: 8.9998 mm horizontal and 8.9230 mm vertical are never returned.
  The oversize sentinel 9.1 takes over at chord 11.55 / 5.35 instead of 11.65 /
  5.45.
* ``dropsize.m:56, 180`` -- ``diodes_added_to_length`` is ``0``, so the "one
  diode added for the missing first slice" that the header comment at ``:10``
  and ``:15`` documents **never happens**.  Only the vertical branch at ``:172``
  adds anything, and it adds ``diodes_added_to_height * 0.5`` = 0.5, not 1.
* ``dropsize.m:143`` -- the ``elseif`` branch taken when the smallest edge
  touching is positive is **dead when
  called from imgProc_sm**, which passes ``largest = max(top, bottom)`` and
  ``smallest = min(top, bottom)``: a positive minimum forces a positive maximum,
  so the ``elseif`` cannot be reached.  Kept, because the function is public.
* ``dropsize.m:220-222`` -- a **negative chord indexes the tables negatively**
  and MATLAB dies.  Preserved as :class:`~arrayprobe.matlab_compat.MatlabIndexError`
  rather than clamped; see :func:`_chord_to_spherical_dia`.

Latent defects -- masked by the caller, reproduced anyway
----------------------------------------------------------

Two defects are invisible in every UIOOPS run ever made, because both call sites
pass ``corrected_horizontal_diode_size == diode_size``, making
``scaling_factor_for_horizontal_lengths`` exactly 1.0.  They are transcribed
faithfully so that the day someone passes a real correction -- which is what the
argument is *for* -- the port and the MATLAB agree on being wrong together:

* ``dropsize.m:131, 167, 177`` -- **the correction is applied twice.**
  ``max_horizontal_length`` is scaled by ``corr / ds`` at ``:131``, then
  multiplied by ``corr`` again at ``:167`` and ``:177``, giving a chord of
  ``L * corr**2 / ds`` where ``L * corr`` was meant.  Measured in Octave: with
  ``L = 3``, ``ds = 0.010``, ``corr = 0.020`` the chord is 0.12, not 0.06.
* ``dropsize.m:131, 150`` -- **the centre-in test compares a scaled length with
  an unscaled one.**  ``:150`` tests the already-scaled ``max_horizontal_length``
  against the raw ``largest_edge_touching``, not against
  ``largest_edge_touching_length``.  Measured in Octave: ``L = 10``,
  ``edge = 12``, ``ds = 0.010`` gives ``center_in = 0`` at ``corr = 0.010`` and
  ``center_in = 1`` at ``corr = 0.020``, on identical geometry.

Validation
----------

Bit-exact against GNU Octave running the unmodified ``dropsize.m``
(``octave_oracle/run_s1c_oracle.m``, golden fixture
``tests/data/s1c_octave_golden.csv``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .matlab_compat import MatlabIndexError, mdiv, mround, to0
from .sizing import SizeDefinition, register_size_definition

__all__ = [
    "MAX_HORIZONTAL_CHORDS",
    "MAX_VERTICAL_CHORDS",
    "HORIZONTAL_CHORDS",
    "HORIZONTAL_CHORD_ESD",
    "VERTICAL_CHORDS",
    "VERTICAL_CHORD_ESD",
    "DIODES_ADDED_TO_LENGTH",
    "DIODES_ADDED_TO_HEIGHT",
    "OVERSIZE",
    "DropSize",
    "dropsize",
    "horizontal_chord_to_spherical_dia",
    "vertical_chord_to_spherical_dia",
]


# --------------------------------------------------------------------------
# Lookup tables -- dropsize.m:53-100
# --------------------------------------------------------------------------

#: ``dropsize.m:53-54``.  Both equal the length of their table, which is what
#: makes the ``i + 1 < max`` bound at ``:199,220`` drop the final entry.
MAX_HORIZONTAL_CHORDS = 117
MAX_VERTICAL_CHORDS = 55

#: ``dropsize.m:56-57``.  ``diodes_added_to_length`` is zero, so the "+1 diode
#: for the missing first slice" in the header comment never happens.
DIODES_ADDED_TO_LENGTH = 0.0
DIODES_ADDED_TO_HEIGHT = 1.0

#: ``dropsize.m:11`` -- "uncalculated size appears as zero; oversize as 9.1".
OVERSIZE = 9.1

#: ``dropsize.m:59-71``.  Chord in mm, 0.0 to 11.6 in steps of 0.1.
HORIZONTAL_CHORDS = np.array(
    [round(0.1 * k, 10) for k in range(MAX_HORIZONTAL_CHORDS)], dtype=np.float64
)

#: ``dropsize.m:73-85``.  Equivalent-spherical diameter, mm, for the chord at
#: the same position in :data:`HORIZONTAL_CHORDS`.
HORIZONTAL_CHORD_ESD = np.array([
    0.0000, 0.1000, 0.2000, 0.3000, 0.3998, 0.4996, 0.5992, 0.6986, 0.7976, 0.8964,
    0.9947, 1.0927, 1.1903, 1.2875, 1.3842, 1.4804, 1.5761, 1.6711, 1.7657, 1.8597,
    1.9531, 2.0460, 2.1385, 2.2304, 2.3217, 2.4124, 2.5026, 2.5921, 2.6812, 2.7696,
    2.8574, 2.9448, 3.0319, 3.1185, 3.2046, 3.2903, 3.3755, 3.4603, 3.5446, 3.6286,
    3.7120, 3.7950, 3.8776, 3.9598, 4.0416, 4.1229, 4.2036, 4.2841, 4.3642, 4.4440,
    4.5233, 4.6024, 4.6811, 4.7597, 4.8378, 4.9152, 4.9924, 5.0690, 5.1452, 5.2210,
    5.2961, 5.3711, 5.4457, 5.5201, 5.5942, 5.6681, 5.7416, 5.8148, 5.8877, 5.9602,
    6.0323, 6.1041, 6.1756, 6.2467, 6.3175, 6.3879, 6.4580, 6.5278, 6.5973, 6.6664,
    6.7353, 6.8040, 6.8720, 6.9399, 7.0075, 7.0744, 7.1411, 7.2074, 7.2733, 7.3388,
    7.4040, 7.4688, 7.5332, 7.5973, 7.6610, 7.7241, 7.7864, 7.8490, 7.9117, 7.9739,
    8.0359, 8.0976, 8.1591, 8.2203, 8.2813, 8.3421, 8.4027, 8.4631, 8.5233, 8.5834,
    8.6433, 8.7030, 8.7625, 8.8220, 8.8814, 8.9407, 8.9998,
], dtype=np.float64)

#: ``dropsize.m:87-93``.  Chord in mm, 0.0 to 5.4 in steps of 0.1.
VERTICAL_CHORDS = np.array(
    [round(0.1 * k, 10) for k in range(MAX_VERTICAL_CHORDS)], dtype=np.float64
)

#: ``dropsize.m:94-100``.  The vertical table rises much faster than the
#: horizontal one at the top end: a large drop is flattened, so a given vertical
#: chord implies a bigger sphere than the same horizontal chord does.
VERTICAL_CHORD_ESD = np.array([
    0.0000, 0.1000, 0.2000, 0.3001, 0.4003, 0.5008, 0.6016, 0.7028, 0.8048, 0.9075,
    1.0110, 1.1155, 1.2208, 1.3271, 1.4348, 1.5438, 1.6545, 1.7668, 1.8809, 1.9967,
    2.1142, 2.2336, 2.3553, 2.4792, 2.6059, 2.7353, 2.8677, 3.0023, 3.1394, 3.2792,
    3.4219, 3.5678, 3.7169, 3.8695, 4.0259, 4.1865, 4.3512, 4.5201, 4.6922, 4.8687,
    5.0525, 5.2438, 5.4432, 5.6474, 5.8580, 6.0775, 6.3073, 6.5485, 6.8018, 7.0729,
    7.3699, 7.7007, 8.0781, 8.4868, 8.9230,
], dtype=np.float64)


# --------------------------------------------------------------------------
# The chord -> diameter lookup -- dropsize.m:192-229
# --------------------------------------------------------------------------

def _chord_to_spherical_dia(chord, chords, diameters, max_chords, table_name):
    """``dropsize.m:192-209`` and ``:212-229``, which are the same code twice.

    The two subfunctions differ only in which pair of tables they close over and
    in ``max_vertical_chords`` vs ``max_horizontal_chords``, so they are one
    implementation here with two thin wrappers below for provenance.

    Transcribed literally, including the index arithmetic that makes it
    extrapolate rather than interpolate::

        i = round(chord * 10)                                   % :198, :219
        if i + 1 < max_chords & i ~= 0                          % :199, :220
            delta = D(i+1) - D(i)                               % :200, :221
            diameter = D(i) + (delta / 0.1) * (chord - X(i))    % :201, :222

    ``X(i)`` is ``(i - 1) * 0.1``, one grid step *below* the chord ``i`` was
    derived from, so ``chord - X(i)`` is about 0.1 rather than about 0.  At an
    exact grid point the two errors cancel and the result is the table value.
    Off one, the slope comes from the segment below the chord instead of the
    segment containing it.

    A negative chord makes ``i`` negative, the guard still passes, and MATLAB
    dies indexing ``D(i+1)``.  Reproduced -- ``D(i+1)`` is evaluated first at
    ``:200``/``:221``, so that is the index the error names.
    """
    delta_chord = 0.1  # :196, :217

    i = int(mround(chord * 10))  # :198, :219

    if i + 1 < max_chords and i != 0:  # :199, :220
        if i + 1 < 1:
            raise MatlabIndexError(
                f"{table_name}({i + 1}): MATLAB subscripts must be positive "
                f"integers (dropsize.m indexes with round(chord * 10) and never "
                f"checks the sign; chord = {chord!r})"
            )
        if i < 1:
            raise MatlabIndexError(
                f"{table_name}({i}): MATLAB subscripts must be positive integers "
                f"(chord = {chord!r})"
            )
        delta_diameter = diameters[to0(i + 1)] - diameters[to0(i)]
        diameter = diameters[to0(i)] + (delta_diameter / delta_chord) * (
            chord - chords[to0(i)]
        )
    elif i == 0:  # :202, :223
        diameter = 0.0
    else:  # :205, :226
        diameter = OVERSIZE

    return float(diameter)


def vertical_chord_to_spherical_dia(vertical_chord):
    """``dropsize.m:192-209``.  See :func:`_chord_to_spherical_dia`."""
    return _chord_to_spherical_dia(
        vertical_chord,
        VERTICAL_CHORDS,
        VERTICAL_CHORD_ESD,
        MAX_VERTICAL_CHORDS,
        "vertical_chord_equivalent_spherical_diameters",
    )


def horizontal_chord_to_spherical_dia(horizontal_chord):
    """``dropsize.m:212-229``.  See :func:`_chord_to_spherical_dia`."""
    return _chord_to_spherical_dia(
        horizontal_chord,
        HORIZONTAL_CHORDS,
        HORIZONTAL_CHORD_ESD,
        MAX_HORIZONTAL_CHORDS,
        "horizontal_chord_equivalent_spherical_diameters",
    )


# --------------------------------------------------------------------------
# dropsize -- dropsize.m:1-187
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DropSize:
    """The seven returns of ``dropsize.m:1``, in MATLAB's order.

    Which of them are set depends entirely on how many array edges the image
    touches -- an image that touches an edge has an unknown true width, so the
    chords that need one are left at their ``:103-108`` initialisers.  Measured
    under Octave, with ``.`` for "left at zero":

    ====================  ======  ==========  ========  =======  ==========  ========
    branch                axis_r  circle_fit  horiz_ch  vert_ch  horiz_mean  spheroid
    ====================  ======  ==========  ========  =======  ==========  ========
    ``image_area < 1``    1.0     .           .         .        .           .
    2 edges, centre in    .       set         set       .        .           .
    2 edges, centre out   .       set         .         .        .           .
    1 edge, centre in     .       set         set       .        .           .
    1 edge, centre out    .       set         .         .        .           .
    0 edges               set     set         set       set      set         set
    ====================  ======  ==========  ========  =======  ==========  ========

    So ``axis_ratio`` is zero for every particle that touches an edge, and 1.0
    -- not zero -- for a particle too small to size.  Downstream code that reads
    it as a shape statistic is reading a branch indicator most of the time.
    """

    center_in: int
    axis_ratio: float
    diameter_circle_fit: float
    diameter_horiz_chord: float
    diameter_vert_chord: float
    diameter_horiz_mean: float
    diameter_spheroid: float

    def __iter__(self):
        """Unpack in MATLAB's return order, so a call site reads like ``:833``."""
        return iter((
            self.center_in,
            self.axis_ratio,
            self.diameter_circle_fit,
            self.diameter_horiz_chord,
            self.diameter_vert_chord,
            self.diameter_horiz_mean,
            self.diameter_spheroid,
        ))


def dropsize(
    max_horizontal_length,
    max_vertical_length,
    image_area,
    largest_edge_touching,
    smallest_edge_touching,
    diode_size,
    corrected_horizontal_diode_size,
    number_diodes_in_array,
):
    """``dropsize.m:1-187``.  Equivalent-volume-sphere sizing for liquid drops.

    Parameters mirror MATLAB's argument order exactly.  All are doubles at the
    call site -- they come from ``calculate_reject_unified``'s returns, which are
    counts and sums over a char matrix -- so none of the int16 traps that bite
    ``sizeDist.m:882-890`` apply here.

    Parameters
    ----------
    max_horizontal_length:
        ``images.image_length`` -- slices spanned, i.e. along-flight extent.
    max_vertical_length:
        ``images.longest_y_within_a_slice`` -- the longest run of shadowed
        diodes inside any one slice.
    image_area:
        Shadowed pixel count.  Below 1 the function returns early.
    largest_edge_touching, smallest_edge_touching:
        ``max`` and ``min`` of the top- and bottom-edge contact lengths
        (``imgProc_sm.m:828-829``).  The ordering is what makes ``:143`` dead.
    diode_size, corrected_horizontal_diode_size:
        Both ``handles.diodesize`` at both call sites, so their ratio is 1.0 in
        every real run.  See "Latent defects" in the module docstring for what
        happens when it is not.
    number_diodes_in_array:
        ``diodenum``.  Used only by the two-edge circle fit.

    Returns
    -------
    DropSize
        Unpackable in MATLAB's return order.
    """
    # :103-109 -- the initialisers that survive on every branch that does not
    # overwrite them.  This is why the table in DropSize has so many blanks.
    diameter_circle_fit = 0.0
    diameter_horiz_chord = 0.0
    diameter_vert_chord = 0.0
    diameter_horiz_mean = 0.0
    diameter_spheroid = 0.0
    axis_ratio = 0.0
    center_in = 0

    # :111
    scaling_factor_for_horizontal_lengths = (
        corrected_horizontal_diode_size / diode_size
    )

    corrected_diodes_added_to_length = 0  # :114

    # :116-125.  Note the early return uses the :114 initialiser, never the
    # scaled value assigned at :132 -- so every diameter comes back 0.0 even
    # when the scaling factor is not 1.
    if image_area < 1:
        diameter_circle_fit = corrected_diodes_added_to_length
        diameter_horiz_chord = corrected_diodes_added_to_length
        diameter_vert_chord = corrected_diodes_added_to_length
        diameter_horiz_mean = corrected_diodes_added_to_length
        diameter_spheroid = corrected_diodes_added_to_length
        center_in = 0
        axis_ratio = 1.0
        return DropSize(
            center_in,
            axis_ratio,
            float(diameter_circle_fit),
            float(diameter_horiz_chord),
            float(diameter_vert_chord),
            float(diameter_horiz_mean),
            float(diameter_spheroid),
        )

    # :129-132.  max_horizontal_length is rebound to its scaled self here, which
    # is what the :150 comparison below then gets wrong.
    largest_edge_touching_length = (
        largest_edge_touching * scaling_factor_for_horizontal_lengths
    )
    smallest_edge_touching_length = (
        smallest_edge_touching * scaling_factor_for_horizontal_lengths
    )
    max_horizontal_length = (
        max_horizontal_length * scaling_factor_for_horizontal_lengths
    )
    corrected_diodes_added_to_length = (
        DIODES_ADDED_TO_LENGTH * scaling_factor_for_horizontal_lengths
    )

    # :136-145 -- determine no. of edges.  The elseif is dead from imgProc_sm,
    # where smallest = min(top, bottom) <= largest = max(top, bottom).
    number_edges_touching = 0
    if largest_edge_touching > 0:
        number_edges_touching = number_edges_touching + 1
        if smallest_edge_touching > 0:
            number_edges_touching = number_edges_touching + 1
    elif smallest_edge_touching > 0:
        number_edges_touching = number_edges_touching + 1

    # :148-152.  Scaled length vs UNSCALED edge -- see "Latent defects".
    center_in = 1
    if max_horizontal_length <= largest_edge_touching:
        center_in = 0

    if number_edges_touching == 2 and center_in == 1:
        # :155-159.  Heymsfield-Parrish circle through both edge chords.  The
        # "+ is replaced by -" comment (Will, 2013-10-17) refers to the sign
        # inside the parentheses, not to the leading term.
        temp = number_diodes_in_array + (
            largest_edge_touching_length**2 - smallest_edge_touching_length**2
        ) / (4 * number_diodes_in_array)
        horizontal_size = math.sqrt(temp**2 + smallest_edge_touching_length**2)
        horizontal_chord = horizontal_size * diode_size
        diameter_circle_fit = horizontal_chord_to_spherical_dia(horizontal_chord)
        diameter_horiz_chord = horizontal_chord_to_spherical_dia(horizontal_chord)
    elif number_edges_touching == 2:
        # :161-165.  Same fit, but centre-out, so only the circle fit is
        # trusted; diameter_horiz_chord stays 0.
        largest_edge_touching_length = (
            largest_edge_touching_length + corrected_diodes_added_to_length
        )
        temp = number_diodes_in_array + (
            largest_edge_touching_length**2 - smallest_edge_touching_length**2
        ) / (4 * number_diodes_in_array)
        horizontal_size = math.sqrt(temp**2 + smallest_edge_touching_length**2)
        horizontal_chord = horizontal_size * diode_size
        diameter_circle_fit = horizontal_chord_to_spherical_dia(horizontal_chord)
    elif number_edges_touching == 1 and center_in == 1:
        # :167-169.  Second application of the diode-size correction; see
        # "Latent defects".
        horizontal_chord = (
            max_horizontal_length + DIODES_ADDED_TO_LENGTH
        ) * corrected_horizontal_diode_size
        diameter_horiz_chord = horizontal_chord_to_spherical_dia(horizontal_chord)
        diameter_circle_fit = horizontal_chord_to_spherical_dia(horizontal_chord)
    elif number_edges_touching == 1:
        # :171-175.  The only branch that uses diodes_added_to_height, and it
        # uses half of it.  max_vertical_length is rebound before the divide, so
        # the denominator cannot be zero unless it was -0.5.
        largest_edge_touching_length = (
            largest_edge_touching_length + corrected_diodes_added_to_length
        )
        max_vertical_length = max_vertical_length + DIODES_ADDED_TO_HEIGHT * 0.5
        horizontal_size = mdiv(
            0.25 * largest_edge_touching_length**2 + max_vertical_length**2,
            max_vertical_length,
        )
        horizontal_chord = horizontal_size * diode_size
        diameter_circle_fit = horizontal_chord_to_spherical_dia(horizontal_chord)
    else:
        # :177-185.  Entirely-in image: everything is measurable, so this is the
        # only branch that fills all seven returns.
        horizontal_chord = (
            max_horizontal_length + DIODES_ADDED_TO_LENGTH
        ) * corrected_horizontal_diode_size
        diameter_horiz_chord = horizontal_chord_to_spherical_dia(horizontal_chord)
        diameter_circle_fit = horizontal_chord_to_spherical_dia(horizontal_chord)
        # :180 uses diodes_added_to_LENGTH (0), not _to_height -- so the
        # vertical chord gets no addition either.
        vertical_chord = (max_vertical_length + DIODES_ADDED_TO_LENGTH) * diode_size
        # :181.  0/0 is NaN in MATLAB, not an exception -- mdiv keeps that.
        axis_ratio = float(mdiv(vertical_chord, horizontal_chord))
        diameter_vert_chord = vertical_chord_to_spherical_dia(vertical_chord)
        horizontal_mean_chord = math.sqrt(horizontal_chord * vertical_chord)
        diameter_horiz_mean = horizontal_chord_to_spherical_dia(horizontal_mean_chord)
        # :185.  exp(log(x)/3), not x**(1/3) -- kept verbatim: they differ in
        # the last ulp, and at x == 0 they differ in kind.  MATLAB's log(0) is
        # -Inf and exp(-Inf) is 0, where Python's math.log(0) raises; np.log
        # gives MATLAB's answer, so a zero-length particle returns 0.0 here
        # rather than blowing up.  Verified against Octave (both_zero_lengths).
        with np.errstate(divide="ignore", invalid="ignore"):
            diameter_spheroid = math.exp(
                np.log(horizontal_chord**2 * vertical_chord) / 3
            )

    return DropSize(
        center_in,
        float(axis_ratio),
        float(diameter_circle_fit),
        float(diameter_horiz_chord),
        float(diameter_vert_chord),
        float(diameter_horiz_mean),
        float(diameter_spheroid),
    )


# --------------------------------------------------------------------------
# Registration -- the registry seam
# --------------------------------------------------------------------------

register_size_definition(SizeDefinition(
    key="dropsize",
    func=dropsize,
    phase="liquid",
    description=(
        "Equivalent-volume-sphere diameters from measured chords, via the "
        "raindrop equilibrium-shape tables; circle fit after Heymsfield & "
        "Parrish (1978) for edge-touching images."
    ),
    provenance="dropsize.m:1-187, called at imgProc_sm.m:833",
    outputs=(
        "center_in",
        "axis_ratio",
        "diameter_circle_fit",
        "diameter_horiz_chord",
        "diameter_vert_chord",
        "diameter_horiz_mean",
        "diameter_spheroid",
    ),
))
