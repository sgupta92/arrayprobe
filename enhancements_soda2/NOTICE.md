# Copyright and attribution

`arrayprobe` is distributed under the **3-clause BSD licence** (BSD-3-Clause), full text in
[`LICENSE`](LICENSE). The modules reproducing SODA-2 (`src/arrayprobe_soda2/`,
`enhancements_soda2/src/`) also retain SODA-2's own notice
([`LICENSES/BSD-3-Clause.txt`](LICENSES/BSD-3-Clause.txt)), and the one module derived from
NCAR Process2D also keeps Process2D's Apache-2.0 terms (see the Process2D paragraph). Each source file's
`SPDX-License-Identifier` line names its licence. The port is ported from **UIOOPS — the University of Illinois/Oklahoma
Optical Array Probe Processing Software** and is distributed under the 3-clause BSD licence
with the UIOOPS maintainers' permission; it credits UIOOPS's authors below.

**It reproduces work from two upstreams.** UIOOPS below, and **SODA-2**
(3-clause BSD, UCAR/NCAR) in its own section.

## The original

UIOOPS, McFarquhar research group (University of Illinois at Urbana-Champaign, later
University of Oklahoma), with contributions from Joe Finlon, Wei Wu and others. The
original copyright notices in the MATLAB sources are retained. This package distributes no
UIOOPS MATLAB source; `scripts/fetch_upstream.py` fetches the pinned, unmodified upstream
releases from the sources below and checks their hashes.

- Source: <https://github.com/joefinlon/UIOPS>
- Archived releases: v3.5, <https://zenodo.org/records/18945998> (the release the UIOOPS engine
  ports); v3.1.4, <https://zenodo.org/records/1285969> (the methodology citation)

**An independent port; it is not a UIOOPS or SODA-2 release.** The port
exists to make their methodology runnable without a MATLAB licence; the science is theirs.

## If you use this

Cite **UIOOPS** as the source of the methodology. This port is archived at https://doi.org/10.5281/zenodo.23574623 and should not be
cited in its place. See [`CITATION.cff`](CITATION.cff).

Relevant methodology papers, cited in the code where their constants are used:

- Holroyd, E. W. (1987), *J. Atmos. Oceanic Technol.* **4**, 498–511 — habit classification.
- Heymsfield, A. J., & Parrish, J. L. (1978), *J. Appl. Meteor.* **17**, 1566 — sample volume and
  the two-chord circle fit.
- Heymsfield, A. J., & Parrish, J. L. (1979), *NCAR/TN-137+IA* — the `sa_method=2` sample-area
  correction's 0.72×D_max coefficient (`sample_area.py`), attributed here rather than to the 1978
  paper above per McFarquhar et al. (2017, Eqs. 11-7/11-8), read directly. A separate document by
  the same two authors a year apart, not a duplicate citation.
- Korolev, A. (2007), *J. Atmos. Oceanic Technol.* **24**, 376–389 — out-of-focus sizing.
- Finlon, J. A., et al. (2016), *J. Appl. Meteor. Climatol.* **55**, 2549–2574,
  doi:10.1175/JAMC-D-16-0059.1 — UIOOPS validation.

## SODA-2 (NCAR) — a second upstream, under a different licence

`arrayprobe_soda2` reproduces part of **SODA-2**, the System for OAP Data Analysis, written in
IDL at NCAR. It is a **separate upstream from UIOOPS**, with different authors and a different
licence, and nothing about it is folded into the UIOOPS attribution above.

> Copyright © 2016 **University Corporation for Atmospheric Research (UCAR)**. All rights
> reserved. Developed by NCAR's Mesoscale and Microscale Meteorology Laboratory,
> <https://www.mmm.ucar.edu/>. Principal author **Aaron Bansemer**.

