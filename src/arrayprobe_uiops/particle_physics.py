# SPDX-License-Identifier: BSD-3-Clause
"""Single-particle area, mass, and terminal-velocity relations (UIOOPS v3.5).

Ported from: single_area.m, single_mass.m (UIOOPS v3.5, both CHANGED from
v3.1.4) and single_vt.m. ``single_vt.m`` is byte-identical between the two
versions, so ``single_vt`` below is the one translation both engines use:
``arrayprobe.particle_physics`` re-exports this object lazily
rather than carrying a second translation -- see ``arrayprobe_uiops.__init__`` and
``tests/test_v35_reuse_byte_identity.py``.

**What changed.** v3.5 added a required third argument, ``iNewHabit``, to
both ``single_area`` and ``single_mass``. It selects between two habit-code
groupings for the SAME set of area-diameter / mass-diameter power laws --
no coefficient changed, only which habit codes route to which law:

- ``i_new_habit=False`` (``iNewHabit=0``, "original Holroyd classifications"):
  byte-identical grouping to v3.1.4's single_area.m/single_mass.m.
- ``i_new_habit=True`` (``iNewHabit=1``, "modified Holroyd classifications"):
  habit ``'o'`` (Oriented) moves out of the linear/'l' bucket and into the
  irregular bucket in BOTH functions. This also makes single_area's and
  single_mass's irregular buckets agree on which codes they contain where
  they did not before -- v3.1.4's asymmetry (single_area's irregular bucket
  is ``{'i','a','s','t'}``, single_mass's is only ``{'i','a'}``) is preserved
  in both branches here exactly as measured; ``i_new_habit`` does not touch
  that asymmetry, it only touches where ``'o'`` and ``'l'`` route.

No default is given for ``i_new_habit`` -- it changes computed output, so
silently picking a side is refused, matching the project's
"no default silently picks a side" rule (see ``FidelityProfile``).

Confirmed against UIOOPS v3.5 run directly under Octave 11.3.0
(``UIOPS-v3.5/joefinlon-UIOPS-039be82/single_area.m``, ``single_mass.m``), 80 diameter/habit/
i_new_habit combinations, golden fixture
``tests/data/v35_particle_physics_octave_golden.csv``
(``tests/test_v35_particle_physics.py``).
"""

__all__ = [
    "single_area",
    "single_mass",
    "single_vt",
]

import math
from typing import Any


def single_area(diameter: Any, habit: Any, i_new_habit: Any) -> Any:
    """Particle cross-sectional area (mm^2) from diameter (cgs, cm), habit code,
    and the v3.5 habit-scheme selector.

    Direct port of v3.5's single_area.m. Unrecognized habit codes return 0.0,
    matching the original's uninitialized-`area`-stays-0 behavior.
    """
    # MATLAB's `switch char(habit)` is case-sensitive: an uppercase code matches no case and
    # returns 0. Holroyd emits lowercase except 'M' and 'C', which match nothing either way.
    habit = str(habit)
    area = 0.0

    if not i_new_habit:  # original Holroyd classifications
        if habit in ('l', 'o'):  # Linear and Oriented
            if diameter < 0.03:
                a, b = 0.0696, 1.5
            else:
                a, b = 0.0512, 1.414
            area = a * diameter ** b
        elif habit == 'h':  # Plate
            a, b = 0.65, 2.0
            area = a * diameter ** b
        elif habit in ('i', 'a', 's', 't'):  # Irregular
            a, b = 0.2285, 1.88
            area = a * diameter ** b
        elif habit == 'g':  # Graupel
            a, b = 0.5, 2.0
            area = a * diameter ** b
        elif habit == 'd':  # Dendrite
            a, b = 0.21, 1.76
            area = a * diameter ** b
    else:  # modified Holroyd classifications
        if habit == 'l':  # Linear
            if diameter < 0.03:
                a, b = 0.0696, 1.5
            else:
                a, b = 0.0512, 1.414
            area = a * diameter ** b
        elif habit == 'h':  # Plate
            a, b = 0.65, 2.0
            area = a * diameter ** b
        elif habit in ('i', 'a', 's', 't', 'o'):  # Irregular, aggregate, sphere, tiny, bad
            a, b = 0.2285, 1.88
            area = a * diameter ** b
        elif habit == 'g':  # Graupel
            a, b = 0.5, 2.0
            area = a * diameter ** b
        elif habit == 'd':  # Dendrite
            a, b = 0.21, 1.76
            area = a * diameter ** b

    return area * 100  # cgs -> mm^2, per original comment


