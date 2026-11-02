# SPDX-License-Identifier: BSD-3-Clause
"""Build a synthetic raw ``.2DS`` file with no campaign data required.

**Why this exists**: everything else a
stranger can run through this package needs either the ORACLES archive
(gitignored, campaign-restricted) or Octave (an external install). This tool
needs neither -- it hand-builds a raw SPEC file shaped exactly like a real
2D-S recording (the record geometry, the housekeeping packet layout, one
framed particle per second) and writes it to a path of the caller's choosing,
so the whole pipeline can be exercised in seconds::

    arrayprobe make-demo-flight base160101000000.2DS --seconds 5

This module lives inside the installed package rather than in ``scripts/``,
which ``pip install`` does not ship; ``scripts/make_demo_flight.py`` remains as
a re-export shim because the documentation publishes that path.

Then process it with ``arrayprobe run <config.toml> <flight> --yes`` (see
``examples/start_here/README.md``), or with ``run_flight.py``'s own ``DEMO_2DS_H`` preset
(a separate tool, with its own flags): ``run_flight.py --preset DEMO_2DS_H --engine 3.5
--profile stock-v3.5 --tas-file <aircraft.cdf> --stages 234 --yes base160101000000.2DS``.
Engine 3.1.4, the ORACLES-validation anchor, is not part of this package.

**The output filename must follow the SPEC ``base<YYMMDDhhmmss>`` convention**
(any valid-looking date/time; the demo data are synthetic regardless) --
``combine_sizedist`` reproduces the original's own behaviour of reading the
flight date from the raw stem (``combine_sizedist.m``, ``summaryfile(1).name``;
see ``docs/09-conventions.md``'s ``<stem>`` placeholder), so a
stage-4c combine fails on any other name. This is a faithful constraint, not a
bug in this tool: a name like ``demo.2DS`` runs stages 2-4 fine and only the
combine step needs the convention.

**Not validated science.** The synthetic particle is shaped to survive S3's
accept ladder (centred, aspect-ratio coherent) but its inter-arrival times are
arbitrary incrementing constants, not a realistic clock -- under the
production shattering configuration every one of them reads as a sub-6us
inter-arrival and is rejected, exactly as ``tests/test_end_to_end.py``
documents. The demo proves the pipeline *runs end to end and writes valid
files*; it is not a stand-in for the oracle-backed validation this project's
actual fidelity claims rest on. The :data:`DEMO_2DS_H` preset this module's
sibling ``run_flight.py`` carries says so in its own ``provenance`` field.

**One deliberate duplication.** ``tests/test_spec_reader.py`` already has
``run_word``/``image_packet``/``raw_file`` -- lower-level packet-framing
primitives used to test individual bit-layout decisions. This module does not
import them: a `scripts/` script that a `pip install`'d user runs cannot depend
on `tests/`, which the sdist does not even ship. The three primitives are
reproduced here, small and stable (they encode a fixed binary layout, not
project logic that could drift), and ``tests/test_end_to_end.py`` now imports
its synthetic flight builder *from this tool* rather than defining its own --
the direction the plan's own item names: "tests import from the tool, not the
reverse."
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np

from arrayprobe_uiops import spec_core as spec


def run_word(aa: int, bb: int, new_slice: bool = False) -> int:
    """One run-length word: ``aa`` shadowed diodes after ``bb`` clear ones."""
    assert 0 <= aa < 128 and 0 <= bb < 128
    return (0x4000 if new_slice else 0) | (aa << 7) | bb


def image_packet(runs, n_s, *, channel="H", pc=7, t_particle=0x1234ABCD, timing=False):
    """A ``'2S'`` image packet. ``runs`` are the run words; the timestamp is appended."""
    payload = [*runs, (t_particle >> 16) & 0xFFFF, t_particle & 0xFFFF]
    n = len(payload)
    flag = 4096 if timing else 0
    if channel == "H":
        return [spec.MARKER_2S, n | flag, 0, pc, n_s, *payload]
    return [spec.MARKER_2S, 0, n | flag, pc, n_s, *payload]


def _packet_counter(k: int, distinct: bool) -> int:
    """Particle-counter word for the ``k``-th image packet (0-based).

    Default: the constant 7 every demo has always written, so default output is
    byte-identical. ``distinct=True`` gives each packet its own counter,
    ``(7 + k) mod 65536`` (the counter is one 16-bit word), because SODA-2's
    ``spec_index`` keeps a frame only when the counter changes -- with a
    constant counter it sees one particle of the dense demo's 60.
    """
    return (7 + k) & 0xFFFF if distinct else 7


def raw_file(path, records) -> Path:
    """Write a raw ``.2DS``-shaped file: ``records`` is a list of (header, image words)."""
    out = np.zeros((len(records), spec.RECORD_WORDS), dtype="<u2")
    for i, (header, image) in enumerate(records):
        out[i, : spec.HEADER_WORDS] = header
        out[i, spec.HEADER_WORDS : spec.HEADER_WORDS + len(image)] = image
    out.tofile(path)
    return Path(path)


def _drop_runs():
    """A small closed loop of shadowed diodes -- lit, a ring of shadow, lit
    again -- framed as one real, accepted particle through S3's reject
    ladder. Centred near diode 60-62 rather than the array edge:
    ``image_center_in`` requires the shape to sit away from the edge of the
    128-diode array.
    """
    return [run_word(2, 62), run_word(2, 60, new_slice=True),
            run_word(2, 60, new_slice=True), run_word(2, 62, new_slice=True)]


def _hk_words(tas_mps: float, time_of_day: float) -> list[int]:
    """One housekeeping packet: TAS at word 49-50 (float32, split high/low),
    time-of-day at 51-52 -- the fields ``SidecarWriter`` reads for the
    ``.tas.csv`` sidecar S4 needs.
    """
    words = [0] * 60
    words[0] = spec.MARKER_HK
    raw = np.float32(tas_mps).view(np.uint32).item()
    words[49] = raw >> 16
    words[50] = raw & 0xFFFF
    words[51], words[52] = int(time_of_day // 65536), int(time_of_day % 65536)
    return words


def build_demo_flight(path, n_seconds: int = 5, tas_mps: float = 130.0,
                       start_hour: int = 6, start_minute: int = 6,
                       start_second: int = 40, distinct_counters: bool = False) -> Path:
    """Write a synthetic raw ``.2DS`` file: one accepted-shaped H-channel
    particle and one HK (TAS) packet per second, starting at
    ``start_hour:start_minute:start_second`` UTC on an arbitrary date.
    """
    records = []
    for sec in range(n_seconds):
        header = (2016, 9, 2, 6, start_hour, start_minute, start_second + sec, 250)
        pkt = image_packet(_drop_runs(), 4, channel="H",
                           pc=_packet_counter(sec, distinct_counters),
                           t_particle=0x1234ABCD + sec)
        records.append((header, pkt))
        tod = start_hour * 3600 + start_minute * 60 + start_second + sec
        records.append((header, _hk_words(tas_mps, tod)))
    return raw_file(str(path), records)


#: A realistic aircraft airspeed series for the demo, so the quickstart runs on engine
#: 3.5 (the default), which refuses to size a 2D-S without an aircraft TAS file
#: (``imgProc_sm.m:183-185``). Derived, not invented: 60 s of ARM AAF ``true_airspeed`` (m/s,
#: public ARM data) from ``enaaafmergedF1.c1.20170706.082313.nc``, 09:40:00-09:40:59 UTC,
#: each value multiplied by 0.9565335751997573 -- one draw of
#: ``numpy.random.default_rng(387).uniform(0.85, 1.15)`` -- and rounded to 0.01 m/s, so it
#: reads like an aircraft record and matches no real flight.
DEMO_AIRCRAFT_TAS_MPS = (
    96.94, 96.72, 95.95, 96.22, 96.12, 95.84, 96.02, 96.02, 96.03, 96.28,
    96.76, 95.8, 96.13, 95.89, 96.0, 95.36, 96.54, 94.95, 96.33, 96.42,
    96.17, 95.65, 95.84, 95.37, 96.18, 96.43, 95.12, 94.89, 94.91, 95.98,
    95.48, 96.13, 96.49, 95.88, 95.09, 95.31, 94.84, 94.54, 94.94, 95.02,
    95.06, 94.3, 95.57, 94.54, 96.33, 94.61, 95.81, 93.3, 94.13, 96.17,
    95.57, 92.62, 93.68, 93.28, 96.44, 93.29, 94.84, 90.48, 91.95, 93.06,
)


def demo_aircraft_path(raw_path) -> Path:
    """Where :func:`write_demo_aircraft` puts the demo flight's aircraft file."""
    raw_path = Path(raw_path)
    return raw_path.with_name(raw_path.stem + ".aircraft.cdf")


