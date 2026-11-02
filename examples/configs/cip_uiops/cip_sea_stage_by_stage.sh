#!/usr/bin/env bash
# The CIP-from-SEA chain stage by stage, as measured 2026-09-17. Kept because
# docs/developer/SPEED.md cites a timing taken with it.
#
# CIP runs on UIOPS v3.5 only. This script is one working `arrayprobe run`
# call over cip_run.toml (this directory); select single stages with that
# config's [run].stages.
set -euo pipefail

# --- inputs -----------------------------------------------------------------
SEA="${SEA:?set SEA to a .sea file, e.g. <und-2016-delivery>/20160912_071830/PostProcessing/2016_09_12_07_18_30.sea}"
OUT="${OUT:?set OUT to a scratch output directory}"
PY="${PY:-./.venv/Scripts/python.exe}"      # run from the repository root
CONFIG="${CONFIG:-examples/configs/cip_uiops/cip_run.toml}"   # [run].engine = "3.5"

mkdir -p "$OUT"

# --- the chain: decode, imgproc and sizedist, on v3.5 ------------------------
# The per-stage subcommands `read-binary`, `imgproc` and `sizedist` belong to
# the v3.1.4 validation engine, which the public package does not include, so
# every stage runs through `arrayprobe run`, which builds scripts/run_flight.py's
# argv from the config ([run].engine = "3.5", stages = "234"; set stages to
# "2", "3" or "4" in a copy of the config to run one stage at a time). The raw
# file given here wins over [run].raw; outputs go to the config's [run].out.
# The config's tas_from_probe must match an airspeed file for this flight: the
# SEA decode writes no TAS sidecar. Add --chunks N for a chunked stage 3.
"$PY" -m arrayprobe run "$CONFIG" "$SEA" --yes