def single_mass(diameter: Any, habit: Any, i_new_habit: Any) -> Any:
    """Particle ice water content / mass (cgs) from diameter, habit code, and
    the v3.5 habit-scheme selector.

    Direct port of v3.5's single_mass.m. Unrecognized habit codes return 0.0.
    """
    # MATLAB's `switch char(habit)` is case-sensitive: an uppercase code matches no case and
    # returns 0. Holroyd emits lowercase except 'M' and 'C', which match nothing either way.
    habit = str(habit)
    iwc = 0.0

    if not i_new_habit:  # original Holroyd classifications
        if habit in ('s', 't'):  # Sphere and Tiny
            a, b = 0.00294, 1.9
            iwc = a * diameter ** b
        elif habit in ('l', 'o'):  # Linear and Oriented
            if diameter < 0.03:
                a, b = 0.001666, 1.91
            else:
                a, b = 0.000907, 1.74
            iwc = a * diameter ** b
        elif habit == 'h':  # Plate
            a, b = 0.00739, 2.45
            iwc = a * diameter ** b
        elif habit in ('i', 'a'):  # Irregular
            a, b = 0.00294, 1.9
            iwc = a * diameter ** b
        elif habit == 'g':  # Graupel
            a, b = 0.049, 2.8
            iwc = a * diameter ** b
        elif habit == 'd':  # Dendrite
            a, b = 0.000516, 1.8
            iwc = a * diameter ** b
    else:  # modified Holroyd classifications
        if habit in ('s', 't'):  # Sphere and Tiny
            a, b = 0.00294, 1.9
            iwc = a * diameter ** b
        elif habit == 'l':  # Linear (columnar)
            if diameter < 0.03:
                a, b = 0.001666, 1.91
            else:
                a, b = 0.000907, 1.74
            iwc = a * diameter ** b
        elif habit == 'h':  # Plate
            a, b = 0.00739, 2.45
            iwc = a * diameter ** b
        elif habit in ('i', 'a', 'o'):  # Irregular, aggregate, bad/undetermined
            a, b = 0.00294, 1.9
            iwc = a * diameter ** b
        elif habit == 'g':  # Graupel
            a, b = 0.049, 2.8
            iwc = a * diameter ** b
        elif habit == 'd':  # Dendrite
            a, b = 0.000516, 1.8
            iwc = a * diameter ** b

    return iwc


def single_vt(diameter: Any, area_ratio: Any, mass: Any, pressure_hpa: Any, temp_c: Any,
              use_mitchell: Any = False) -> Any:
    """Terminal fall velocity for a single particle.

    Direct port of single_vt.m. Default method is Heymsfield & Westbrook
    (2010); pass use_mitchell=True for the Mitchell (1996) method (a
    special case of Heymsfield & Westbrook with k=0, drag C=0.6,
    epsilon=5.83).

    Units, matching the original: diameter/mass in metric (m, kg),
    pressure in hPa, temperature in Celsius.

    Note: the original hardcodes `pi=3.1415926` as a local variable
    (shadowing MATLAB's built-in, full-precision `pi`), rather than
    using the built-in constant. That literal is preserved here
    deliberately -- swapping in math.pi would be a (tiny) numerical
    behavior change from the original, not a pure translation.
    """
    g = 9.8
    pi = 3.1415926  # deliberately not math.pi -- see docstring note

    t_k = temp_c + 273.15
    p_pa = pressure_hpa * 100
    rho_a = p_pa / (287.15 * t_k)
    # Sutherland's formula for dynamic viscosity
    eta = 18.27 * (291.15 + 120) / (t_k + 120) * (t_k / 291.15) ** 1.5 / 1e6
    nu = eta / rho_a  # kinematic viscosity

    if not use_mitchell:
        # Modified Best Number, Heymsfield & Westbrook (2010), drag C=0.35, epsilon=8.0
        x = rho_a / (eta ** 2) * 8 * mass * g / (pi * area_ratio ** 0.5)
        reynolds = 16 * (math.sqrt(1 + 4 * math.sqrt(x) / 64 / math.sqrt(0.35)) - 1) ** 2
    else:
        # Modified Best Number, Mitchell (1996), drag C=0.6, epsilon=5.83
        x = rho_a / (eta ** 2) * 8 * mass * g / (pi * area_ratio)
        reynolds = 5.83 ** 2 / 4 * (
            math.sqrt(1 + 4 * math.sqrt(x) / (5.83 ** 2) / math.sqrt(0.6)) - 1) ** 2

    return nu / diameter * reynolds
