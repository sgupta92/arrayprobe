# SPDX-License-Identifier: BSD-3-Clause
"""Which engine each enhancement may be applied to, declared per module.

A user should never have to guess which enhancement applies to which engine;
this module declares it, and :func:`check` refuses a combination that does not
apply.

**Why this has to be code and not a table in a document.** Three of the defects
these modules correct were fixed by the UIOOPS developers themselves in v3.5.
Running ``wide_hollow_fix`` on the v3.5 engine would not be a harmless no-op --
it would correct an already-corrected value, and the output would be silently
wrong. A markdown column cannot refuse that; :func:`applicable` can.

**Four states, and the difference between the last two matters.**

``APPLIES``
    The defect is present in that engine's source, so the correction is live.
``SUPERSEDED``
    The upstream developers fixed it in v3.5. Applying the enhancement there
    double-corrects. These are the project's strongest external evidence -- a
    finding the maintainers independently fixed -- and they are named with the
    v3.5 line that fixed them.

    **Where an engine still carries the defect, use the better correction**,
    not the v3.5 one by default. ``upstream_route``
    carries the verdict per row, and it is a **measurement, not a preference**
    -- all four were compared against the v3.5 implementation and the answers
    differ:

    * ``wide_hollow_fix`` (A1) -- **composed from both.** v3.5's rewrite fixed
      the diode-32 hollow test *and* the late-start hole window and introduced the lost hollow coverage criterion, so the entry point takes its window
      removal and keeps v3.1.4's any-overlap coverage guard.
    * ``int16_double_fix`` (A2) -- **equivalent**, bit-identical over 100,000
      comparisons.
    * ``reshape_fix`` (A6) -- **equivalent**, the scramble inverts exactly.
    * ``conc_arear_fix`` (A4) -- **theirs is better**, slightly: ours takes an
      ``(x/d)*d*d`` round-trip that differs from ``x*d`` in the last bit on
      9.8 % of values.

    Three different answers from four rows is the argument for measuring
    rather than adopting a rule in either direction.
``VARIANT_ONLY``
    The construct exists in **no** stock UIOOPS release; it describes a field
    campaign's modified UIOOPS, and is absent from stock v3.5 rather than
    fixed in it.
``UNESTABLISHED``
    Not yet read against v3.5. **This is not "fixed"**, and it is not
    "applies". The v3.5 findings classifier establishes *presence* only,
    so its ``not-found`` is a search miss: *"a 'not located' row means read
    it, never fixed."* An
    ``UNESTABLISHED`` enhancement is refused on v3.5 the same way a superseded
    one is, because shipping an unverified correction against the default
    engine is the failure this whole module exists to prevent. Moving a row out
    of this state means reading the v3.5 source, not re-running the classifier.

    **The set is empty.** The five rows the
    classifier could not locate -- ``hole_edge_swap`` (C5), ``zero_image_
    recovery`` (A10), ``mask_presence_fix`` (F1), ``particle_number_all_fix``
    (C5b), ``rollover_fix`` (A5) -- were each read directly against
    ``UIOPS-v3.5/joefinlon-UIOPS-039be82/``; every row now carries a
    ``v35_site`` and the tag ``"read-against-v35"``. A sixth row,
    ``diode_range_fix`` (F3), was reclassified from a plain live row to
    ``VARIANT_ONLY`` in the same pass for the same reason. None were found
    to be genuinely unreadable, so this state currently has no members --
    a future finding lands here again only if the v3.5 source itself
    cannot settle it.

**How the four were established, and why two sources disagree.** The
``SUPERSEDED`` set comes from a hand-read
*"already fixed"* table, not from the classifier -- ``the missing mean-ratio transpose``'s construct still
matches in v3.5 and the classifier calls it ``still-present``, while reading the
source shows the fix (dated *Joe Finlon 02/13/19*). A defect fixed by rewriting
the code around it still classifies as present. Where the two disagree, the
reading wins, and ``test_engine_applicability.py`` asserts the ``SUPERSEDED``
set against that table so neither side can drift alone.

New-capability and literature modules correct no defect and are engine-agnostic
by construction; they are declared ``APPLIES`` on both, with the basis saying
so rather than citing a finding they do not have.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

__all__ = [
    "ENGINES",
    "DEFAULT_ENGINE",
    "Applicability",
    "APPLICABILITY",
    "NotApplicableToEngine",
    "UnknownEngine",
    "applicable",
    "check",
    "for_engine",
    "register_engine",
]

#: The UIOOPS engines an enhancement can be applied to. SODA-2 is deliberately
#: absent: it is a different processing lineage rather than a UIOOPS version
#: its port covers the particle path only,
#: and no enhancement here was written against it.
ENGINES: tuple[str, ...] = ("3.1.4", "3.5")

#: What a caller who names no engine gets.
DEFAULT_ENGINE = "3.5"


def register_engine(engine_id: str, *,
                     table: dict[str, "Applicability"] | None = None) -> None:
    """Extend :data:`ENGINES` with a third lineage sharing this driver.

    The SODA-2 package is a *separate* processing
    lineage, not a UIOOPS version, and its own isolation test
    (``enhancements_soda2/tests/test_lineage_isolation.py``) forbids it from
    importing this module at all -- so this hook is deliberately **not**
    wired to SODA-2. It exists for a future UIOOPS-family engine that *does*
    share ``pipeline.py``'s driver and wants an applicability declaration.

    Refuses a duplicate registration, including re-registering either of the
    two built-in engines (``"3.1.4"``, ``"3.5"``) -- the two cases are the
    same check, since a genuine duplicate call always names an id already in
    :data:`ENGINES`.

    ``table`` optionally supplies full :class:`Applicability` declarations
    for modules specific to the new lineage, merged into
    :data:`APPLICABILITY` (overwriting a name it repeats). Passing no table
    still leaves every existing module with a defined answer for the new
    engine: :meth:`Applicability.state`'s own ``dict.get`` default already
    reads an engine key it has never heard of as :data:`UNESTABLISHED`
    (:func:`check`'s ``entry.state.get(engine, UNESTABLISHED)``), which is
    the correct refusal for a module nobody has read against this lineage
    yet -- never "applies" by default.
    """
    global ENGINES
    if engine_id in ENGINES:
        raise ValueError(
            f"engine {engine_id!r} is already registered: {ENGINES}. "
            f"Registering the same id twice, including either built-in "
            f"engine, is refused rather than silently re-accepted.")
    ENGINES = ENGINES + (engine_id,)
    if table:
        APPLICABILITY.update(table)


APPLIES = "applies"
SUPERSEDED = "superseded-upstream"
VARIANT_ONLY = "variant-only"
UNESTABLISHED = "unestablished"


class UnknownEngine(ValueError):
    """An engine name that is not one of :data:`ENGINES`."""


class NotApplicableToEngine(RuntimeError):
    """An enhancement was asked for on an engine it does not cover.

    Raised rather than silently dropped. A config that names an enhancement
    asked for it, and a silent drop would look identical to the enhancement
    having run, which is the failure mode the registry's ``UnknownEnhancement``
    already refuses for a different reason.
    """


@dataclass(frozen=True)
class Applicability:
    """One module's engine coverage, and how it was established.

    ``state`` maps engine id to one of the four states above. ``basis`` says
    how, in one line a reader can check: a finding id and a v3.5 line for a
    superseded row, the classifier axis for a live one, "no defect corrected"
    for a capability module.
    """

    finding: str | None
    state: dict[str, str]
    basis: str
    v35_site: str | None = None
    tags: frozenset[str] = field(default_factory=frozenset)
    #: For a superseded row, how a v3.1.4 user gets the developers' own fix
    #: rather than this project's independent one. Either a callable to use (``"module:function"``) or the
    #: plain fact that there is nothing to borrow and the answer is to run the
    #: v3.5 engine. Required on every SUPERSEDED row, checked by
    #: ``test_engine_applicability.py``.
    upstream_route: str = ""

    def runs_on(self, engine: str) -> bool:
        return self.state.get(engine) == APPLIES


def _both(basis: str, finding: str | None = None, **kw) -> Applicability:
    return Applicability(finding=finding,
                         state={"3.1.4": APPLIES, "3.5": APPLIES},
                         basis=basis, **kw)


def _superseded(finding: str, site: str, what: str, *,
                route: str) -> Applicability:
    return Applicability(
        finding=finding,
        state={"3.1.4": APPLIES, "3.5": SUPERSEDED},
        basis=f"already fixed in v3.5, established by reading the v3.5 source: "
              f"{what}",
        v35_site=site,
        upstream_route=route)


def _unestablished(finding: str, file: str) -> Applicability:
    return Applicability(
        finding=finding,
        state={"3.1.4": APPLIES, "3.5": UNESTABLISHED},
        basis=f"classify_findings_v35.py reports 'not-found' for this finding in "
              f"{file}, which is a search miss and NOT a finding of removal. "
              f"Read the v3.5 source to settle it.")


#: Every shipped enhancement module, keyed by its module stem -- the same
#: string the config file uses. ``test_engine_applicability.py`` asserts this
#: covers exactly the modules on disk, so a new enhancement cannot ship
#: without saying which engines it is for.
APPLICABILITY: dict[str, Applicability] = {

    # --- Fixed by the UIOOPS developers themselves, in v3.5 -----------------
    # These four are the project's strongest external evidence and its
    # sharpest hazard: correct on v3.1.4, double-correcting on v3.5.
    "wide_hollow_fix": _superseded(
        finding="the diode-32 hollow test", site="calculate_reject_unified.m:374",
        what="the 32-bit bin2dec packing is gone, replaced by "
        "bitand(image_buf(i,:)=='1', old=='1') across the full array width",
        route="COMPOSED FROM BOTH, not delegated: wide_hollow_fix.better_is_it_hollow takes v3.5's removal of the middle-third max-hole window (A19, a real improvement) and declines its coverage-guard regression (V29 -- :385's bare `if` on a logical array reads as all-elements, so the 0.65 criterion ran 290 of 298 times in v3.1.4 and 0 of 299 in v3.5). Blanket delegation was the first pass and was wrong. tests/test_wide_hollow_vs_upstream.py"),
    "int16_double_fix": _superseded(
        finding="the int16 diameter saturation", site="sizeDist.m:941-942",
        what="im_width = double(netcdf.getVar(...)) -- the cast moved to the read, "
        "dated Joe Finlon 02/13/19, which is the edit this project's upstream feedback suggested",
        route="EQUIVALENT: measured bit-identical to arrayprobe_uiops.sizedist.d_choice_diameter over 100,000 comparisons spanning all five affected branches (tests/test_superseded_corrections_on_the_merits.py). The structures differ -- v3.5 casts at the read (sizeDist.m:941-942), this module promotes before the multiply -- but the saturation is in the multiply and not in the stored value, so both recover the same number exactly. Neither is better; use whichever engine you are already on"),
    "conc_arear_fix": _superseded(
        finding="the double-scaled area-ratio concentration", site="sizeDist.m:957",
        what="the second diode-size scaling is commented out, with the reason "
        "recorded beside it",
        route="THEIRS IS BETTER, slightly and measurably: v3.5 simply omits the second scaling (sizeDist.m:957) where this module pre-divides image_diam_AreaR on disk and re-runs the unmodified pipeline, so the value takes an (x/d)*d*d round-trip against v3.5's x*d. Measured over 200,000 values at diodesize 0.010: 19,555 of 200,000 (9.8 %) differ, all in the last bit, max relative 2.7e-16. The variable is declared double so that is the live case; stored as float32 it would be every value at ~2e-8. Far below any measurement, and still a reason to prefer running v3.5 for A4 rather than repairing afterwards (tests/test_superseded_corrections_on_the_merits.py)"),
    "reshape_fix": _superseded(
        finding="the missing mean-ratio transpose", site="sizeDist.m:2412, :2434",
        what="all six variables now carry the transpose their neighbours had, same "
        "dated pass as the int16 x double cast fix. The classifier still calls "
        "this finding still-present, "
        "because a defect fixed by rewriting the code around it goes on "
        "matching -- the reading wins",
        route="EQUIVALENT: the scramble is a bijection and this module inverts it exactly -- 2,000 of 2,000 random (n_time, n_bins) arrays recovered element for element (tests/test_superseded_corrections_on_the_merits.py). v3.5 avoids the scramble by writing the transpose (sizeDist.m:2412, :2434); repairing afterwards loses nothing. Neither is better"),

    # --- Unchanged in v3.5: the probetype-1 branch is still missing ----------
    "int_arr_rollback_fix": Applicability(
        finding="the missing probetype-1 rollback correction",
        state={"3.1.4": APPLIES, "3.5": APPLIES},
        basis="read against v3.5: the inter-arrival rollback branch is unchanged -- "
              "sizeDist.m:1025-1029 corrects probetype 2 (int_arr < -10) and probetype 0 "
              "(int_arr < 0) and has no clause for probetype 1, and :1044-1045 still marks "
              "every particle left negative 'I' and zeroes its int_arr, as v3.1.4's "
              ":852-856 and :871-872 do. Live on v3.5 for probetype 1 on every "
              "iaThreshType; the shattering-reacceptance fix v3.5 made in its type-3 "
              "branch is a different finding and does not touch this branch",
        v35_site="sizeDist.m:1025-1029 (no probetype-1 clause), :1044-1045 (the 'I' reject)",
        tags=frozenset({"read-against-v35"})),

    # --- Present in v3.5, located with a line -----------------------------
    "spot_edge_fix": _both(
        "classifier: still-present in calculate_reject_unified.m", finding="the missing decimal in spot_edge",
        v35_site="calculate_reject_unified.m:53", tags=frozenset({"read-against-v35"})),
    "outoffocus": _both(
        "classifier: still-present in sizeDist.m", finding="the unapplied Korolev size correction",
        v35_site="calculate_reject_unified.m:286-287 (part_z/size_factor lookups; "
                 "handles.rej_hollow forced to 1 at :62, so the hollow block always "
                 "runs under the stock v3.5 driver)",
        tags=frozenset({"read-against-v35"})),
    "reaccept_every_event_fix": Applicability(
        finding="the first-event-only reacceptance scan",
        state={"3.1.4": APPLIES, "3.5": APPLIES},
        basis="read: v3.5 sizeDist.m:1213 (iaThreshType 1) and :1346 (type 2) still "
              "iterate find(rBegin):find(rEnd), MATLAB's first-element colon rule, so the "
              "defect is intact on both v3.5 paths an earlier release could take; only the new "
              "type-3 block (:1403-1427, 'JF 11/5/25') brackets first-rBegin..last-rEnd. This "
              "module applies that bracket to types 1 and 2 on both engines; the substitution "
              "cannot reach type 3, which calls reaccept_shattered_1hz directly. Registry ON "
              "by default; the Python keyword defaults off",
        v35_site="sizeDist.m:1213, :1346 (defect intact); :1416-1419 (the developers' fix)",
        tags=frozenset({"read-against-v35", "conditional-on-v35"}),
        upstream_route="applies the developers' own fix: the type-3 bracket (sizeDist.m:1416-1419) "
                       "moved onto the type-1/2 paths; semantic asserted equal to "
                       "arrayprobe_uiops.sizedist_tables.reaccept_shattered_1hz"),
    "overload_accounting_fix": Applicability(
        finding="the no-accept second overwrite",
        state={"3.1.4": APPLIES, "3.5": APPLIES},
        basis="classifier: still-present in sizeDist.m. Conditional on the run, not on "
              "the engine: v3.5 sizeDist.m only defVars sum_IntArr/"
              "sample_vol under `if iSaveIntArrSV == 1` (:2363-2372), and "
              "scripts/run_flight.py's V35_CALL pins iSaveIntArrSV=0 for every default "
              "v3.5 run (arrayprobe_uiops/sizedist.py:706's write gate) -- measured on "
              "the tracked demo_flight_v35_sd.nc, which holds neither variable. The "
              "module names this refusal (overload_accounting_fix."
              "MissingSizeDistVariables) rather than applying vacuously; a caller who "
              "wants this correction on v3.5 must re-run sizedist.run with i_save_int_arr_sv=1 first",
        v35_site="sizeDist.m:2363 (iSaveIntArrSV gate), :2364/:2369 (defVar)",
        tags=frozenset({"conditional-on-v35"})),
    "last_record_fix": Applicability(
        finding="the dropped final raw record",
        state={"3.1.4": APPLIES, "3.5": APPLIES},
        basis="classifier: still-present in read_binary_SPEC.m; confirmed by "
              "direct read: the outer record loop "
              "(:145, `while feof(fid)==0 && endfile == 0`) and the one-byte "
              "EOF probe on the pair (N, N+1) (:248-252) are unchanged from "
              "v3.1.4, so the last record of a v3.5 raw file is dropped the "
              "same way. `:297`'s tighter scan bound (`iii+4<=2048`) is a "
              "change inside get_img, not to the outer loop's EOF probe, and "
              "does not touch this defect. Applicable to both engines, but "
              "reader-stage (registry.py's `stage` field): `arrayprobe-enhanced "
              "run` cannot apply it after the port has already decoded, and the "
              "re-decode path that would be needed is not built -- call read_binary_spec_with_last_record "
              "yourself, before the port runs, rather than through the driver",
        v35_site="read_binary_SPEC.m:248-252",
        tags=frozenset({"read-against-v35", "reader-stage"})),
    "tas_grid_fix": _both(
        "classifier: still-present in sizeDist.m", finding="the duplicate TAS-second particle loss",
        v35_site="sizeDist.m:135", tags=frozenset({"read-against-v35"})),
    "diode_range_fix": Applicability(
        finding="the image-widening diode number",
        state={"3.1.4": APPLIES, "3.5": VARIANT_ONLY},
        basis="read against v3.5: the only surviving construct is the width "
              "guard (imgProc_sm.m:850, `figsize(2)~=diodenum` -> disp + "
              "return); no mask re-illumination/widening code (`shadow_diode`, "
              "`c(:,...)='1'`) exists anywhere in the file -- grepped for "
              "'diodenum', 'figsize', 'shadow_diode' and neither the "
              "nine-argument imgProc_sm form nor masks.reilluminate's "
              "MATLAB counterpart is present. The widening this module "
              "corrects is on the mask-file path, which is FORK_ONLY per "
              "uiops.CATALOGUE and absent from stock v3.5",
        v35_site="imgProc_sm.m:850 (guard only; no widening construct)",
        tags=frozenset({"read-against-v35"})),
    "particle_time_int8_fix": _both(
        "measured against v3.5: the Octave oracle pair "
        "for this finding, "
        "rebuilt on the unmodified v3.5 tree with the real CGAL_minR_v35 "
        "MEX, writes particle_time [127, 127] at 06:06:58 where the true "
        "value is [60658, 60702]; its 00:00:58 twin writes [58, 102], which "
        "the correction reproduces exactly. Same write expression "
        "(imgProc_sm.m:1336) over the same int8 header seed (:697, :887-889). "
        "test_particle_time_int8_fix.py::AgainstTheV35OctaveOraclePair",
        finding="the int8 particle-time collapse", v35_site="imgProc_sm.m:1336",
        tags=frozenset({"read-against-v35", "measured-against-v35"})),

    # --- The file is byte-identical between the two releases --------------
    "pms_c6_routing_fix": _both(
        "read_binary_PMS.m is byte-identical between v3.1.4 and v3.5, so the "
        "finding and its line numbers transfer untouched. Applicable to both "
        "engines, but reader-stage (registry.py's `stage` field): "
        "`arrayprobe run --enhancements` cannot apply it after the port has already "
        "decoded, and no re-decode path is built for it -- call "
        "read_binary_PMS_corrected yourself, before the port runs, rather "
        "than through the driver",
        finding="the misfiled F2DC scalar fields", tags=frozenset({"reader-stage"})),
    "pressure_units_fix": _both(
        "single_vt.m is byte-identical between v3.1.4 and v3.5, so the "
        "finding and its line numbers transfer untouched", finding="the unchecked pressure unit",
        v35_site="sizeDist.m:1167", tags=frozenset({"read-against-v35"})),

    # --- A campaign fork, not stock UIOOPS  --------------------------------
    "intarr_threshold_fix": Applicability(
        finding="the global-minimum inter-arrival threshold",
        state={"3.1.4": APPLIES, "3.5": VARIANT_ONLY},
        basis="classifier: variant-only. The construct exists in no stock "
              "UIOOPS release -- it describes a field campaign's modified "
              "UIOOPS, which is what produced the archived products. Absent "
              "from stock v3.5 rather than fixed in it"),

    # --- Read against v3.5 directly ------------------------------------------
    # The classifier reported 'not-found' for these five; that is a search
    # miss, never a finding of removal. Each row below cites the v3.5 line
    # actually opened.
    "hole_edge_swap": Applicability(
        finding="the swapped hole variables",
        state={"3.1.4": APPLIES, "3.5": APPLIES},
        basis="read against v3.5: the swap is unchanged. defVar names "
              "varid29 'edge_at_max_hole' and varid30 'max_hole_diameter' "
              "(imgProc_sm.m:564-573); putVar then writes varid29 from "
              "images.max_hole_diameter and varid30 from "
              "images.edge_at_max_hole (:1376-1377) -- the two are still "
              "swapped on the way to disk, exactly as arrayprobe_uiops/"
              "imgproc.py:43-45, :729-732 already documents",
        v35_site="imgProc_sm.m:564-573 (defVar), :1376-1377 (putVar swap)",
        tags=frozenset({"read-against-v35"})),
    "zero_image_recovery": Applicability(
        finding="the abandoned zero-image record",
        state={"3.1.4": APPLIES, "3.5": VARIANT_ONLY},
        basis="read against v3.5: stock imgProc_sm.m already recovers a "
              "zero-image particle. Both zero-image branches advance with "
              "`start = j + 2; ... continue;` and the `break;` that would "
              "drop the particle is commented out (:766-769, :773-776, both "
              "'Properly treat zero-image particle ~ Joe Finlon & Adam "
              "Majewski 11/06/17'); the general per-particle advance at "
              ":1311 is the same `start = j + 2`. This module's `break` is "
              "the validation campaign's modified UIOOPS's, and the module "
              "is a FidelityProfile, "
              "which v3.5 has none of",
        v35_site="imgProc_sm.m:766-769, :773-776, :1311",
        tags=frozenset({"read-against-v35"})),
    "mask_presence_fix": Applicability(
        finding="the silent missing mask file",
        state={"3.1.4": APPLIES, "3.5": VARIANT_ONLY},
        basis="read against v3.5: imgProc_sm.m's signature "
              "(infile, outfile, probename, n, nEvery, projectname, "
              "iRectEllipse, iCalcAllDiodeStats, iQC, iNewHabit, varargin) "
              "carries no ninth-argument masks form, and grepping the whole "
              "file for 'exist(', 'maskfile', 'mask_file', 'reilluminate' "
              "and 'masks' returns nothing -- the 9-arg mask branch this "
              "module corrects is FORK_ONLY per uiops.CATALOGUE and does "
              "not exist in stock v3.5",
        v35_site="imgProc_sm.m:1 (signature); no mask branch found",
        tags=frozenset({"read-against-v35"})),
    "particle_number_all_fix": Applicability(
        finding="the sometimes-written Particle_number_all",
        state={"3.1.4": APPLIES, "3.5": APPLIES},
        basis="read against v3.5: the write guard still excludes probetype "
              "0 and 3. varid104 ('Particle_number_all') is *defined* under "
              "`if probetype~=0 || probetype~=3` (:347, an OR that is true "
              "for every probetype) but *written* under "
              "`if probetype~=0 && probetype~=3` (:1329, an AND that "
              "excludes probetype 0 and 3) -- the same asymmetric gate the "
              "port's docstring already cites (arrayprobe_uiops/imgproc.py "
              "':356' / ':1329-1331')",
        v35_site="imgProc_sm.m:347 (define, OR), :1329 (write, AND)",
        tags=frozenset({"read-against-v35"})),
    "rollover_fix": Applicability(
        finding="the first-midnight-only rollover",
        state={"3.1.4": APPLIES, "3.5": APPLIES},
        basis="read against v3.5: the two rollover halves diverged. The "
              "per-second `timehhmmss` rollover is byte-for-byte the "
              "original defect -- `timehhmmss(find(diff(timehhmmss)<0)+1:"
              "end) = ... + 240000` (:130-131) still uses only the first "
              "decrease, because MATLAB's `a:b` takes only the first element "
              "of a vector operand, unchanged from v3.1.4. The particle-time "
              "half (`image_time_hhmmssall`) loops over "
              "every decrease via `decreasedTimeInds` (:788-799), which is "
              "the half v3.5 fixed (arrayprobe_uiops/sizedist.py:172-215, "
              "`fix_multiday_particle_times`, which itself stops at the first "
              "genuine crossover it finds). This "
              "module corrects only the surviving `timehhmmss` half on v3.5",
        v35_site="sizeDist.m:130-131 (still defective), :788-799 (fixed)",
        tags=frozenset({"read-against-v35", "partial-on-v35"})),
    "particle_time_glitch_fix": Applicability(
        finding="the first-midnight-only rollover",
        state={"3.1.4": APPLIES, "3.5": APPLIES},
        basis="read and measured against v3.5: the developers met the cascade "
              "(sizeDist.m:788-806, Finlon 02/13/19, 'ignore corrupt particle "
              "boundary times') by shifting only at a decrease that passes their "
              "day-crossover test, but the test is applied to single values, so "
              "one all-ones header (316363 = 31:63:63) passes it -- on "
              "2016-09-06 CIP session 2, 232 decreases pass and "
              "arrayprobe_uiops.sizedist.fix_multiday_particle_times shifts "
              "2,886,521 particles from particle 910,043 on. A single glitch "
              "still cascades too (:787-789 shifts on exactly one decrease), and "
              "no version removes the glitched particles from the one-second "
              "block table. This module reuses their test (on local medians) to "
              "tell a crossover from a glitch, and repairs the proc before either "
              "engine's sizeDist reads it",
        v35_site="sizeDist.m:787-806 (the cascade guard, fooled by a glitch above 230000)",
        tags=frozenset({"read-against-v35", "measured-against-v35"})),

    # --- New capability: corrects no defect, so no version axis applies ---
    "arco_export": _both("new capability; corrects no defect"),
    "arm_export": _both("new capability; corrects no defect"),
    "cf_export": _both("new capability; corrects no defect -- reads sizeDist's variables, "
                       "whose unit strings are identical in v3.1.4 and v3.5 except re "
                       "(um vs mm), which the mapping accepts both ways"),
    "poisson_uncertainty": _both("new capability; corrects no defect"),
    "probe_crossover": _both("new capability; corrects no defect -- reads six "
                             "sd variables both sizeDist translations write "
                             "under the same names (test_probe_crossover.py "
                             "runs it on a v3.1.4 and a v3.5 sd file)"),
    "probe_uncertainty": _both("new capability; corrects no defect"),
    "effective_density": _both("new capability; corrects no defect"),
    "analysis": _both("new capability; corrects no defect"),
    "md_relations": _both("a table of mass-diameter relations; computes "
                          "nothing engine-specific"),
    "brown_francis_1995": _both(
        "new capability; a published (1995) aggregate mass-diameter power "
        "law, read directly from the paper and "
        "registered in md_relations; corrects no defect in either engine "
        "and is not consulted by either by default"),
    "dmax_sensitivity": _both("new capability; reports how far the six "
                              "diameter definitions disagree",
                              v35_site="sizeDist.m:941-942 (double cast), "
                                       ":1054-1066 (d_choice branches)",
                              tags=frozenset({"read-against-v35"})),
    "particle_clustering": _both(
        "new capability; reads nine proc-file columns by name "
        "(`extract_features`, particle_clustering.py:99-157) -- v3.5 drops "
        "one of them (`image_diam_circle_fit`), so `feature_names_for('3.5')` "
        "clusters on the remaining eight plus `compactness`. Row 29 in "
        "applicability_matrix.md",
        v35_site="imgProc_sm.m:455-458 (image_diam_circle_fit's defVar, "
                 "commented out)",
        tags=frozenset({"read-against-v35"})),
    "ml_accept_reject": _both("new capability; operates on rendered images, "
                              "not on either engine's internals"),

    # --- Literature methods, not corrections ------------------------------
    "distance_rejection": _both(
        "Korolev & Field (2015) §4; a published method applied to either "
        "engine's output, not a correction to either"),
    "poisson_restore": _both(
        "Korolev & Field (2015) Eq. 1-2; a published method applied to "
        "either engine's output, not a correction to either"),
    "intarr_policy": _both(
        "McFarquhar et al. (2017) p. 11.21; selects among the three "
        "thresholds both IntArrAnalysis_time.m and stock v3.5 "
        "IntArrAnalysis.m (:116, :146-147; writes :290) already compute, and "
        "varies the neighbour count of the (ix-1):ix flagging both engines "
        "share (v3.1.4 sizeDist.m:1017, :1149; v3.5 :1194, :1326, :1393)",
        v35_site="IntArrAnalysis.m:116,146-147,290; sizeDist.m:1194,1326,1393",
        tags=frozenset({"read-against-v35"})),
    "published_dof": _both(
        "Gurganus & Lawson (2018) Eq. 1, c = 8 +/- 0.2; replaces "
        "calc_sa_randombins.m:42, which is byte-identical in v3.1.4 and v3.5 "
        "(one port, sample_area.py:84-88, shared by both engines)"),

    "partial_image_habit": _both(
        "Korolev & Sussman (2000) Sect. 4b-d; a published population classifier "
        "applied to either engine's silhouettes, not a correction to either. Neither "
        "engine classifies accepted partials with a partial-specific rule: v3.1.4 runs "
        "holroyd.m on the truncated image (imgProc_sm.m:807); v3.5 withholds a habit "
        "('C') for centre-out images (imgProc_sm.m:1282-1285) and, under iNewHabit=1, "
        "for edge contact above half the diameter (holroyd_new.m:101-104), and runs the "
        "complete-image rules on the rest -- exclusion, not the paper's method, so "
        "there is no upstream fix to delegate to",
        v35_site="imgProc_sm.m:1282-1285; holroyd_new.m:101-104",
        tags=frozenset({"read-against-v35"})),
    "field2006_shatter": _both(
        "derived from NCAR Process2D (NCAR/aircraft_oap, Apache-2.0), Field et al. "
        "(2006); a published inter-arrival method applied to either engine's particle "
        "times, not a correction to either. Opt-in, selected per run"),

    # --- Probe-specific rather than version-specific ----------------------
    "spec_artefact_filter": _both(
        "2D-S only, per the SPEC manual; a probe restriction rather than a "
        "version one, and it applies to both engines' 2D-S output"),
}

#: The modules that repair what the v3.1.4 engine wrote, and so ship only where that engine
#: does. The public distribution omits that engine and these six with it; a name here whose
#: ``<name>.py`` is absent beside this file moves to :data:`OMITTED_APPLICABILITY`. A name not
#: listed here is never dropped, so a missing ordinary module still fails the on-disk tests.
REQUIRES_V314: frozenset[str] = frozenset({
    "conc_arear_fix", "last_record_fix", "pressure_units_fix",
    "reaccept_every_event_fix", "wide_hollow_fix", "zero_image_recovery",
})

#: Declarations of :data:`REQUIRES_V314` modules this distribution does not carry.
OMITTED_APPLICABILITY: dict[str, Applicability] = {}


def _omit_absent_v314_modules() -> None:
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    for name in sorted(REQUIRES_V314):
        if name in APPLICABILITY and not os.path.exists(os.path.join(here, name + ".py")):
            OMITTED_APPLICABILITY[name] = APPLICABILITY.pop(name)


_omit_absent_v314_modules()


def _require_engine(engine: str) -> str:
    if engine not in ENGINES:
        raise UnknownEngine(
            f"unknown engine {engine!r}; known: {list(ENGINES)}. SODA-2 is not "
            f"listed on purpose -- it is a separate processing lineage rather "
            f"than a UIOOPS version, and no enhancement was written against it.")
    return engine


def applicable(name: str, engine: str = DEFAULT_ENGINE) -> bool:
    """Whether enhancement ``name`` may be applied to ``engine``."""
    _require_engine(engine)
    if name not in APPLICABILITY:
        raise KeyError(
            f"no engine applicability declared for {name!r}. Every shipped "
            f"enhancement must declare one; see this module's docstring.")
    return APPLICABILITY[name].runs_on(engine)


def check(name: str, engine: str = DEFAULT_ENGINE) -> None:
    """Raise :class:`NotApplicableToEngine` unless ``name`` covers ``engine``."""
    if applicable(name, engine):
        return
    entry = APPLICABILITY[name]
    state = entry.state.get(engine, UNESTABLISHED)
    detail = {
        SUPERSEDED:
            "the UIOOPS developers fixed this themselves in v3.5, so applying "
            "it here would correct an already-corrected value",
        VARIANT_ONLY:
            "the construct it corrects exists in no stock UIOOPS release; it "
            "describes a field campaign's modified UIOOPS",
        UNESTABLISHED:
            "it has not been read against this engine's source yet, and an "
            "unverified correction against the default engine is exactly what "
            "this refusal exists to prevent",
    }.get(state, "it is not declared for this engine")
    site = f" ({entry.v35_site})" if entry.v35_site else ""
    raise NotApplicableToEngine(
        f"enhancement {name!r} is {state} on engine {engine}{site}: {detail}. "
        f"Basis: {entry.basis}.")


def for_engine(engine: str = DEFAULT_ENGINE,
               names: Iterable[str] | None = None) -> dict[str, bool]:
    """Every declared enhancement, mapped to whether it runs on ``engine``."""
    _require_engine(engine)
    wanted = list(APPLICABILITY) if names is None else list(names)
    return {n: applicable(n, engine) for n in wanted}