Licensed under the **3-clause BSD licence**. The full text is retained verbatim, as clause 1
requires, in SODA-2's own repository
(<https://github.com/abansemer/soda2/blob/master/LICENSE.txt>); no SODA-2 source is
redistributed in any of this project's packages, so the notice below, together with the same notice in each reproducing module's docstring, is
what carries clause 1. This reproduction is distributed under the same 3-clause BSD licence
(`LICENSE`), with UCAR's notice retained verbatim in `LICENSES/BSD-3-Clause.txt`; each
reproducing module's header names that file.

- Source: <https://github.com/abansemer/soda2>
- Citation, as SODA-2's author provided it (2026-10-06): Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418
- The Python modules are **from-source reimplementations**, not translations of copied text; each
  carries the UCAR notice in its own docstring beside the routine it reproduces.
- **Not a SODA-2 release.** Findings about SODA-2 are kept in their own register
  and are **never** merged into the UIOOPS findings count.
- **SODA-2 is a cross-check, never an oracle for a UIOOPS port.** An independent chain agreeing is
  evidence about the physics; only UIOOPS-written output adjudicates a UIOOPS reproduction.

Cite **SODA-2** for any result derived from `arrayprobe_soda2`, alongside UIOOPS for the rest.

## Third-party components

This package distributes no upstream source code and no upstream data. It translates two
upstream code bases, each obtained from its own maintainers:

| Upstream | What the package translates from it | Licence |
|---|---|---|
| UIOOPS v3.5 | The current UIOOPS release, including its `CGAL_*` MEX sources, translated by the UIOOPS engine (`arrayprobe_uiops`) | GPLv3 |
| SODA-2 | NCAR's IDL chain, translated by the SODA-2 engine — see the section above | 3-clause BSD, UCAR |

An earlier translation of UIOOPS v3.1.4, not part of this package, reproduced archived
products. The package runs without any upstream source. To check the translation against the original sources,
`scripts/fetch_upstream.py` downloads each tree at its pinned commit from the maintainers'
repository and verifies every file against a tracked SHA-256 manifest.

## NCAR Process2D (Apache-2.0) -- one opt-in enhancement

`enhancements_uiops/src/arrayprobe_enhancements/field2006_shatter.py` (the Field et al. 2006
per-second inter-arrival fit) is derived from NCAR `aircraft_oap`
`process2d/process2d.cpp`, licensed under the **Apache License 2.0** (NCAR). Each function
cites the `process2d.cpp` lines it transcribes. The derived module is distributed under the
3-clause BSD licence (`LICENSE`), as Apache-2.0 section 4 permits for a
derivative work, with Apache-2.0's conditions kept for what it transcribes: the licence text
ships as `LICENSES/Apache-2.0.txt` in the distribution that carries the module, this credit to NCAR is retained, and the module states that
it is derived and changed. Its header reads `BSD-3-Clause AND Apache-2.0`. It is opt-in, outside every engine, and not
affiliated with or endorsed by NCAR.

`Miniball.hpp`, referenced by the upstream `CGAL_minR`, is by Bernd Gärtner. This port does not
use it: the smallest-enclosing-circle geometry was independently reimplemented in Python
(`arrayprobe/geometry/`), and no third-party geometry code was copied.

## Full text: BSD-3-Clause, with UCAR's notice for SODA-2

Reproduced byte-for-byte; SODA-2's clause 1 requires the notice to be retained.

```text
SODA-2 licence notice, retained

arrayprobe is under the 3-clause BSD licence in LICENSE. The modules that reproduce
SODA-2 (src/arrayprobe_soda2/ and enhancements_soda2/src/) also carry the notice
below, which SODA-2's clause 1 requires to be retained. The module derived from NCAR
Process2D (enhancements_uiops/src/arrayprobe_enhancements/field2006_shatter.py) is
also subject to the Apache License 2.0 (LICENSES/Apache-2.0.txt).

========================================================================
SODA-2, the original these modules reproduce. Its notice, conditions and
disclaimer are retained verbatim, as its clause 1 requires.
========================================================================

License: System for OAP (optical array probe) Data Analysis

Copyright © 2016 University Corporation for Atmospheric Research (UCAR). 
All rights reserved.

Developed by NCAR's Mesoscale and Microscale Meteorology Laboratory
https://www.mmm.ucar.edu/

Redistribution and use in source and binary forms, with or without 
modification, are permitted provided that the following conditions are 
met:

1. Redistributions of source code must retain the above copyright 
notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright 
notice, this list of conditions and the following disclaimer in the 
documentation and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its 
contributors may be used to endorse or promote products derived from 
this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS 
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT 
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR 
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT 
HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, 
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT 
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, 
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY 
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT 
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE 
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```