def write_demo_aircraft(raw_path, n_seconds: int = 5, start_hour: int = 6,
                        start_minute: int = 6, start_second: int = 40,
                        margin_s: int = 10) -> Path:
    """Write ``<stem>.aircraft.cdf`` beside a demo flight: ``Time`` (HHMMSS) and ``TAS`` (m/s).

    Covers the flight's records plus ``margin_s`` seconds either side, so every image
    record's second finds a sample (``imgProc_sm.m:727`` looks it up by exact equality).
    Values cycle through :data:`DEMO_AIRCRAFT_TAS_MPS`.
    """
    from arrayprobe.tools.make_tas_file import write_tas_file

    t0 = start_hour * 3600 + start_minute * 60 + start_second - margin_s
    n = n_seconds + 2 * margin_s
    tod = [(t0 + i) % 86400 for i in range(n)]
    hhmmss = [float((s // 3600) * 10000 + (s % 3600 // 60) * 100 + s % 60) for s in tod]
    tas = [DEMO_AIRCRAFT_TAS_MPS[i % len(DEMO_AIRCRAFT_TAS_MPS)] for i in range(n)]
    return write_tas_file(demo_aircraft_path(raw_path), hhmmss, tas, provenance={
        "source": "demo: ARM AAF true_airspeed 2017-07-06 09:40 UTC excerpt x 0.9565",
    })


def disk_runs(diameter: int, x0: int) -> list[int]:
    """A filled circle ``diameter`` diodes across, left edge at diode ``x0``
    ("test your thresholds" example data).

    One run word per slice: a horizontal chord ``2w+1`` diodes wide, centred
    on the circle's own centre column, ``w = floor(sqrt(r**2 - (j-c)**2))``
    with ``r = diameter/2``, ``c = (diameter-1)/2``. A filled disk's area
    ratio is close to ``pi/4`` (~0.79, measured on the proc file this writes),
    comfortably above both ``area_ratio_z`` thresholds (0.5, 0.2) -- these
    shapes exist to land in used bins, not to test that threshold.
    """
    r = diameter / 2
    c = (diameter - 1) / 2
    runs = []
    for j in range(diameter):
        w = int(math.floor(math.sqrt(max(r * r - (j - c) ** 2, 0.0))))
        aa = 2 * w + 1
        bb = x0 + int(c) - w
        runs.append(run_word(aa, bb, new_slice=(j > 0)))
    return runs


#: The measured deviation from the plan (S3.2): a genuinely one-diode-wide
#: outline (the plan's original description) landed at area ratio ~0.15 for
#: every diameter tried (measured 2026-09-13) -- BELOW both ``area_ratio_z``
#: thresholds (0.2, 0.5), because the outline's area shrinks linearly with
#: diameter while the normalising circle grows quadratically (``area_ratio ~
#: 8/(pi*diameter)`` for a 1-diode outline). No diameter separates the two
#: thresholds that way. :func:`ring_runs` is a true **annulus** instead --
#: outer diameter ``diameter``, hole diameter ``round(RING_HOLE_FRACTION *
#: diameter)`` -- whose area ratio is tunable by the hole fraction alone
#: (``~= 1 - RING_HOLE_FRACTION**2``, independent of diameter) and calibrated
#: to land between the two thresholds; see :data:`DENSE_RING_DIAMETER`'s
#: measured numbers.
RING_HOLE_FRACTION: float = 0.8


def ring_runs(diameter: int, x0: int) -> list[int]:
    """A hollow disk (annulus) -- outer diameter ``diameter``, left edge at
    diode ``x0`` -- to move the ``area_ratio_z`` threshold (
    see :data:`RING_HOLE_FRACTION` for why this is an annulus and not a bare
    outline).

    Each slice is either one filled run (the polar caps, where the hole does
    not reach) or two runs -- left arc, right arc -- separated by the
    uncovered hole. Run words after the first *in the same slice* are
    **relative**: ``spec.py``'s decoder accumulates ``b_base`` across a
    slice's runs (``read_binary_SPEC.m:223-241``), so a second run's ``bb``
    is the gap *from the end of the previous run*, not an absolute diode
    index -- this is the bug the plan's own outline draft had (measured
    2026-09-13: an absolute second ``bb`` decoded ~50 diodes past the
    intended wall).
    """
    r_out = diameter / 2
    r_in = RING_HOLE_FRACTION * r_out
    c = (diameter - 1) / 2
    runs = []
    for j in range(diameter):
        w_out = int(math.floor(math.sqrt(max(r_out * r_out - (j - c) ** 2, 0.0))))
        w_in_sq = r_in * r_in - (j - c) ** 2
        if w_in_sq <= 0:
            # The polar cap: the hole does not reach this slice, so it is a
            # filled chord, exactly like one slice of :func:`disk_runs`.
            aa = 2 * w_out + 1
            bb = x0 + int(c) - w_out
            runs.append(run_word(aa, bb, new_slice=(j > 0)))
            continue
        w_in = int(math.floor(math.sqrt(w_in_sq)))
        left_len = w_out - w_in
        right_len = w_out - w_in
        left_start = x0 + int(c) - w_out
        runs.append(run_word(left_len, left_start, new_slice=(j > 0)))
        gap = 2 * w_in + 1  # the uncovered hole, between the two arcs
        runs.append(run_word(right_len, gap, new_slice=False))
    return runs


def bar_runs(length_slices: int, width_diodes: int, x0: int) -> list[int]:
    """A filled rectangle, ``length_slices`` slices of ``width_diodes``
    contiguous shadowed diodes starting at diode ``x0`` -- to move the
    ``max_comp_img_ar`` aspect-ratio threshold. Fully filled
    (area ratio 1.0), so it cannot also trip ``area_ratio_z``: it exists to
    test the aspect-ratio ceiling alone.
    """
    return [run_word(width_diodes, x0, new_slice=(j > 0)) for j in range(length_slices)]


#: Diameters for the "disk" shape, spanning 6-40 diodes
#: (60-400 um at the 2D-S's 10 um diode) so particles land across used bins
#: 6-40 rather than piling into one. Fixed rather than a continuous draw so a
#: reader can reproduce the exact set of bins exercised without re-running
#: the generator.
DENSE_DISK_DIAMETERS: tuple[int, ...] = (6, 8, 10, 14, 18, 22, 26, 30, 34, 40)

#: A single fixed ring diameter, not drawn from a range: S3.2 calls for
#: *verifying* the area-ratio crossing against the proc file rather than
#: assuming it, which only makes sense for one calibrated shape. 16 diodes
#: is what this module was calibrated against (see the docstring of
#: :func:`build_dense_demo_flight`).
DENSE_RING_DIAMETER: int = 16

#: The bar geometry named directly in the plan (S3.2): aspect ratio 9/2 = 4.5,
#: strictly between ``ORACLES_PRODUCTION_REJECT_CONFIG.max_comp_img_ar`` (4)
#: and ``DEFAULT_REJECT_CONFIG.max_comp_img_ar`` (5).
DENSE_BAR_LENGTH_SLICES: int = 9
DENSE_BAR_WIDTH_DIODES: int = 2

#: The particle-clock gap design (raw counts) for the shattering/inter-arrival
#: test, named as module constants rather than inline literals so
#: ``tests/test_demo_flight_thresholds.py`` can patch :data:`DENSE_GAP_SHORT`
#: to :data:`DENSE_GAP_LONG`'s value and show the test it guards actually
#: fires (the plan's own "mutation for this guard"). At ``tas_mps=130`` and
#: the 2D-S's 10 um diode, :data:`DENSE_GAP_SHORT` reads back as a sub-6-us
#: gap (a shattering candidate) and :data:`DENSE_GAP_LONG` as safely above it
#: -- confirmed against a built proc file's own ``inter_arrival``, not
#: assumed (see :func:`build_dense_demo_flight`).
DENSE_GAP_SHORT: int = 20
DENSE_GAP_LONG: int = 4000

def _gap_safe_indices(particles_per_second: int) -> list[int]:
    """0-based indices, within one record, that ``sizedist.py``'s shattering
    ladder (``:1375-1382``) never flags 'S' under this module's own gap
    design.

    Index 0 is always flagged (the record-boundary reset, ``imgproc.py:967-
    972``). For ``ix`` in ``1 .. particles_per_second-1``, a design gap of 20
    counts at particle ``ix+1`` (this module's ``j % 3 == 1`` rule) flags
    **both** ``ix`` and ``ix-1`` (``sizedist.py:1381-1382``: ``auto_reject[ix
    - 1:ix + 1] = 'S'``). Measured 2026-09-13: without this, a shape drawn at
    an unsafe position is rejected by the shattering test regardless of any
    OTHER threshold, which silently zeroed test 3's (``max_comp_img_ar``)
    used-bin difference the first time this flight was built -- every bar
    happened to land on a flagged position. Bars are pinned to these safe
    slots below so the aspect-ratio test can never be masked that way.
    """
    unsafe = {0}
    for ix in range(1, particles_per_second):
        if ix % 3 == 0:
            unsafe.add(ix - 1)
            unsafe.add(ix)
    return [i for i in range(particles_per_second) if i not in unsafe]


def build_dense_demo_flight(path, n_seconds: int = 20, seed: int = 20260913,
                            particles_per_second: int = 12, tas_mps: float = 130.0,
                            start_hour: int = 6, start_minute: int = 6,
                            start_second: int = 40,
                            distinct_counters: bool = False) -> Path:
    """Write a DENSE synthetic raw ``.2DS`` file: example data users can
    "test their thresholds" on.

    The plain :func:`build_demo_flight` cannot: its five particles sit below
    the first used bin's lower edge (0.055 mm) and every ``inter_arrival`` is
    identically zero (each is the only particle of its record), so no reject
    or shattering threshold can ever move a used-bin count -- measured, S3.1.
    This flight fixes both. Per second, one record holds
    ``particles_per_second`` image packets **concatenated in the same
    record** (each sized to survive S3's centring and accept ladder -- see
    :func:`disk_runs`/:func:`ring_runs`/:func:`bar_runs`), followed by the
    housekeeping (TAS) record as before. Per record: exactly 2 bars, pinned
    to :func:`_gap_safe_indices` slots (never shatter-flagged, so the
    aspect-ratio test is never confounded by the shattering test); up to 2
    rings at random remaining positions; the rest disks. ``rng =
    np.random.default_rng(seed)`` makes the flight fully reproducible: the
    same seed always draws the same diameters, ring positions and disk
    positions.

    **Multi-particle records are not new plumbing.** ``spec.get_img`` already
    walks its whole 2048-word window for repeated ``MARKER_2S`` packets (real
    2D-S records hold many small particles); this only exercises a path the
    plain demo flight, at one particle per record, never has.

    **The inter-arrival design.** ``imgproc.py:967-972`` (preserved bug)
    zeroes ``inter_arrival`` for the first particle of every
    record, so only particles 2..``particles_per_second`` within a record
    carry a real gap. For the ``j``-th particle of a record (1-based, ``j >
    1``), the particle clock advances by 20 raw counts when ``j % 3 == 1``,
    else 4000. At ``tas_mps=130`` and the 2D-S's 10 um diode, one count is
    ``ds / 1e3 / TAS`` seconds (``imgproc.py:955``) -- confirmed against a
    built proc file, not assumed: 20 counts reads back as a sub-6-us gap
    (shattering-candidate) and 4000 as a safely-supra-6-us one, against
    ``sizeDist``'s per-probe default threshold (the twelfth
    argument). The record-boundary reset supplies additional close-together
    (zero-gap) events for free.

    Raw file record count is exactly ``2 * n_seconds`` (one image record, one
    HK record, per second) -- a stranger can predict the file size from that
    alone, as :func:`build_demo_flight` already documents.
    """
    rng = np.random.default_rng(seed)
    safe = _gap_safe_indices(particles_per_second)
    # Two bars per record, pinned to gap-safe slots (see _gap_safe_indices) so
    # the aspect-ratio test never competes with the shattering test. Up to two
    # rings per record at whatever positions remain, drawn once per record so
    # a record's ring count never depends on how many safe slots existed.
    bar_slots = set(safe[:2])
    records = []
    t_particle = 0x1000_0000
    n_packets = 0
    for sec in range(n_seconds):
        header = (2016, 9, 2, 6, start_hour, start_minute, start_second + sec, 250)
        non_bar = [i for i in range(particles_per_second) if i not in bar_slots]
        n_rings = min(2, len(non_bar))
        ring_slots = (set(rng.choice(non_bar, size=n_rings, replace=False).tolist())
                     if n_rings else set())
        payload: list[int] = []
        for j in range(1, particles_per_second + 1):
            i = j - 1
            if i in bar_slots:
                shape = "bar"
            elif i in ring_slots:
                shape = "ring"
            else:
                shape = "disk"
            if shape == "disk":
                diameter = int(rng.choice(DENSE_DISK_DIAMETERS))
                x0 = int(rng.integers(16, 112 - diameter))
                runs = disk_runs(diameter, x0)
                n_s = diameter
            elif shape == "ring":
                diameter = DENSE_RING_DIAMETER
                x0 = int(rng.integers(16, 112 - diameter))
                runs = ring_runs(diameter, x0)
                n_s = diameter
            else:
                x0 = int(rng.integers(16, 112 - DENSE_BAR_WIDTH_DIODES))
                runs = bar_runs(DENSE_BAR_LENGTH_SLICES, DENSE_BAR_WIDTH_DIODES, x0)
                n_s = DENSE_BAR_LENGTH_SLICES
            if j > 1:
                t_particle += DENSE_GAP_SHORT if (j % 3 == 1) else DENSE_GAP_LONG
            payload.extend(image_packet(runs, n_s, channel="H",
                                        pc=_packet_counter(n_packets, distinct_counters),
                                        t_particle=t_particle))
            n_packets += 1
        records.append((header, payload))
        tod = start_hour * 3600 + start_minute * 60 + start_second + sec
        records.append((header, _hk_words(tas_mps, tod)))
        # The gap to next record's first particle is unobservable: :967-972
        # always writes 0 for a record's first particle regardless of the
        # clock value, so this advance exists only to keep the 32-bit clock
        # monotonically increasing across the whole file (never wrapping).
        t_particle += DENSE_GAP_LONG
    return raw_file(str(path), records)


# ---------------------------------------------------------------------------
# The FEATURE flight: the instrument faults the corrections act on
# ---------------------------------------------------------------------------
#
# The plain and dense flights above are clean by construction, so every enhancement
# whose subject is a *fault* -- a clipped particle, an out-of-focus ring, a stuck or
# noisy diode, a duplicated housekeeping second, a clock glitch -- measured an
# A/B of exactly zero on them (the vacuous A/Bs of 2026-09-14/15: A7, Z8, Z21, GL4).
# :func:`build_feature_demo_flight` writes one more flight, alongside and never in
# place of those two (their bytes are tracked and tested), that carries one of each.
# Every feature is listed in :data:`FEATURES` with the MATLAB line it exercises; every
# particle is listed, in raw order, by :func:`feature_particle_manifest`, which the
# tests read to find each feature in the decoded output.

#: The 2D-S array width, in diodes (``read_binary_SPEC.m``'s 128-bit slice).
N_DIODES: int = 128

#: Particle-clock advances (raw counts) for the feature flight: ``FEATURE_GAP_LONG``
#: between ordinary particles (a supra-6-us gap at 130 m/s, the dense flight's own
#: :data:`DENSE_GAP_LONG`), ``FEATURE_GAP_BURST`` inside a shattering burst (the dense
#: flight's sub-6-us :data:`DENSE_GAP_SHORT`).
FEATURE_GAP_LONG: int = 4000
FEATURE_GAP_BURST: int = 20

#: Disk diameters (diodes) for the ordinary particles: 0.12-0.48 mm at the 2D-S's
#: 10 um diode, so they fill the v3.1.4 grid's used bins (6+, above 0.055 mm) AND
#: v3.5's 2D-S grid, which starts at 0.2 mm (measured on this flight's v3.5 sd:
#: ``bin_min[0] = 0.2``) -- the dense flight's 0.06-0.40 mm disks mostly fall below it.
FEATURE_DISK_MIN: int = 12
FEATURE_DISK_MAX: int = 48

#: The stuck diode (1-based) -- shadowed in every slice of every particle of the
#: stuck-diode seconds -- and the noisy diode, which fires isolated one-pixel
#: particles. Both are well away from the particles' own bodies and from diode 32,
#: so neither is confounded with the 32-diode hollow packing (A1).
FEATURE_STUCK_DIODE: int = 100
FEATURE_NOISY_DIODE: int = 20

#: What the feature flight carries, one entry per feature: the one-second record it
#: occupies (0-based second index, see :func:`build_feature_demo_flight`), the
#: MATLAB line(s) the feature exercises, and the enhancement(s) whose A/B it exists
#: to make non-vacuous. Read by the tests, which assert each is present in the
#: decoded output rather than trusting this table.
FEATURES: dict[str, dict] = {
    "background": {
        "seconds": (0, 1, 2, 3, 13),
        "matlab": "sizeDist.m:1080-1100 (good/bad split): ordinary accepted disks",
        "for": "the used-bin population every sd-level A/B is measured against",
    },
    "edge_clipped": {
        "seconds": (4,),
        "matlab": ("calculate_reject_unified.m:213-216 (touching_edge 't'); "
                   "imgProc_sm.m:897 (touching_edge - '0' = 68); sizeDist.m:1094-1100 "
                   "(entirein / centerin masks)"),
        "for": "A7 partial_image_habit (Korolev & Sussman 2000 partials), SAmethod 1",
    },
    "hollow_ring": {
        "seconds": (5,),
        "matlab": ("calculate_reject_unified.m:279-280, :408-530 (is_it_hollow, "
                   "rej_hollow=1 -> 'h'); :465 (32-diode packing, A1); v3.5 "
                   "is_it_hollow (no middle-third window) and imgProc_sm.m:1276 "
                   "(D/size_factor)"),
        "for": "A1 wide_hollow_fix, A3 spot_edge_fix, A12 outoffocus, C5 hole_edge_swap, GL4",
    },
    "one_diode_streak": {
        "seconds": (6,),
        "matlab": ("calculate_reject_unified.m:269 (max_comp_img_ar -> 'a'); "
                   "sizeDist.m:1316-1340 (a second with data but no accepted particle)"),
        "for": "spec_artefact_filter line noise, A8 overload_accounting_fix",
    },
    "stuck_diode": {
        "seconds": (7, 8),
        "matlab": ("read_binary_SPEC.m:223-241 (a second run in the same slice); "
                   "calculate_reject_unified.m:188-196 (split), :228 (>80% block)"),
        "for": "ml_accept_reject Method A (stuck-diode merge), spec_artefact_filter",
    },
    "noisy_diode": {
        "seconds": (9,),
        "matlab": "imgProc_sm.m diode_stats (per-diode shadow counts); one-pixel particles",
        "for": "spec_artefact_filter's noisy-diode exception and dot noise",
    },
    "shattering_burst": {
        "seconds": (10,),
        "matlab": ("sizeDist.m:874 (6 us default threshold), :1375-1382 ('S' on both "
                   "neighbours), :1036/:1169 (reacceptance scans the first event only)"),
        "for": ("D3 reaccept_every_event_fix, intarr_policy, distance_rejection, "
                "poisson_restore"),
    },
    "duplicated_tas_second": {
        "seconds": (11,),
        "matlab": ("sizeDist.m:88 (floor to whole seconds), :476 (one_sec_times = "
                   "tas_time), :627-644 (an empty [t, t) interval still consumes its "
                   "particles)"),
        "for": "A17 tas_grid_fix",
    },
    "missing_tas_second": {
        "seconds": (12,),
        "matlab": "sizeDist.m:476, :549-596 (a gap in one_sec_times)",
        "for": "A17 tas_grid_fix (the other half: a second with no housekeeping)",
    },
    "bad_particle_timestamp": {
        "seconds": (14,),
        "matlab": ("imgProc_sm.m:379 (Time from the record header); sizeDist.m:544-545 "
                   "(x(find(diff(x)<0)+1:end) += 240000 -- one glitch files every later "
                   "particle 24 h late)"),
        "for": "the CIP timestamp cascade (the rollover_fix enhancement)",
    },
    "cascade_victims": {
        "seconds": (15, 16),
        "matlab": "sizeDist.m:544-545 (the particles after the glitch)",
        "for": "the measured size of the cascade",
    },
    "last_record_particles": {
        "seconds": (17,),
        "matlab": ("read_binary_SPEC.m (the final record is never a primary: the loop "
                   "decodes (N, N+1) and breaks on EOF)"),
        "for": "E5 last_record_fix",
    },
}

#: The header second of the one glitched record, as an HHMMSS offset: the record
#: carries 00:MM:SS instead of 06:MM:SS -- a six-hour backwards jump, the shape of a
#: corrupted hour field. It is the one decrease in the particle ``Time`` series.
FEATURE_GLITCH_HOUR: int = 0

#: The duplicated second's second housekeeping packet carries this TAS, so which of
#: the two rows survives a collapse (A17: the first, MATLAB's unique(...,'first')) is
#: visible in the output rather than inferred.
FEATURE_DUPLICATE_TAS_MPS: float = 131.0


def _runs_from_image(img) -> list[int]:
    """Run words for a boolean image of shape ``(n_slices, 128)`` (True = shadowed).

    The inverse of ``spec._decode_runs_scalar`` (``read_binary_SPEC.m:223-241``): the
    first run of a slice carries its clear count from diode 1 and the new-slice flag
    (on every slice but the first); later runs in the same slice carry the clear gap
    from the end of the previous run -- the relative encoding :func:`ring_runs`
    documents. An all-clear slice is one ``aa = 0`` word, which the decoder turns
    into an empty run.
    """
    img = np.asarray(img, dtype=bool)
    assert img.ndim == 2 and img.shape[1] == N_DIODES
    runs: list[int] = []
    for j, row in enumerate(img):
        padded = np.concatenate(([False], row, [False])).astype(np.int8)
        edges = np.flatnonzero(np.diff(padded))
        starts, ends = edges[0::2], edges[1::2]
        if starts.size == 0:
            runs.append(run_word(0, 0, new_slice=(j > 0)))
            continue
        prev_end = 0
        for k, (s, e) in enumerate(zip(starts, ends, strict=True)):
            runs.append(run_word(int(e - s), int(s - prev_end), new_slice=(j > 0 and k == 0)))
            prev_end = int(e)
    return runs


def _disk_image(diameter: int, centre: float) -> np.ndarray:
    """A filled disk ``diameter`` slices long, centred on 0-based column ``centre``,
    clipped to the 128-diode array (a disk centred near an end is a clipped,
    edge-touching particle)."""
    r = diameter / 2
    c = (diameter - 1) / 2
    img = np.zeros((diameter, N_DIODES), dtype=bool)
    for j in range(diameter):
        w = math.sqrt(max(r * r - (j - c) ** 2, 0.0))
        lo = int(math.floor(centre - w + 0.5))
        hi = int(math.floor(centre + w + 0.5))
        img[j, max(lo, 0):min(hi + 1, N_DIODES)] = True
    return img


def _annulus_image(diameter: int, hole_fraction: float, left: int,
                   spot_diameter: int = 0) -> np.ndarray:
    """An annulus (an out-of-focus drop's bright centre), outer diameter
    ``diameter``, hole diameter ``hole_fraction * diameter``, leftmost diode at
    0-based column ``left``; ``spot_diameter > 0`` adds Korolev's central (Poisson)
    spot inside the hole."""
    r_out = diameter / 2
    r_in = hole_fraction * r_out
    c = (diameter - 1) / 2
    yy, xx = np.mgrid[0:diameter, 0:diameter]
    rr = np.hypot(yy - c, xx - c)
    body = (rr <= r_out) & (rr > r_in)
    if spot_diameter:
        body |= rr <= spot_diameter / 2
    img = np.zeros((diameter, N_DIODES), dtype=bool)
    img[:, left:left + diameter] = body
    return img


def _streak_image(length_slices: int, diode: int) -> np.ndarray:
    """One diode (1-based) shadowed for ``length_slices`` consecutive slices."""
    img = np.zeros((length_slices, N_DIODES), dtype=bool)
    img[:, diode - 1] = True
    return img


def _record_header(hour: int, minute: int, second: int) -> tuple:
    """The eight header words (``readRecord``, :170-182), the demo flights' own
    date and millisecond."""
    return (2016, 9, 2, 6, hour, minute, second, 250)


def _feature_seconds(rng) -> list[dict]:
    """The flight's content, second by second: a list of dicts with the particle
    images (``shapes``: list of ``(feature, image, gap)``), whether the second gets
    housekeeping (``hk``: 0, 1 or 2 packets) and whether its header time is the
    glitch. Drawn once from ``rng`` so the flight is reproducible from its seed."""

    def disks(n, feature="background", lo=FEATURE_DISK_MIN, hi=FEATURE_DISK_MAX):
        out = []
        for _ in range(n):
            d = int(rng.integers(lo, hi + 1))
            centre = float(rng.integers(34 + d // 2, 95 - d // 2))
            out.append((feature, _disk_image(d, centre), FEATURE_GAP_LONG))
        return out

    secs: list[dict] = []
    for _ in range(4):                                     # 0-3: background
        secs.append({"shapes": disks(8), "hk": 1})
    # 4: edge-clipped -- three disks clipped at diode 1, three at diode 128, of
    # growing size (the clipped fraction grows with it), and two whole disks.
    edge = []
    for d, off in ((16, 2.0), (30, 4.0), (44, 6.0)):
        edge.append(("edge_clipped", _disk_image(d, off), FEATURE_GAP_LONG))
        edge.append(("edge_clipped", _disk_image(d, N_DIODES - 1 - off), FEATURE_GAP_LONG))
    secs.append({"shapes": edge + disks(2), "hk": 1})
    # 5: hollow rings -- three inside diodes 1-32 (the only span v3.1.4's hollow
    # test packs, :465), three beyond it; hole fractions spanning a thin and a thick
    # ring; two carry a Poisson spot.
    rings = []
    for d, frac, left, spot in ((24, 0.5, 2, 0), (28, 0.6, 2, 0), (22, 0.45, 5, 4),
                                (30, 0.5, 50, 0), (40, 0.65, 44, 0), (34, 0.5, 70, 6)):
        rings.append(("hollow_ring", _annulus_image(d, frac, left, spot), FEATURE_GAP_LONG))
    secs.append({"shapes": rings + disks(2), "hk": 1})
    # 6: one-diode streaks only -- a second whose every particle is an artefact.
    streaks = [("one_diode_streak", _streak_image(n, dio), FEATURE_GAP_LONG)
               for n, dio in ((30, 45), (40, 64), (24, 90), (36, 110))]
    secs.append({"shapes": streaks, "hk": 1})
    # 7-8: stuck diode -- every particle also shadows FEATURE_STUCK_DIODE in every slice.
    for _ in range(2):
        stuck = []
        for feature, img, gap in disks(6, "stuck_diode", lo=12, hi=30):
            img = img.copy()
            img[:, FEATURE_STUCK_DIODE - 1] = True
            stuck.append((feature, img, gap))
        secs.append({"shapes": stuck, "hk": 1})
    # 9: noisy diode -- ten one-pixel particles on FEATURE_NOISY_DIODE among four disks.
    noisy = [("noisy_diode", _streak_image(1, FEATURE_NOISY_DIODE), FEATURE_GAP_LONG)
             for _ in range(10)]
    mixed = disks(4)
    secs.append({"shapes": noisy[:5] + mixed[:2] + noisy[5:] + mixed[2:], "hk": 1})
    # 10: shattering burst -- two bursts of six (sub-6-us gaps) separated by long gaps,
    # a larger "parent" drop opening each, then two isolated disks.
    burst = []
    for _ in range(2):
        burst.append(("shattering_burst", _disk_image(40, 64.0), FEATURE_GAP_LONG))
        for _k in range(6):
            d = int(rng.integers(6, 14))
            burst.append(("shattering_burst", _disk_image(d, float(rng.integers(30, 98))),
                          FEATURE_GAP_BURST))
    secs.append({"shapes": burst + disks(2), "hk": 1})
    secs.append({"shapes": disks(6, "duplicated_tas_second"), "hk": 2})    # 11
    secs.append({"shapes": disks(6, "missing_tas_second"), "hk": 0})       # 12
    secs.append({"shapes": disks(8), "hk": 1})                             # 13
    secs.append({"shapes": disks(1, "bad_particle_timestamp", 30, 30),     # 14
                 "hk": 1, "glitch": True})
    for _ in range(2):                                                     # 15-16
        secs.append({"shapes": disks(6, "cascade_victims"), "hk": 1})
    secs.append({"shapes": disks(4, "last_record_particles"), "hk": 1,     # 17
                 "last": True})
    return secs


def feature_particle_manifest(seed: int = 20260915) -> list[dict]:
    """Every particle of :func:`build_feature_demo_flight` in raw order:
    ``{"second", "feature", "n_slices", "width", "min_diode", "max_diode", "area"}``
    (diodes 1-based). Recomputed from the same seed, never stored, so it cannot
    drift from the flight it describes."""
    rng = np.random.default_rng(seed)
    out = []
    for sec, spec_ in enumerate(_feature_seconds(rng)):
        for feature, img, _gap in spec_["shapes"]:
            cols = np.flatnonzero(img.any(axis=0))
            out.append({
                "second": sec, "feature": feature, "n_slices": int(img.shape[0]),
                "width": int(cols.size and cols[-1] - cols[0] + 1),
                "min_diode": int(cols[0] + 1) if cols.size else 0,
                "max_diode": int(cols[-1] + 1) if cols.size else 0,
                "area": int(img.sum()),
            })
    return out


def build_feature_demo_flight(path, seed: int = 20260915, tas_mps: float = 130.0,
                              start_hour: int = 6, start_minute: int = 6,
                              start_second: int = 40) -> Path:
    """Write the FEATURE synthetic raw ``.2DS`` file: eighteen
    one-second records carrying, second by second, the faults :data:`FEATURES`
    lists -- edge-clipped particles at both array ends, hollow and Poisson-spot
    rings inside and beyond diode 32, one-diode streaks, a stuck and a noisy diode,
    a two-event shattering burst, a duplicated and a missing housekeeping (TAS)
    second, one record whose header hour is corrupted (the one decrease in the
    particle ``Time`` series, ``sizeDist.m:544-545``), and particles in the file's
    final record (which ``read_binary_SPEC.m`` never decodes as a primary).

    Record order per second: the image record, then its housekeeping packet(s) --
    except the final second, whose housekeeping record comes *first* so that its
    image record is the last record of the file. The glitched second's housekeeping
    record carries the correct header time (only the image record's hour is
    corrupted), so the TAS grid itself never goes backwards and the missing second
    stays the only gap in it -- only the particle times go backwards, which is the
    CIP shape. Not validated science, exactly as the other two flights.
    """
    rng = np.random.default_rng(seed)
    records = []
    t_particle = 0x2000_0000
    t0 = start_hour * 3600 + start_minute * 60 + start_second
    for sec, spec_ in enumerate(_feature_seconds(rng)):
        tod = t0 + sec
        hh, mm, ss = tod // 3600, (tod % 3600) // 60, tod % 60
        header = _record_header(hh, mm, ss)
        image_header = _record_header(FEATURE_GLITCH_HOUR, mm, ss) if spec_.get("glitch") \
            else header
        payload: list[int] = []
        for k, (_feature, img, gap) in enumerate(spec_["shapes"]):
            if k > 0:
                t_particle += gap
            payload.extend(image_packet(_runs_from_image(img), img.shape[0], channel="H",
                                        pc=7, t_particle=t_particle))
        assert len(payload) <= spec.DATA_WORDS, (sec, len(payload))
        hk = [(header, _hk_words(FEATURE_DUPLICATE_TAS_MPS if n else tas_mps, tod))
              for n in range(spec_["hk"])]
        if spec_.get("last"):
            records.extend(hk)
            records.append((image_header, payload))
        else:
            records.append((image_header, payload))
            records.extend(hk)
        t_particle += FEATURE_GAP_LONG
    return raw_file(str(path), records)


# ---------------------------------------------------------------------------
# What the product will look like, said at the point of writing the flight
# ---------------------------------------------------------------------------
#
# Recorded 2026-09-16, measured 2026-09-17: a stranger runs the published quickstart,
# sees ``ALL DONE``, opens the 68 MB combined product it wrote and finds 99.72 % of its
# cells NaN, with nothing in either command's output having said so. The padding is
# faithful -- ``combine_sizedist.m`` pads every second between the flight date it reads
# out of the raw STEM and the first second the records actually carry -- but a user who
# has not read the user guide's Quickstart section has no way to know that, and a
# mostly-NaN file looks exactly like a broken one.
#
# This tool cannot fix the padding without changing what it writes, and its bytes are
# tracked (``tests/data/demo_flight_v35_*``, the pinned threshold counts in
# ``tests/test_demo_flight_thresholds.py``). What it CAN do is say, before the pipeline
# is ever started, exactly how long the time axis will be and how much of it can carry
# data -- all of which follows from the stem it was given and the clock it is about to
# stamp into the records, both of which are this function's own inputs.


def _stem_time_of_day(stem: str) -> int | None:
    """Seconds after midnight in a ``base<YYMMDDhhmmss>`` stem, or ``None``.

    The combine step reads the flight's date and time out of the raw stem
    (``combine_sizedist.m``, ``summaryfile(1).name``), never out of the record
    headers -- measured 2026-09-17 on the quickstart's own product, whose
    ``Time Vector`` starts at MATLAB datenum 736330.0 (2016-01-01 00:00:00) from
    the stem ``base160101000000`` while every record header in that same file
    carries 2016-09-06 (the header tuple is year, month, weekday, day, so its
    2 is the weekday). A stem this cannot parse returns ``None`` rather than a
    guess.
    """
    if not stem.startswith("base"):
        return None
    digits = stem[4:]
    if len(digits) != 12 or not digits.isdigit():
        return None
    hh, mm, ss = int(digits[6:8]), int(digits[8:10]), int(digits[10:12])
    if hh > 23 or mm > 59 or ss > 59:
        return None
    return hh * 3600 + mm * 60 + ss


def expected_product_shape(path, n_seconds: int, *, start_hour: int = 6,
                           start_minute: int = 6,
                           start_second: int = 40) -> dict | None:
    """How long the combined product's time axis will be, and how much of it can
    carry data, for a flight written to ``path`` with these arguments.

    Returns ``None`` when the stem does not carry a parseable ``base<YYMMDDhhmmss>``
    timestamp, or when that timestamp is at or after the records' own clock -- the
    padding direction this has not been measured in, and a number nobody measured
    does not get printed.

    **How each field was established.** ``data_seconds`` is ``n_seconds - 1``:
    measured 2026-09-17 on the quickstart's own five-second run, whose ``.tas.csv``
    carries four seconds (60640-60643) because the raw file's LAST record is the
    fifth second's housekeeping packet and ``read_binary_SPEC.m`` never decodes a
    file's last record -- the decode and ``proc`` do carry all five seconds of
    particles (60 particles across 60640-60644 on the dense flight), and it is
    stage 4, gridding on the TAS seconds, that drops the fifth. ``axis_seconds``
    is derived from the same run: 22,004 = (22,000 seconds from the stem's
    00:00:00 to the records' 06:06:40) + 4 data seconds.
    """
    stem_tod = _stem_time_of_day(Path(path).stem)
    if stem_tod is None:
        return None
    record_tod = start_hour * 3600 + start_minute * 60 + start_second
    pad = record_tod - stem_tod
    if pad < 0:
        return None
    data_seconds = max(n_seconds - 1, 0)
    axis = pad + data_seconds
    return {
        "stem_time_of_day": stem_tod,
        "record_time_of_day": record_tod,
        "pad_seconds": pad,
        "data_seconds": data_seconds,
        "axis_seconds": axis,
        "populated_fraction": (data_seconds / axis) if axis else 0.0,
    }


def _hhmmss(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


#: Measured 2026-09-17 on a five-second dense flight run through
#: ``--preset DEMO_2DS_H --stages 234c``: 60 particles decoded, 50 accepted by S3
#: (10 bars rejected ``'a'``, by design), 11 counted into used bins across the four
#: TAS seconds, ``Mean Area Ratio`` finite in 11 of 2,816,512 cells and touching
#: two of those seconds. Quoted in the tool's own summary so a reader knows what
#: "not empty" amounts to here.
DENSE_MEASURED_COUNTED: int = 11

#: The same five-second dense flight on engine 3.5 (``--profile stock-v3.5`` with the
#: builder's own aircraft file, ``--borrowed-combine``): ``count`` in ``sd`` sums to 48,
#: measured 2026-10-05 by ``tests/test_quickstart_runs.py`` once engine 3.5 sized the demo
#: 2D-S on the 2D-S 128-bin ladder by default (15 on the stock HVPS table, 2026-09-27).
#: The message used to quote only the 3.1.4 figure, with no engine named, while the v3.5
#: run a new user is steered to printed a different one.
DENSE_MEASURED_COUNTED_V35: int = 48

#: Measured 2026-09-17 the same way on the PLAIN flight: 5 particles, all 0.048 mm
#: (below the first used bin's lower edge, 0.055 mm), each the only particle of its
#: record so every ``inter_arrival`` reads 0 -- the production shattering
#: configuration rejects all five. ``count`` sums to 0, ``mean_area_ratio`` is finite
#: in 0 of 512 cells, ``Reject_ratio`` is 1.0 in every second.
PLAIN_MEASURED_COUNTED: int = 0


def summary_lines(path, n_seconds: int, *, dense: bool) -> list[str]:
    """The lines :func:`main` prints after writing a flight: what the combined
    product's time axis will look like, and whether its size distribution will
    have anything in it. Returned rather than printed so a test can read them.
    """
    lines: list[str] = []
    shape = expected_product_shape(path, n_seconds)
    if shape is not None:
        lines.append(
            f"combined product to expect: a {shape['axis_seconds']:,}-second time axis "
            f"of which {shape['data_seconds']} carry data "
            f"({100 * shape['populated_fraction']:.3g} %); the other "
            f"{shape['pad_seconds']:,} are NaN.")
        lines.append(
            f"  why: the combine step dates the flight from the file-name STEM "
            f"({_hhmmss(shape['stem_time_of_day'])}), while these records are stamped "
            f"{_hhmmss(shape['record_time_of_day'])}, and every second between is padded. "
            "A NaN there means the probe wrote nothing that second, not an error.")
        lines.append(
            f"  {shape['data_seconds']} data seconds and not {n_seconds}: the file's last "
            "record is the last second's housekeeping packet, and the 2D-S reader never "
            "decodes a file's last record, so the .tas.csv carries one second fewer than the "
            "decode does and stage 4 grids on the TAS seconds (measured 2026-09-17).")
        if shape["pad_seconds"]:
            clock = _hhmmss(shape["record_time_of_day"]).replace(":", "")
            aligned = f"base{Path(path).stem[4:10]}{clock}"
            lines.append(
                f"  to get a product with no padding at all, name the file {aligned}"
                f"{Path(path).suffix} -- the stem then matches the records' own clock.")
    if dense:
        lines.append(
            f"the DENSE flight's size distribution is small, not empty: at --seconds 5, "
            f"60 particles decode and {DENSE_MEASURED_COUNTED_V35} are counted into size bins "
            "on engine 3.5.")
    else:
        lines.append(
            "WARNING: this PLAIN flight's size distribution will be EMPTY. Measured "
            "2026-09-17 under --preset DEMO_2DS_H: its particles are all 0.048 mm, below "
            "the first used bin's lower edge (0.055 mm), and each is the only particle of "
            "its record, so every inter-arrival reads 0 and the production shattering "
            f"configuration rejects all of them -- Counts sum to {PLAIN_MEASURED_COUNTED}, "
            "Mean Area Ratio is NaN in every cell and Reject Ratio is 1.0 in every second.")
        lines.append(
            "  pass --dense for a flight whose distribution has particles in it.")
    return lines


def next_lines(written, aircraft, py):
    """The "next" commands printed after a demo flight is written.

    The engine 3.1.4 line is printed only when that engine is installed (it is not
    part of this package).
    """
    name = str(written)
    folder = name.rsplit("/", 1)[0].rsplit("\\", 1)[0] if ("/" in name or "\\" in name) else "."
    out = ["next -- engine 3.5, the default (re-run with --with-config to write run.toml "
           "beside the flight; a repository checkout can use examples/start_here/run.toml, "
           f"the same settings):\n  arrayprobe run {folder}/run.toml {written} --yes"]
    if importlib.util.find_spec("arrayprobe.reject") is not None:
        out.append(f"or engine 3.1.4, the ORACLES-validation anchor:\n  {py} "
                   f"scripts/run_flight.py --preset DEMO_2DS_H --engine 3.1.4 --port-validation "
                   f"--stages 234c --yes {written}")
    return out


#: The ready-to-run settings ``--with-config`` writes beside the demo flight: the same
#: choices as the repository's ``examples/start_here/run.toml``, with every path relative
#: to the folder the flight is written in, so ``arrayprobe run <folder>/run.toml`` works
#: from a bare ``pip install`` with no ``examples/`` folder.
DEMO_RUN_TOML = """# The settings for the demo run, written by
# `arrayprobe make-demo-flight --with-config`.
# The same choices as the repository's examples/start_here/run.toml. Paths in it are
# relative to this folder.

[fidelity]
# The processing rules: the UIOPS v3.5 rules as the UIOPS developers released them.
profile = "stock-v3.5"

[run]
# Which processing program. "3.5" is the default for new data.
engine = "3.5"
# Which probe and aircraft settings. DEMO_2DS_H is the synthetic demo file's own settings.
preset = "DEMO_2DS_H"
# Where the results go: this folder.
out = "."
# Which steps to run: 2 = read the raw file, 3 = measure each particle,
# 4 = count particles by size each second, c = write one combined file.
stages = "234c"
# The aircraft's speed through the air, second by second, written beside the raw file.
tas_file = "{aircraft}"

[combine]
# Write the combined file (step "c"). Stock v3.5 has no combine step, so this
# borrows one and labels the output as borrowed.
borrowed = true

[enhancements]
# Empty on purpose: no optional corrections. The run is the plain UIOPS v3.5 processing.
"""


def write_demo_run_toml(raw_path, aircraft) -> Path:
    """Write ``run.toml`` beside a demo flight; returns its path."""
    raw_path = Path(raw_path)
    target = raw_path.with_name("run.toml")
    target.write_text(DEMO_RUN_TOML.format(aircraft=Path(aircraft).name), encoding="utf-8")
    return target


def main(argv=None) -> int:
    """CLI entry point, shared by ``arrayprobe make-demo-flight`` and the
    ``scripts/make_demo_flight.py`` shim, so both surfaces parse identically."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", help="output path, e.g. demo.2DS")
    parser.add_argument("--seconds", type=int, default=5,
                        help="number of one-second records to write (default: 5)")
    parser.add_argument("--tas-mps", type=float, default=130.0,
                        help="synthetic true airspeed in m/s (default: 130.0)")
    parser.add_argument("--dense", action="store_true",
                        help="write the DENSE flight instead: "
                             "disks/rings/bars sized to move a reject or "
                             "shattering threshold's used-bin count, not the "
                             "plain one-particle-per-second flight above")
    parser.add_argument("--distinct-counters", action="store_true",
                        help="give each image packet its own particle counter "
                             "(default: the constant 7), so SODA-2's spec_index "
                             "keeps every particle; changes the written bytes")
    parser.add_argument("--with-config", action="store_true",
                        help="also create the output folder if needed and write a "
                             "ready-to-run run.toml beside the flight, so "
                             "`arrayprobe run <folder>/run.toml <flight> --yes` works "
                             "without the repository's examples/ folder")
    args = parser.parse_args(argv)
    if args.seconds < 2:
        # Measured 2026-09-26: a 1-second flight (plain or --dense) decodes one image record but
        # writes no <stem>.tas.csv, so S4 skips and the run fails; a 0-second one is empty.
        # Both were written, exit 0, with the next command printed as if they would run.
        parser.error(f"--seconds must be at least 2, got {args.seconds}: a shorter flight "
                     f"decodes to no airspeed record (<stem>.tas.csv), and the run then fails "
                     f"at the size-distribution stage")
    if not args.tas_mps > 0:
        parser.error(f"--tas-mps must be a positive speed in m/s, got {args.tas_mps}")

    if args.with_config:
        Path(args.path).parent.mkdir(parents=True, exist_ok=True)
    if args.dense:
        written = build_dense_demo_flight(args.path, n_seconds=args.seconds,
                                          tas_mps=args.tas_mps,
                                          distinct_counters=args.distinct_counters)
        print(f"wrote {written} (DENSE: {args.seconds} synthetic seconds, "
              f"TAS={args.tas_mps} m/s) -- see help(arrayprobe.tools.make_demo_flight."
              "build_dense_demo_flight) for what moves which threshold")
    else:
        written = build_demo_flight(args.path, n_seconds=args.seconds,
                                    tas_mps=args.tas_mps,
                                    distinct_counters=args.distinct_counters)
        print(f"wrote {written} ({args.seconds} synthetic seconds, "
              f"TAS={args.tas_mps} m/s)")

    # Both flights, not just the plain one: the 99.72 %-NaN product a stranger opens
    # after the published quickstart is the DENSE one, and until 2026-09-17 the dense
    # branch returned here -- printing neither this summary, nor the base-name note,
    # nor the next command. See summary_lines.
    for line in summary_lines(written, args.seconds, dense=args.dense):
        print(line)
    if not written.stem.startswith("base"):
        print(f"note: {written.name!r} does not start with 'base' -- the combine "
              "step (--stages 234c) needs a base<YYMMDDhhmmss> name to read the "
              "flight date; stages 2-4 alone work with any name.")
    # The batch driver is still `scripts/run_flight.py`, which `pip install` does
    # not ship (see arrayprobe.tools.__init__ for why it has not moved yet), so
    # this hint names the repository path and says so rather than printing a
    # command an installed-package user cannot run.
    # --yes: this demo names no threshold policy, so the run would otherwise stop and
    # ask. The command printed here must be one somebody can paste and have work.
    aircraft = write_demo_aircraft(written, n_seconds=args.seconds)
    print(f"wrote {aircraft} (aircraft TAS for engine 3.5: a scaled excerpt of public ARM "
          "AAF data, see DEMO_AIRCRAFT_TAS_MPS)")
    # --engine is required on every preset (2026-09-23), so both commands name it.
    # The interpreter as this platform spells it: a Windows path printed on Linux could not be
    # pasted (cloud pass 8 cold-user run).
    py = ".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python"
    if args.with_config:
        config = write_demo_run_toml(written, aircraft)
        print(f"wrote {config} (the run settings, paths relative to its folder)")
        print("next -- engine 3.5, the default:")
        print(f"  arrayprobe run {config} {written} --yes")
        return 0
    for line in next_lines(written, aircraft, py):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
