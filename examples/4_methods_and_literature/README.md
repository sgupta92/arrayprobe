# 4. Methods and literature

**What it is for.** The published methods the processing follows, each shown on small
synthetic cases where the right answer is known, so you can see what a convention does before
you choose one.

**Who it is for.** Readers who want to know why the numbers come out as they do, and authors
who must state their conventions in a paper.

**Order.** The notebooks are independent.

1. `01_enclosing_circle_conventions`: three ways to draw the circle around a particle, and the size bias of each.
2. `02_sample_area_conventions`: centre-in, all-in and reconstruction-width sample areas, and the concentration each gives.

**What you need.** Found by reading the code cells of the two notebooks. `01` imports
only the v3.5 engine's `min_circle` module; `02` imports nothing beyond numpy and matplotlib.
Both use fixed-seed synthetic particles built in the notebook:
no real data, no file you supply, no network.
