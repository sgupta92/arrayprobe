# Weigel et al. (2016) thermodynamic concentration correction — status: BLOCKED on source access

The development plan lists "Weigel ξ·µ (T, p, TAS
side-inputs are located)" as the next enhancement. The attempt to implement it
stopped short of writing any correction code, for the reason below — per this project's own rule
("Never invent a fact to fill a gap"), a formula reconstructed from a secondary
summary rather than read from the paper is not an acceptable substitute for the real equation.

## What is confirmed, and how

- **The paper**: Weigel, R., et al. (2016), *Thermodynamic correction of particle concentrations
  measured by underwing probes on fast-flying aircraft*, Atmos. Meas. Tech., 9, 5135–5162,
  https://doi.org/10.5194/amt-9-5135-2016. Confirmed via `WebSearch` (title, journal,
  volume/page, DOI all agree with what the development plan
  and `developer/literature/README.md` already recorded).
- **What the correction does, in outline** (from the paper's own abstract, fetched via
  `WebFetch` on the article's HTML page — this is a paraphrase of the abstract, not a quotation of
  an equation): two multiplicative factors applied to a measured concentration —
  - a **compression factor ξ**, driven by aircraft true air speed (TAS): ξ ≈ 1.0 down to ≈0.85
    over TAS 60–250 m/s (i.e., it does not depend on particle size);
  - an **inertia factor µ(D_p)**, driven by particle diameter D_p: ≈1.0 below 70 µm, falling to
    ≈0.8 over 100–225 µm (i.e., it does not depend on TAS) — a cloud particle's inability to fully
    track the air's deceleration/redirection near the probe as its inertia grows with size.
  - The plan's own citation (`:279`) frames the combined effect as "+10–25 % on every
    concentration" once both factors are divided out.

## What is NOT confirmed — the actual gap

**The functional form and numeric coefficients of Eq. 7 (ξ, p. 5143) and Eqs. 8–9 (µ(D), same
page per the plan's citation) have not been obtained.** Three access attempts, in order:

1. `developer/literature/weigel_2016.pdf` — expected there by name,
   but **not present in the repository**: `developer/literature/*.pdf` is gitignored by policy (copyrighted
   journal PDFs, `.gitignore:80`) and this particular PDF was apparently never fetched into a
   local working copy either — `find . -iname '*weigel*'` under `developer/literature/` and
   `docs/developer/` found nothing.
2. `WebFetch` on the article's HTML page (`amt.copernicus.org/articles/9/5135/2016/…html`) —
   succeeded, but Copernicus's HTML article view does not render the in-text equations as
   extractable text (confirmed by the fetch model's own response: "the actual equation
   expressions are not included in the text extracted from this webpage").
3. `WebFetch` on the PDF directly — **failed**: `maxContentLength size of 10485760 exceeded`
   (the PDF is larger than the tool's 10 MB fetch cap). No alternate route (a smaller
   discussion-paper/preprint version, a secondary source quoting the equations verbatim) was found
   within the attempt's time-box.

**Refusing to guess**: the abstract-level ranges above (1.0→0.85, 1.0→0.8) describe the shape of
the correction but not its equation — attempting to back a formula out of two endpoints each would
be exactly the kind of reconstruction-from-a-neighbouring-example the project's standing rule
prohibits, especially for a change that "changes every number" (`:279`) once applied.

## What the "T, p, TAS side-inputs are located" half of the row asked for — this part IS resolved

Traced where temperature, pressure and TAS actually live in the existing port, so the eventual
implementation does not have to guess or re-plumb these:

| Input | Where it lives today | Notes |
|---|---|---|
| **TAS** (aircraft true air speed) | `src/arrayprobe/readers/tasinfo.py::load_tas_info`, reading the `.tas.csv` sidecar written by `readers.spec.read_binary_SPEC` | Time-varying, per-record (`timehhmmss`, `tas` columns). Already an array over the whole flight — exactly the resolution Weigel's TAS-dependent ξ needs. |
| **Static T, p** | `src/arrayprobe/cli.py`'s `sizedist` subcommand: `--pres`/`--temp` are **scalar CLI arguments**, broadcast to every record via `np.full_like(tas, args.pres)` / `np.full_like(tas, args.temp)` (`cli.py:230`) | **Not time-varying and not read from any file** — they are user-supplied constants for the whole flight, applied uniformly. This is a real fidelity fact worth recording: the port (following `sizeDist.m`'s own signature) has never had per-record ambient T/p, only per-flight constants. An enhancement wanting time-resolved T/p (as the plan's `.physical.1Hz` reference at row 732 implies) needs a **new** reader for that file — it does not exist in the port today under any name. |
| **Probe's own airspeed (PAS)** | **Not present anywhere in the port.** No reader, no CLI argument, no column in any tracked fixture carries a probe-local pitot/PAS value distinct from aircraft TAS. | Weigel's correction is explicitly for probes with their own air-speed sensor (the plan's `:279` "the probe's own airspeed" and `developer/literature/README.md`'s "the probe pitot's PAS"); if the 2D-S/HVPS units this project processes do not carry a PAS channel, the correction may need to run on TAS as a PAS substitute (a simplification the paper itself may or may not sanction — unknown without reading it) — another reason the real equations must be read before deciding.

## What is left to unblock this row

1. Obtain a copy of `weigel_2016.pdf` (a page-range extract under 10 MB is enough) and read
   Eq. 7 and Eqs. 8–9 directly, verbatim, with their page/equation numbers.
2. Confirm from the paper's own text whether the field campaign's 2D-S/HVPS units carry a usable PAS
   channel, or whether TAS is an accepted substitute for underwing probes lacking one.
3. Decide, once the real equation is in hand, whether static T/p need to become time-varying
   (a new `.physical.1Hz`-style reader) or whether the existing per-flight scalar is an acceptable
   approximation for this correction specifically — that is a scientific judgment call for the
   user, not an implementation detail to default silently.
4. Only then write `enhancements_uiops/src/arrayprobe_enhancements/weigel_thermodynamic_correction.py`
   (module name chosen to distinguish it from the inter-arrival-*rejection* enhancements already
   shipped — this is a **concentration correction**, not a rejection rule, despite the plan row's
   shorthand "Weigel ξ·µ" living among the inter-arrival rows) with the real formula, tests derived
   from the paper's own worked examples/figures if any are given, and a design doc rewritten from
   this one.

No code exists for this enhancement — a stub implementing an unverified formula
would be worse than no implementation, per this project's standing rule.
