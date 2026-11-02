# How a size distribution is built
> From shadow images to number concentration per size bin: what each stage decides, and where each decision lives in the code.

An optical array probe records shadows. A row of photodiodes sits across the airflow; each time
the probe clocks the array it writes one *slice* — which diodes were shadowed — and a particle
passing through becomes a stack of slices. Nothing in the raw file is a size or a
concentration. Every number in a size distribution is the result of four decisions made in
order, and this page walks through them in the order the pipeline makes them.

**See also** [User guide](02-user-guide.md) for the commands · [Configuration](06-configuration.md) for the settings named below · [Glossary](11-glossary.md) for cells, bins and denominators · [Conventions and terms](09-conventions.md) for file names.

## 1. Decode — raw records to image buffers

The raw file is the manufacturer's own record format: compressed image data interleaved with
housekeeping packets. The reader (stage `2` of `arrayprobe run`, one module per format family) unpacks it into a netCDF file of fixed-size image records — the layout
UIOOPS's own `read_binary_*.m` writes, so the next stage cannot tell which program produced it.
For the SPEC probes (2D-S, HVPS) the horizontal and vertical channels are separate arrays and
are written to separate files, `<out>.H.cdf` and `<out>.V.cdf`, and the housekeeping stream
goes to plain-text sidecars beside them. The one that matters downstream is `<out>.tas.csv`:
the probe's own true-air-speed record, which the size-distribution stage uses to turn a count
into a concentration.

Nothing is decided here about particles. The decode is a format conversion, which is why it is
the one stage whose output is compared byte for byte.

## 2. Frame — image buffers to particles

Stage `3` of `arrayprobe run` (UIOOPS's `imgProc_sm.m`) walks the image records,
splits the slice stream into particles at the probe's particle boundaries, and describes each
particle it finds. The description is one row of the per-particle `proc` file:

- **when** it arrived — its time and its inter-arrival time, the gap since the particle before;
- **how big** it is, several ways at once — its extent along the diode array, its extent along
  the direction of flight, its shadowed area, its perimeter, and the diameter of the smallest
  circle that encloses it (the routine UIOOPS ships only as a compiled `CGAL_minR` binary; here it
  is reimplemented, and because that circle is unique, agreement with the original is exact
  rather than approximate);
- **what shape** it is — a habit class after Holroyd (1987);
- **whether to trust it** — an automatic reject code from `calculate_reject_unified.m`, which
  flags images that touch the array edge, look hollow, are too elongated, or otherwise fail a
  test. `'0'` means accepted.

Framing decides *what a particle is*. It does not yet decide which particles count: a rejected
particle is still written, with its code, so the decision can be audited later.

The reject thresholds are the first setting that changes the science. They are fields of a named
[fidelity profile](06-configuration.md), never loose numbers, because the archived
products were made with thresholds that differ from the released defaults.

## 3. Size and count — particles to one-second distributions

Stage `4` of `arrayprobe run` (UIOOPS's `sizeDist.m`) turns the particle list into a
distribution for every second of flight. Four decisions happen here, in this order.

**Which particles are accepted.** A particle whose reject code is not an accepting one is set
aside. Then *shattering*: an ice crystal striking the probe tips breaks into fragments that
arrive in a burst, so particles whose inter-arrival time is shorter than a threshold are
removed. The threshold comes from a file or from a per-probe constant, and the optional
twelfth `sizeDist` argument decides which — the [user guide](02-user-guide.md#or-drive-each-stage)
explains why passing a file name that does not exist is a different call from passing nothing.

**How big each accepted particle is.** `d_choice` picks one of the six size definitions framing
computed — the minimum enclosing circle is `d_choice = 6`, the value every UIOOPS run script
uses. The [configuration page](06-configuration.md) tables all six.

**Which bin it falls in.** Each probe has a fixed ladder of size bins; the particle is counted
in the bin containing its size. Counting is per second of flight.

**How much air was sampled.** This is what turns a count into a concentration. For each bin the
sampled volume is

> sample volume = sample area × true air speed × live time

The **sample area** depends on the particle's size and on `sa_method`: whether a particle counts
when its centre lies within the array (*centre-in*), only when it lies wholly within it
(*entire-in*), or with the reconstruction correction that widens the array. A large particle has
a smaller entire-in sample area than a small one, so this choice moves large-particle
concentrations most. The **true air speed** is the probe's own record from the decode's
`.tas.csv` sidecar. The **live time** is the part of each second the probe was able to record —
the sum of inter-arrival times, less the time lost to overloads while image data was being saved
— written to the output as `sum_IntArr`; the sample volume itself is written as `sample_vol`
(cm³, per bin and second).

The concentration in each bin is then the count divided by that volume and by the bin's width:
`conc_minR`, in cm⁻⁴ — particles per cubic centimetre of air per centimetre of size. The same
stage also writes area, mass and fall-speed distributions from the same accepted particles.

## 4. Combine — a flight's files into one product

A flight usually arrives as several raw files, each carrying its own start time.
`combine` (`arrayprobe.combine.combine_sizedist`) stitches their one-second files onto one time
axis, synchronised to the campaign summary file's timestamp, and writes the product a data user
downloads — `<flight>.combined.<channel>.<probe>.cdf`. The order of the input files is part of
the contract, which is why the function takes an explicit ordered list.

No stock UIOOPS release has this step: the combine comes from one field campaign's modified copy of UIOOPS,
which is why a [v3.5 run](02-user-guide.md) stitches a product only when its configuration asks for
that combine by name.

## Where the numbers can move, in one table

| Stage | The setting | What it changes |
|---|---|---|
| Frame | reject thresholds (the fidelity profile) | which particles are flagged |
| Size and count | shattering threshold, and whether the block runs at all | which accepted particles are removed as fragments |
| Size and count | `d_choice` | the size assigned to each particle, so which bin it lands in |
| Size and count | `sa_method` | the sampled volume per bin, so every concentration |
| Frame | stuck-diode masks (off by default) | the image itself, before anything is measured |

Every one of these is a required argument or a named profile, never a default, and each run
writes a `.call` sidecar beside its output recording the call it made — because an output file
cannot be asked afterwards which of these it was made with.

## What this page does not cover

Which engine to run and what its numbers rest on: [Choosing an engine](27-choosing-an-engine.md).
Why reproducing the original's behaviour came before any correction:
[Why reproduce the original first](26-why-reproduce-first.md). The particle-level evidence behind
each decision above — every framed particle rendered beside its computed fields — is in the
[visualisation tool](03-visualisation.md).
