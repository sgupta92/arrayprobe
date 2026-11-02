# SPDX-License-Identifier: BSD-3-Clause
"""The fidelity-profile type and the one shared profile registry.

Moved here from :mod:`arrayprobe.profiles`. The
v3.1.4 variants, the v3.5 builders and the ``register_*_v35`` functions still
live there and register into the registry defined here, so
``arrayprobe.profiles.PROFILES is arrayprobe_uiops.profiles.PROFILES``. This
module never imports ``arrayprobe``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from arrayprobe_uiops.reject_core import ORACLES_PRODUCTION_REJECT_CONFIG, RejectConfig

__all__ = [
    "FidelityProfile",
    "PROFILES",
    "profile",
    "register_profile",
    "is_v35_flavoured",
    "register_stock_v35_image_assisted",
]


@dataclass(frozen=True)
class FidelityProfile:
    """A named MATLAB variant, plus the switches that distinguish it."""

    name: str
    description: str

    spec_buffer_guard: bool
    """Whether ``read_binary_SPEC``'s image decoder carries the 2017 bounds guards.

    Stock v3.1.4 ``read_binary_SPEC.m:222,226,233,256,260,267`` tests
    ``iii+nH-1<=length(buf)`` and ``iii+kkk<=length(buf)`` before decoding, so a
    packet whose declared word count runs past the two-record window is skipped
    and the file keeps processing.  The ORACLES variant
    (``OptArrProbDataProcessing/read_binary_SPEC.m:215,218,224``) has none of
    them -- those exact lines are the whole diff between the two files, aside
    from four commented-out debug prints -- so MATLAB raises
    ``Index exceeds matrix dimensions`` and the run dies there.

    ``False`` therefore means "let it raise", which is the honest reproduction of
    what produced the reference data.  It is not a bug we are free to fix: a run
    that would have died in MATLAB must not quietly return a shorter file here.
    """

    hvps_reader: str
    """Which decoder handles a raw ``.HVPS`` file: ``'spec'`` or ``'hvps'``.

    Stock v3.1.4 has only ``read_binary_SPEC``.  The ORACLES variant also ships
    ``read_binary_hvps.m``, a single-block decoder with a different packet walk,
    and the surviving one-line run scripts show *both* were pointed at the same
    file: ``read_binary_SPEC_oracles.m`` calls ``read_binary_SPEC`` on
    ``base160906064343.HVPS`` and ``read_binary_hvps_20160906_1.m`` calls
    ``read_binary_hvps`` on it.

    **The steps script resolves this, and it points at ``'spec'``**
    (``archive/staging_variant_raw/steps_scr_1.m.raw.txt``, a ``switch probe``
    naming every step's input and output filename per probe; author-identified
    2026-09-03 as the script actually used).  Its HVPS branch is internally
    inconsistent, and the inconsistency is the evidence:

    * **Step 1** names ``read_binary_hvps([filename '.HVPS'], filename)``.  That
      function writes a netCDF at the literal ``outfilename`` holding one
      ``data`` variable -- **no channel split and no sidecars** (one ``fopen``,
      the input).
    * **Step 2** then reads ``[filename '.V.cdf']``.
    * **Step 3** reads TAS from ``[filename '.tas.csv']`` -- the **HVPS file's
      own basename** -- and feeds ``[filename '.V_1.cdf']`` to ``sizeDist``.

    Step 1 as written cannot produce what steps 2 and 3 consume.
    ``read_binary_SPEC`` produces exactly both: ``.H.cdf``/``.V.cdf`` at
    ``:30-31`` and ``.tas.csv`` at ``:289``.  So the inputs the HVPS
    ``sizeDist`` actually consumed came from ``read_binary_SPEC`` run on the
    **HVPS raw file**, and the ``read_binary_hvps`` line is a stale branch.

    **What this does and does not overturn** -- one of each, and the boundary
    was drawn wrongly here once before it was corrected.

    *Overturned:* the claim that the HVPS decode writes no ``.tas.csv`` so the
    archived product's airspeed must have come from the 2D-S sidecar.  It has
    its own.  Measured on two flights, the HVPS's own sidecar ends at exactly
    the archived product's last second (170813: 16:55:21; 160906: 14:40:13),
    and it explains the 18-second overrun the 2D-S-sidecar run carried.

    *NOT overturned:* the ``.V.`` in the product name.  **The HVPS is a
    single-channel instrument** -- unlike the 2D-S, it has no second optical
    channel -- and it was **mounted in a vertical orientation**, which is what
    the ``V`` records.  So ``.V.`` is a label for the
    probe's mounting, exactly as this project originally had it, and a claim
    made here that it was "a real channel" was wrong.  Running
    ``read_binary_SPEC`` over an HVPS file does emit an ``.H.cdf``, but that
    output is an artefact of a two-channel reader meeting a one-channel
    instrument, not a second channel: on 170813 it holds 15,947 records against
    the V side's 19,700, and nothing downstream should read it.

    **The measurement is in, and it is a clean negative** (flight 170813,
    2026-09-03, both arms run end to end and compared against the archived
    product):

    ==========================  ==========  ==========
    ..                          ``'hvps'``  ``'spec'``
    ==========================  ==========  ==========
    particles out of S3             39,241      49,964
    ``DMT_DOF_SPEC_OVERLOAD`` set        0      10,722
    accepted particles              22,497      22,497
    ``Counts`` total                17,470      17,470
    ==========================  ==========  ==========

    ``Counts`` is **element-wise identical** between the two arms -- not merely
    equal in total -- and so is the accepted-particle count.  The archive holds
    16,094, so **both arms miss it by the same 1.0855**.  Switching decoder
    changes only ``Size Distribution`` (2 cells, 5.9e-6), ``Number
    Concentration`` (1 cell) and ``Reject Ratio`` (2 cells), via the DOF
    dead time that the overload vector now drives.

    So the decoder was genuinely misidentified, and correcting it does **not**
    explain the HVPS count excess.  Both readers reach the same single physical
    channel, which is why they agree; ``'spec'`` additionally populates
    ``SliceCount``, ``DMT_DOF_SPEC_OVERLOAD`` and ``Particle_number_all``, which
    ``'hvps'`` leaves identically zero for every particle -- the "a variable
    uniform across every particle" signature, here with a definite cause.

    **The default stays ``'hvps'`` for now**, because nothing output-pinned
    argues for moving it: the counts are identical either way, and the archived
    products cannot adjudicate between them.  ``'spec'`` is nonetheless the more
    faithful reproduction of the chain the steps script describes, and is what a
    future flip should adopt once something depends on those three variables.
    Build the test profile with
    ``dataclasses.replace(ORACLES_PRODUCTION, hvps_reader='spec')``.
    """

    # ------------------------------------------------------------------
    # S3 axes.  ``imgProc_sm.m`` is where the two trees part company hardest:
    # 949 lines in stock against 521 in the variant, and unlike the reject/sizing files -- where
    # every shared file turned out byte-identical -- five of those differences
    # change written output for probetype 2.
    # ------------------------------------------------------------------

    diode_stats_counts_shadowed: bool
    """Whether ``bin_stats`` counts shadowed diodes or lit ones.

    Stock ``imgProc_sm.m:804-805`` accumulates ``sum(c=='0',1)``; the variant at
    ``:387-388`` accumulates ``sum(c=='1',1)``.  In UIOOPS's char image ``'0'`` is
    a **shadowed** diode (``CGAL_minR.cpp:63`` selects on 48, ``holroyd.m:139``,
    ``calculate_reject_unified.m:386``), so the two are exact complements and the
    variant counts *illuminated* diodes.

    This is not an ambiguity -- stock's own changelog names it as a repair:
    "Updated by Dan Stechman, 11/28/2016 -- Changed definition of diode_stats
    variable to sum instances of *shadowed* particles (old version summed
    illuminated particles)" (``imgProc_sm.m:48-50``).  The ORACLES variant is
    dated November 2016 and sits on the near side of that fix, so ``bin_stats``
    in the reference product is a lit-diode count.  ``False`` reproduces it.

    Consequence is bounded but real: ``bin_stats`` is a per-flight diagnostic of
    which photodiodes are working, and read as a shadow count it inverts --
    a dead (never-shadowed) diode reads as the *most* active one.
    """

    zero_image_particle_recovery: bool
    """What happens when a particle frames to zero slices.

    Both trees detect the condition the same way (``start > (j-1)`` for
    probetype 2), and then diverge completely:

    * stock ``imgProc_sm.m:541-546`` sets ``start = j + 2``, advances ``j`` and
      ``continue``\\ s -- the empty particle is skipped and the record keeps
      being scanned;
    * the variant at ``:249-251`` executes ``break``, abandoning **the entire
      rest of the image record**.

    Stock's changelog dates the change: "Updated by Joe Finlon (w/ contribution
    from Adam Majewski), 11/06/17 -- Improved handling of image buffers when
    zero-image particles are detected" (``:66-68``), and the old ``break`` is
    left in place commented out at ``:538``/``:545`` beside its replacement.

    This is the highest-consequence S3 divergence, because it is silent and
    unbounded: every particle after the first zero-image particle in a record is
    simply absent from the reference product, with nothing recorded to say so.
    ``False`` reproduces that loss, which is required -- a port that recovered
    here would emit particles that are not in the file it is validated against.
    """

    time_in_seconds_from_tas: bool
    """How ``Time_in_seconds`` is built for probetype 2 (2D-S / HVPS).

    The variant, ``imgProc_sm.m:365``, is one line that scales the particle's own
    clock count by the diode size: an absolute value, with true air speed
    hard-wired to 170 m/s.

    Stock ``:724-778`` is Joe Finlon's 2017-03-03 replacement: it reads TAS from
    an aircraft data file passed as ``varargin{1}``, converts each *inter-particle*
    clock difference at the TAS for that image record's time, and accumulates --
    falling back to the same ``/170`` only when the lookup is empty or NaN
    (``:730``, Finlon 2018-02-09).  It also carries the rollback correction at
    ``:737``/``:752``: a negative difference below ``-250`` s is treated as the
    32-bit clock wrapping, and ``2^32-1`` is added back.

    The two therefore differ in kind, not degree: an absolute clock reading
    against an accumulated sum of TAS-corrected differences.  ``False`` also
    means no aircraft file is required, which is why the variant's signature has
    no ``varargin``.
    """

    inter_arrival_in_seconds: bool
    """The units of the written ``inter_arrival`` variable, for probetype 2.

    Stock ``imgProc_sm.m:769-773`` differences ``time_in_seconds``, so the
    variable is in **seconds** as its own attribute claims.  The variant at
    ``:366-370`` computes ``part_time - part_micro(kk-1)`` -- a difference of raw
    clock counts, never scaled -- so the reference product's ``inter_arrival`` is
    in **clock cycles**.  Measured on the fixture: the variant writes 3129, 11,
    19, 71 where the seconds reading would be of order 1e-5.

    Two further consequences of the variant's form, both reproduced:

    * ``part_micro`` is reset to a fresh array at every image record
      (``:513`` ``clear ... part_micro ...``) and ``kk`` returns to 1, so the
      ``if(kk>1)`` test at ``:366`` fails for the first particle of *every*
      record and writes 0 -- not just for the first particle of the file.
    * because it differences the clock rather than the time, it is unaffected by
      the ``/170`` TAS assumption above -- which makes it the more transferable
      of the two quantities, not the less.
    """

    shadow_diode_reillumination: bool
    """Whether ``imgProc_sm`` re-illuminates stuck photodiodes before measuring.

    A third source variant, and the one that actually produced the ORACLES
    products.  Both trees on disk take six arguments (variant) or eight-plus
    (stock); the production file takes **nine** -- ``(..., projectname, path,
    flight, file)`` -- and uses the three extras for one guarded block, at
    extraction ``:286-292``::

        if exist([path '/' 'diode.' flight file '.' infile(end-4) '.mat'],'file')==2;
            load([... ],'shadow_diode');
            c(:,shadow_diode)='1';
        end

    It sits between the ``c`` construction (``:266-268``) and the image-width
    guard (``:272``), so it precedes habit, rejection, sizing and the enclosing
    circle: it reaches all 41 written variables.  ``find_shadow_diodes.m``
    supplies the list, calling a diode stuck when ``bin_stats`` shows it lit for
    under 80% of the array mean.

    Established by normalized diff of the Appendix-B extraction against the real
    variant tree file: the *entire* delta is this block, the ``mod(i,100)``
    progress ``disp`` that reports it, the three-argument signature, and two
    spelling repairs in comments (``Variabels``, ``doide``).  Nothing else
    differs, so the production file is the variant file plus this axis.

    ``True`` only enables the branch.  Whether it does anything depends on the
    mask, which is passed separately (:mod:`arrayprobe.masks`) rather than
    discovered by filename, so a run states what it applied instead of
    depending on the working directory.  ``False`` makes passing a mask an
    error, because neither tree file can consume one.

    Note what this does *not* settle: the mask files recovered for 09/06/2016
    2D-S are empty, so for that product the branch is inert whether or not it
    was compiled in.  The 09/06 HVPS mask is not empty (diodes 2 and 128).
    """

    imgproc_output_typing: str
    """The proc-file variable contract: ``'typed'`` or ``'all-double'``.

    Stock ``imgProc_sm.m:218-448`` declares each variable at its natural width
    -- ``'int'`` for ``Date``/``Time``/``parent_rec_num``, ``'short'`` for
    ``msec``/``position``/``image_length``/``holroyd_habit``, ``'byte'`` for the
    three flags -- casts on write (``int16(images.auto_reject)`` at ``:898``,
    ``int16(images.holroyd_habit)`` at ``:923``), and attaches ``Units`` and
    ``Description`` to every one, plus eight global attributes.

    The variant ``:135-186`` declares **every** variable ``'double'``, writes
    ``double(...)`` where stock writes ``int16(...)``, and calls ``endDef`` at
    ``:187`` having issued **no ``putAtt`` at all** -- no variable attributes and
    no global attributes.  Confirmed by executing it: the proc file it writes has
    41 variables, all ``float64``, and ``ncattrs()`` empty on every one, against
    the same 41 variables carrying eight global and two per-variable attributes
    from stock on the identical input.

    So the reference product is self-describing to a much smaller degree than
    stock's, and nothing in it records the probe, the project, or the source
    file.  It also means the variant cannot round-trip a value through a narrower
    type -- worth knowing, because it makes ``holroyd_habit`` and
    ``image_auto_reject`` exact ASCII codes in the reference where stock's
    ``int16`` cast is a genuine (if here harmless) narrowing.
    """

    nan_tas_substitution: bool
    """Whether ``sizeDist`` replaces a NaN TAS before the sample volume.

    Stock ``UIOPS-v3.1.4/joefinlon-UIOPS-ba5e67c/sizeDist.m:1729-1741``
    ("Correct NaN TAS values where appropriate (rare issue) ~ Joe Finlon
    02/26/18") walks ``tas`` in order and sets each NaN ``tas(i)`` to the last
    valid value in ``tas(1:i-1)`` -- already substituted, so earlier NaNs count
    as valid once replaced -- or to 100 m/s when there is none; ``svol2`` at
    ``:1748`` then uses the repaired vector.  The ORACLES-variant ``sizeDist.m``, the
    ORACLES production tree, has no such block: its ``svol2`` line (``:1605``)
    follows the probetype-1 block (``:1596``) directly, so a NaN TAS writes a NaN
    sample volume and every concentration derived from it.  The v3.5 tree keeps
    the block (``UIOPS-v3.5/joefinlon-UIOPS-039be82/sizeDist.m:1959-1971``).
    ``True`` reproduces stock; ``False`` the ORACLES products.  Implemented by
    :func:`arrayprobe.sizedist.substitute_nan_tas`, selected in
    :func:`arrayprobe.sizedist.run` by ``nan_tas_substitution=`` (which follows
    ``tree`` when not given); pinned against Octave in
    ``tests/test_sizedist_nan_tas.py``.
    """

    reject_thresholds: RejectConfig
    """The ``calculate_reject_unified.m:71-77`` thresholds this tree runs with.

    Stock and the named ORACLES variant tree share a byte-identical
    ``calculate_reject_unified.m`` and take :data:`~arrayprobe.reject.DEFAULT_REJECT_CONFIG`.
    The ORACLES variant -- the file that made the archived products -- carries
    three dated edits (``rej_hollow 1->0``, ``max_edge_img_ar 6->4``,
    ``max_comp_img_ar 5->4``) and takes
    :data:`~arrayprobe.reject.ORACLES_PRODUCTION_REJECT_CONFIG`.

    Carried on the profile because the alternative -- the call site reaching for
    a module default -- is exactly what happened until 2026-08-28: every ORACLES
    file was rejected on the stock thresholds, which drops ~40% of large
    particles on a dense file, and the proc files looked plausible throughout.
    The measurement that settled which thresholds made the product is in
    ``reject.py``.
    """


#: Fields that describe which MATLAB tree's *behaviour* a run reproduces, as
#: opposed to ``reject_thresholds``, which is configuration the v3.5 engine
#: reads. :func:`is_v35_flavoured` compares exactly these.
_BEHAVIOUR_FIELDS: tuple[str, ...] = (
    "spec_buffer_guard", "hvps_reader", "diode_stats_counts_shadowed",
    "zero_image_particle_recovery", "time_in_seconds_from_tas",
    "inter_arrival_in_seconds", "shadow_diode_reillumination",
    "imgproc_output_typing", "nan_tas_substitution",
)


#: Names whose *citations* point at the v3.5 tree. Populated by the two v3.5
#: builders below and by ``register_profile(..., cites_tree="v3.5")``.
#:
#: **Why a declaration and not only a field comparison.**  The first version of
#: :func:`is_v35_flavoured` compared the behaviour fields alone and returned
#: **True for ``stock-v3.1.4``** -- correctly, and uselessly. ``STOCK_V35`` was
#: built precisely by measuring that *every* field holds the same value as
#: ``stock-v3.1.4`` (see its description), so the two are field-identical and no
#: comparison of fields can ever separate them. What separates them is which tree
#: their citations name, and that is not derivable from the values. Running the
#: v3.5 engine under ``stock-v3.1.4`` would compute the right numbers and write a
#: ``.call`` claiming a tree that was not consulted -- a provenance error, which
#: in this project is the expensive kind.
_V35_TREE_PROFILES: set[str] = set()


def is_v35_flavoured(candidate: FidelityProfile) -> bool:
    """True when ``candidate`` may be used under ``--engine 3.5``.

    Two conditions, both required, and the first is the one that carries the
    weight:

    1. The profile **declares** that its citations are to the v3.5 tree -- it is
       one of the shipped v3.5 profiles, or a fork registered it with
       ``register_profile(p, cites_tree="v3.5")``. Not inferable from the field
       values; see :data:`_V35_TREE_PROFILES`.
    2. Every field in :data:`_BEHAVIOUR_FIELDS` equals :data:`STOCK_V35`'s.
       ``reject_thresholds`` is deliberately excluded -- it is the one thing the
       v3.5 engine reads from a profile and the one axis a caller is entitled to
       vary. This second check catches a fork that declares ``v3.5`` while
       describing v3.1.4 behaviour.

    **Fails closed in both directions.** An undeclared profile is refused however
    its fields read, and a declared one is still refused if its behaviour
    contradicts the declaration. A new field added to :class:`FidelityProfile` and
    not listed in :data:`_BEHAVIOUR_FIELDS` makes this *stricter*, never laxer.
    """
    if candidate.name not in _V35_TREE_PROFILES:
        return False
    stock35 = _LAZY["stock-v3.5"]()
    return all(
        getattr(candidate, f) == getattr(stock35, f) for f in _BEHAVIOUR_FIELDS
    )


#: The shipped variants, plus whatever a caller has registered. Mutable only
#: through :func:`register_profile`; :data:`PROFILES` is a live read-only view of
#: it, so a registration is visible to everything that reads the registry.
#: ``stock-v3.5`` is deliberately absent here until :func:`_build_stock_v35`
#: runs -- see :data:`SHIPPED` and :class:`_ProfileRegistry` for how lookups,
#: membership and iteration all stay correct in the meantime.
_REGISTRY: dict[str, FidelityProfile] = {}

#: The names the shipping package declares as its own, fixed once at its import
#: (:data:`arrayprobe.profiles.SHIPPED` is the frozen public copy). Filled by
#: the v3.1.4 package when it seeds its variants; read by :func:`register_profile`
#: so a shipped name can never be reused.
_SHIPPED: set[str] = set()

#: Lazily built shipped profiles, name -> zero-argument builder. The builders
#: live with the v3.1.4 variants and are injected at
#: their import, so this module never imports ``arrayprobe``.
_LAZY: dict[str, Callable[[], FidelityProfile]] = {}


class _ProfileRegistry(Mapping[str, FidelityProfile]):
    """Live view of :data:`_REGISTRY`, materialising ``stock-v3.5`` on demand.

    The other three shipped profiles, and anything a fork has registered, are
    already in :data:`_REGISTRY` and served directly. ``stock-v3.5`` is the
    one entry whose construction needs ``arrayprobe_uiops``, so asking
    this mapping for it -- by key, by ``in``, or by iterating down to values
    -- builds it once, via :func:`_build_stock_v35`, and never merely by
    importing this module or this class.
    """

    def __getitem__(self, name: str) -> FidelityProfile:
        if name in _LAZY:
            return _LAZY[name]()
        return _REGISTRY[name]

    def __iter__(self):
        return iter(_SHIPPED | set(_REGISTRY))

    def __len__(self) -> int:
        return len(_SHIPPED | set(_REGISTRY))


PROFILES: Mapping[str, FidelityProfile] = _ProfileRegistry()


def register_profile(new: FidelityProfile, *, cites_tree: str = "3.1.4") -> FidelityProfile:
    """Add a fork's own variant to the registry, under its own ``name``.

    ``cites_tree`` says **which MATLAB tree the variant's file:line citations name**
    -- ``"3.1.4"`` (the default) or ``"3.5"``. It is not inferable from the field
    values, because ``stock-v3.5`` was built by measuring that every field holds
    the same value as ``stock-v3.1.4``: the two are field-identical and only their
    citations differ. A variant registered ``cites_tree="3.5"`` becomes usable
    under ``--engine 3.5`` (see :func:`is_v35_flavoured`, which also re-checks the
    behaviour fields, so declaring ``"3.5"`` over v3.1.4 behaviour is still
    refused). **Defaulting to ``"3.1.4"`` fails closed**: a fork that says nothing
    is refused by the v3.5 gate rather than admitted to it.

    **Why this exists.**  UIOOPS is forked, edited and
    re-forked -- that is how the field-campaign variant behind the archived products came
    to exist -- so a group running their own tree needs to be able to say *my
    fork differs here* without editing this package. Every field of a
    :class:`FidelityProfile` is required by the dataclass, so a registration
    states each divergence explicitly; there is no path here that fills one in.

    **What this deliberately does not open.**  A profile can be registered from
    Python, where the caller constructs the object and names every field, and
    **never from a configuration file**: a ``FidelityProfile`` field *is* a
    threshold, and the configuration rule is that a config file selects
    between documented behaviours and never sets one. ``arrayprobe.config``
    will happily select a registered profile by name once it exists; it still
    refuses to describe one.

    A registration may not take a name already in use, shipped or registered:
    ``.call`` sidecars, logs and error messages record the *name*, so a name has
    to keep meaning one variant. Raises :class:`ValueError` if it does.
    """
    if not isinstance(new, FidelityProfile):
        raise TypeError(f"register_profile takes a FidelityProfile, got {type(new).__name__}")
    if not new.name or not new.name.strip():
        raise ValueError("a registered profile needs a name; it is what a .call stamp records")
    if not new.description or not new.description.strip():
        raise ValueError(
            f"profile {new.name!r} has no description. Every shipped profile's says which "
            "MATLAB tree it is and where that tree lives, because a variant nobody can "
            "locate cannot be checked against anything")
    # Checked against SHIPPED as well as _REGISTRY: "stock-v3.5" is a shipped
    # name from the moment this module loads (SHIPPED is eager), even before
    # _build_stock_v35 has ever run and actually put it in _REGISTRY -- a
    # registration attempt must not slip through in that window.
    if new.name in _REGISTRY or new.name in _SHIPPED:
        kind = "shipped with this package" if new.name in _SHIPPED else "already registered"
        raise ValueError(
            f"fidelity profile {new.name!r} is {kind}; a name records which MATLAB variant "
            f"produced a file, in .call sidecars and in every error message, so it cannot be "
            f"reused. Known: {sorted(_SHIPPED | set(_REGISTRY))}")
    if cites_tree not in ("3.1.4", "3.5"):
        raise ValueError(
            f"cites_tree must be '3.1.4' or '3.5', got {cites_tree!r}; it names which MATLAB "
            "tree this variant's file:line citations point at, and only those two are vendored")
    _REGISTRY[new.name] = new
    if cites_tree == "3.5":
        _V35_TREE_PROFILES.add(new.name)
    return new


def profile(name: str) -> FidelityProfile:
    """Look a profile up by name, listing the alternatives on a miss."""
    try:
        return PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(PROFILES))
        raise KeyError(f"unknown fidelity profile {name!r}; known profiles: {known}") from None


# The v3.5 builders and register functions, moved from
# arrayprobe.profiles; arrayprobe.profiles re-exports them.
_STOCK_V35_NAME = "stock-v3.5"

#: Cache for :func:`_build_stock_v35`; ``None`` until the profile is first
#: actually needed. Deliberately not a plain ``FidelityProfile`` constant --
#: see the import-time note above.
_stock_v35_cache: FidelityProfile | None = None


def _build_stock_v35() -> FidelityProfile:
    """Construct :data:`STOCK_V35`, importing ``arrayprobe_uiops`` only here.

    Called from every access path below (the ``STOCK_V35`` module attribute,
    ``PROFILES["stock-v3.5"]``, ``profile("stock-v3.5")``, iterating
    ``PROFILES`` down to values) so the deferral is invisible to a caller:
    the profile is always complete once returned, just not necessarily built
    yet the first time anything asks. Cached, so the import and the
    construction each happen at most once per process -- the same "once" the
    former eager version paid at ``import arrayprobe`` time, just moved to
    first use.
    """
    global _stock_v35_cache
    if _stock_v35_cache is None:
        from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG

        _stock_v35_cache = FidelityProfile(
            name=_STOCK_V35_NAME,
            description=(
                "joefinlon/UIOPS v3.5 as shipped (UIOPS-v3.5/joefinlon-UIOPS-039be82/). "
                "Every field holds the same value as UIOOPS v3.1.4 as released -- measured field "
                "by field "
                "against the v3.5 sources, not assumed -- and cites v3.5 lines instead: "
                "buffer guards read_binary_SPEC.m:322-367, shadowed-diode stats "
                "imgProc_sm.m:1208-1211, zero-image recovery :773/:1311, TAS-based "
                "Time_in_seconds :1133-1172, seconds-valued inter_arrival :1176, no "
                "shadow_diode block anywhere, typed output (:1352, :1380), NaN-TAS "
                "substitution sizeDist.m:1959-1971, reject thresholds "
                "calculate_reject_unified.m:60-66. Provenance table and test: "
                "arrayprobe_uiops.profile, tests/test_stock_v35_profile.py. The v3.5 engine "
                "consumes only reject_thresholds (its readers and driver take no profile, "
                "because v3.5 has one source tree); the rest records which source tree a run "
                "translates. v3.5 also writes NETCDF4 with deflate (read_binary_SPEC.m:81, "
                "imgProc_sm.m:289) where v3.1.4 writes classic; that is the engine's own "
                "contract, not a profile axis."
            ),
            spec_buffer_guard=True,
            hvps_reader="spec",
            diode_stats_counts_shadowed=True,
            zero_image_particle_recovery=True,
            time_in_seconds_from_tas=True,
            inter_arrival_in_seconds=True,
            shadow_diode_reillumination=False,
            imgproc_output_typing="typed",
            nan_tas_substitution=True,
            reject_thresholds=STOCK_V35_REJECT_CONFIG,
        )
        _REGISTRY[_STOCK_V35_NAME] = _stock_v35_cache
        _V35_TREE_PROFILES.add(_STOCK_V35_NAME)
    return _stock_v35_cache


_ORACLES_PROD_V35_NAME = "oracles-production-v3.5"

#: Cache for :func:`_build_oracles_production_v35`, deferred for the same
#: reason as :data:`_stock_v35_cache`: it is built from ``STOCK_V35``.
_oracles_prod_v35_cache: FidelityProfile | None = None


def _build_oracles_production_v35() -> FidelityProfile:
    """Construct :data:`ORACLES_PRODUCTION_V35` -- v3.5 behaviour, ORACLES thresholds.

    **Why this exists.**  CIP results are wanted
    under stock *and* ORACLES-production thresholds "side by side", and the
    batch driver refused: ``--engine 3.5`` accepted only ``stock-v3.5``, whose
    own message said a v3.5-flavoured variant "is not supported here yet". The
    same refusal had already parked CMP-2 on 2026-09-16, where scoring the v3.5
    engine against the author's triage labels would have confounded *engine*
    with *profile* -- on exactly the thresholds worth 38.15 % of used-bin
    particles. Two blockers, one missing object.

    **Why ``ORACLES_PRODUCTION`` itself could not be passed instead, and why the
    refusal was right.**  Measured 2026-09-17: it differs from :data:`STOCK_V35`
    in **all eight** non-threshold fields -- ``spec_buffer_guard``,
    ``hvps_reader``, ``diode_stats_counts_shadowed``,
    ``zero_image_particle_recovery``, ``time_in_seconds_from_tas``,
    ``inter_arrival_in_seconds``, ``shadow_diode_reillumination``,
    ``imgproc_output_typing``. Every one of those describes **v3.1.4 source
    behaviour**, so handing it to the v3.5 engine would assert things about a
    tree that is not running. The gate was not over-strict; the registry was
    short one profile.

    **What this profile is, stated plainly: a synthetic configuration.**  No
    MATLAB tree has ever run the v3.5 engine with the ORACLES thresholds. The
    ORACLES fork froze at v3.1.4 and was never rebased, so the fidelity
    claim is unaffected. So this profile **reproduces no archived
    product and must never be described as doing so**. It exists for exactly one
    purpose: to vary the threshold axis while holding the engine axis fixed, so
    that a difference between two runs can be attributed to one or the other.
    Its ``.call`` stamp records the name, which is how a reader tells such a run
    from a reproduction.

    The three threshold values and their provenance are the ORACLES fork's own
    dated edits, the ORACLES-variant ``calculate_reject_unified.m`` -- ``:72``
    ``rej_hollow 1 -> 0``, ``:76`` ``max_edge_img_ar 6 -> 4``, ``:77``
    ``max_comp_img_ar 5 -> 4`` -- against the v3.5 tree's stock block at
    ``UIOPS-v3.5/joefinlon-UIOPS-039be82/calculate_reject_unified.m:60-66``
    (``1/1/1/25/6/5``). Both blocks were read, not assumed.
    """
    global _oracles_prod_v35_cache
    if _oracles_prod_v35_cache is None:
        stock35 = _build_stock_v35()
        _oracles_prod_v35_cache = replace(
            stock35,
            name=_ORACLES_PROD_V35_NAME,
            description=(
                "The v3.5 engine run under the reject thresholds a field campaign's "
                "modified UIOOPS v3.1.4 used. "
                "SYNTHETIC: no MATLAB tree ever ran this combination -- that modified "
                "UIOOPS was never moved onto v3.5 -- so this profile "
                "reproduces NO archived product and must not be cited as reproducing one. "
                "It exists to hold the engine fixed while the threshold axis varies, so a "
                "difference between two runs is attributable. Behaviour fields are "
                "stock-v3.5's, unchanged and still cited to "
                "the v3.5 tree. Only reject_thresholds differ, taking that modified "
                "UIOOPS's calculate_reject_unified.m:72 (rej_hollow "
                "1->0), :76 (max_edge_img_ar 6->4) and :77 (max_comp_img_ar 5->4), against "
                "v3.5's stock 1/1/1/25/6/5 at calculate_reject_unified.m:60-66. NOTE for a "
                "64-diode probe: this profile leaves rej_hollow OFF, so unlike stock-v3.5 "
                "it does not exercise the 32-diode hollow packing defect."
            ),
            reject_thresholds=ORACLES_PRODUCTION_REJECT_CONFIG,
        )
        _REGISTRY[_ORACLES_PROD_V35_NAME] = _oracles_prod_v35_cache
        _V35_TREE_PROFILES.add(_ORACLES_PROD_V35_NAME)
    return _oracles_prod_v35_cache


_IMAGE_ASSISTED_V35_NAME = "stock-v3.5-image-assisted"

#: Cache for :func:`register_stock_v35_image_assisted`, built from ``STOCK_V35``
#: the same way :data:`_oracles_prod_v35_cache` is -- ``None`` until first needed.
_image_assisted_v35_cache: FidelityProfile | None = None


def register_stock_v35_image_assisted() -> FidelityProfile:
    """Build, register and return ``stock-v3.5-image-assisted``.

    **What it is.** :data:`STOCK_V35` with exactly one field moved:
    ``reject_thresholds`` becomes
    :data:`arrayprobe_uiops.measure.IMAGE_ASSISTED_V35_REJECT_CONFIG` --
    ``rej_hollow`` off, ``max_edge_img_ar`` and ``max_comp_img_ar`` left at
    stock's 6 and 5. See that constant's own docstring for the full
    evidence (200 triage labels) and its honest caveat (this
    configuration is not optimal at 55-105 um, where the hollow test it turns
    off was correct 25/25). Built the same way as
    :func:`_build_oracles_production_v35` -- ``dataclasses.replace`` off
    ``STOCK_V35``, so every non-threshold field is provably identical to it and
    :func:`is_v35_flavoured` admits it without re-deriving anything.

    **Why registered rather than shipped as a fourth module-level constant
    like ``STOCK_V35``/``ORACLES_PRODUCTION_V35``.** Two existing tests pin the
    module's *shipped, ``dir()``-visible* surface to exactly its current
    members: ``tests/test_profile_registry.py::
    test_the_shipped_set_does_not_grow_with_registrations`` pins :data:`SHIPPED`
    to five names, and ``tests/test_cli_engine_selection.py::
    test_the_second_reason_names_the_v35_profiles_that_exist`` enumerates every
    uppercase ``dir(profiles)`` name whose value is a :class:`FidelityProfile`
    and pins that list to ``["ORACLES_PRODUCTION_V35", "STOCK_V35"]`` --
    the second test's own docstring says outright that "the next one
    registered fails this again and the prose has to catch up" (``cli.py``'s
    refusal message). This profile is deliberately reached the same way a
    fork's own variant is -- ``profiles.PROFILES["stock-v3.5-image-assisted"]``
    or ``profiles.profile(...)``, never ``profiles.STOCK_V35_IMAGE_ASSISTED`` --
    which is also the more accurate description: the project's one-package-per-upstream rule already
    settles this as an opt-in configuration selected per run, not a new shipped
    default, and per that same decision it adds no package.

    Calls :func:`register_profile` with ``cites_tree="3.5"``, so
    :func:`is_v35_flavoured` -- and therefore the ``--engine 3.5`` gate in
    ``scripts/run_flight.py`` -- admits it exactly as it would a fork's own
    declared variant. Idempotent and cached like :func:`_build_stock_v35`: safe
    to call from every entry point that needs the name resolvable
    (``scripts/run_flight.py``-style CLI lookups, the CIP lane scripts under
    ``_decoded/cip160906/``) without risking ``register_profile``'s
    already-registered ``ValueError`` on a second call.
    """
    global _image_assisted_v35_cache
    if _image_assisted_v35_cache is None:
        from arrayprobe_uiops.measure import IMAGE_ASSISTED_V35_REJECT_CONFIG

        stock35 = _build_stock_v35()
        new = replace(
            stock35,
            name=_IMAGE_ASSISTED_V35_NAME,
            description=(
                "The v3.5 engine under stock-v3.5's own reject thresholds except "
                "rej_hollow, which is OFF. Behaviour fields are stock-v3.5's, "
                "unchanged (same construction as oracles-production-v3.5: "
                "dataclasses.replace off STOCK_V35). Only reject_thresholds "
                "differs, taking arrayprobe_uiops.measure."
                "IMAGE_ASSISTED_V35_REJECT_CONFIG -- rej_hollow False against "
                "stock-v3.5's True at calculate_reject_unified.m:62 in "
                "UIOPS-v3.5/joefinlon-UIOPS-039be82/, max_edge_img_ar and "
                "max_comp_img_ar left at stock's 6 and 5 (:65, :66), unlike "
                "oracles-production-v3.5 which also moves both of those. NOT a "
                "MATLAB tree's value -- a project decision, "
                "from 200 triage "
                "labels: the hollow test discards 19 of 25 real particles at "
                "205-305um (~5,654 counts, ~76% real) and is ambiguous at "
                "105-205um (11 real/14 artifact), against 25/25 correct at "
                "55-105um. Isolates the axis oracles-production-v3.5's A/B "
                "confounded: stock's looser aspect ratios were partly "
                "cancelling its stricter hollow test (R=1.0396 at 55-105um "
                "vs R=0.2283 at 205-305um). CAVEAT: turning rej_hollow off "
                "flat also admits the 55-105um artifacts that test was "
                "correctly catching -- that bin is 68% artifact even among "
                "particles both configurations accept, so this profile is not "
                "optimal there; a size-dependent rule is future opt-in work "
                "inside the engine, not this profile."
            ),
            reject_thresholds=IMAGE_ASSISTED_V35_REJECT_CONFIG,
        )
        _image_assisted_v35_cache = register_profile(new, cites_tree="3.5")
    return _image_assisted_v35_cache


_LAZY.setdefault(_STOCK_V35_NAME, _build_stock_v35)
_LAZY.setdefault(_ORACLES_PROD_V35_NAME, _build_oracles_production_v35)


def __getattr__(name: str) -> FidelityProfile:
    """Module-level lazy attribute: ``profiles.STOCK_V35`` triggers the build.

    Only reached when normal attribute lookup misses -- i.e. before
    :func:`_build_stock_v35` has ever run, since it is only then that this
    module's namespace has no ``STOCK_V35`` of its own. ``from arrayprobe_uiops.
    profiles import STOCK_V35`` goes through this too, the same as any other
    attribute access.
    """
    if name == "STOCK_V35":
        return _build_stock_v35()
    if name == "ORACLES_PRODUCTION_V35":
        return _build_oracles_production_v35()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """``dir(profiles)`` lists the lazy :data:`STOCK_V35` too (PEP 562), so code that
    enumerates the module's profiles still finds it; listing it builds nothing."""
    return sorted(set(globals()) | {"STOCK_V35", "ORACLES_PRODUCTION_V35"})
