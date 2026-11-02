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

## Full text: Apache License 2.0 (the Process2D-derived module)

Reproduced byte-for-byte as apache.org serves it.

```text

                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the union of the acting entity and all
      other entities that control, are controlled by, or are under common
      control with that entity. For the purposes of this definition,
      "control" means (i) the power, direct or indirect, to cause the
      direction or management of such entity, whether by contract or
      otherwise, or (ii) ownership of fifty percent (50%) or more of the
      outstanding shares, or (iii) beneficial ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or
          Derivative Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and
          do not modify the License. You may add Your own attribution
          notices within Derivative Works that You distribute, alongside
          or as an addendum to the NOTICE text from the Work, provided
          that such additional attribution notices cannot be construed
          as modifying the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on Your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS

   APPENDIX: How to apply the Apache License to your work.

      To apply the Apache License to your work, attach the following
      boilerplate notice, with the fields enclosed by brackets "[]"
      replaced with your own identifying information. (Don't include
      the brackets!)  The text should be enclosed in the appropriate
      comment syntax for the file format. We also recommend that a
      file or class name and description of purpose be included on the
      same "printed page" as the copyright notice for easier
      identification within third-party archives.

   Copyright [yyyy] [name of copyright owner]

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
```
