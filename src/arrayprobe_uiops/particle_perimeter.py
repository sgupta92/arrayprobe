# SPDX-License-Identifier: BSD-3-Clause
"""Single-particle image perimeter (boundary pixel count).

Ported from: ParticlePerimeter.m (UIOOPS v3.1.4)
"""

#: Declared so the public surface is explicit rather than whatever happens not to
#: start with an underscore. The Phase-1 shims at ``<name>.py`` in the original flat layout import
#: these names directly, CONSTANTS INCLUDED -- omitting a constant here would not
#: break them, but omitting one from a shim does, which is why they are listed.
__all__ = [
    "SHADOWED",
    "BACKGROUND",
    "particle_perimeter",
    "particle_perimeter_setbased",
    "particle_perimeter_from_mask",
]

SHADOWED = 48   # ASCII '0': an illuminated-diode / shadowed pixel
BACKGROUND = 49  # ASCII '1': background, also used for the padded border


def particle_perimeter(image_buffer):
    """Faithful port of ParticlePerimeter.m.

    image_buffer: 2D sequence of ASCII codes (int), where SHADOWED (48)
    marks a shadowed pixel and any other value is background.

    Perimeter = count of shadowed pixels with at least one 4-connected
    non-shadowed neighbor (the image is implicitly padded with
    BACKGROUND on all sides, matching the original's `c1` padding).

    "Any other value is background" is the original's behaviour, not an
    interpretation of it: ParticlePerimeter.m tests `48==c1(i,j)` and
    nothing else. Checked against MATLAB's own output for a code of 50 in
    `tests/test_particle_perimeter_oracle.py`, along with the three
    degenerate shapes (0x0, 3x0, 0x5) where a transcription of the
    `2:m+1` loops can diverge silently.
    """
    m = len(image_buffer)
    n = len(image_buffer[0]) if m else 0

    padded = [[BACKGROUND] * (n + 2) for _ in range(m + 2)]
    for i in range(m):
        for j in range(n):
            padded[i + 1][j + 1] = image_buffer[i][j]

    perimeter = 0
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if padded[i][j] == SHADOWED and (
                padded[i + 1][j] != SHADOWED
                or padded[i - 1][j] != SHADOWED
                or padded[i][j + 1] != SHADOWED
                or padded[i][j - 1] != SHADOWED
            ):
                perimeter += 1
    return perimeter


def particle_perimeter_setbased(image_buffer):
    """Independent re-derivation of the same quantity, for cross-validation.

    Treats shadowed pixels as a coordinate set and counts those with at
    least one of their 4 neighbors missing from the set -- neighbors
    that fall outside the image bounds count as "missing" too, which
    reproduces the original's background-padding behavior without
    building an explicit padded array. Written independently from
    particle_perimeter() above so that the two implementations agree
    only if the underlying logic (not just the code) is correct.
    """
    m = len(image_buffer)
    n = len(image_buffer[0]) if m else 0
    shadowed = {
        (i, j)
        for i in range(m)
        for j in range(n)
        if image_buffer[i][j] == SHADOWED
    }

    perimeter = 0
    for (i, j) in shadowed:
        neighbors = ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1))
        if any(nb not in shadowed for nb in neighbors):
            perimeter += 1
    return perimeter


def particle_perimeter_from_mask(mask):
    """Convenience wrapper: mask is a 2D sequence of bool, True = shadowed.

    Source: wraps the port of ``ParticlePerimeter.m:9-22`` (UIOOPS v3.1.4)."""
    img = [[SHADOWED if v else BACKGROUND for v in row] for row in mask]
    return particle_perimeter(img)
