# Security policy

`arrayprobe` processes scientific instrument files (optical-array-probe binaries and netCDF
products) and runs no network service and executes no code from its input beyond ordinary
parsing. The realistic risk surface is a malformed input file triggering a crash, an excessive
resource read, or (in principle) a parser vulnerability in a dependency — not a remote exploit.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository (Security tab → "Report
a vulnerability") rather than a public issue, so a fix can land before the report is public.

If that is not available to you, open an issue that describes the class of problem without a
working proof-of-concept, and the maintainer will follow up to get details privately.

This is a single-maintainer research project; response time is best-effort, not guaranteed.

## Supported versions

Only the latest released version is supported. There is no long-term-support branch.

## Scope

In scope: the `arrayprobe`, `arrayprobe_uiops`, `arrayprobe_soda2` and `arrayprobe-uiops-enhancements`
packages as distributed. Out of scope: the vendored, unmodified upstream sources this repository
carries for reference and differential-oracle use — different projects, different upstreams:

- `UIOPS-v3.5/` (MATLAB; report issues upstream, at
  [github.com/joefinlon/UIOPS](https://github.com/joefinlon/UIOPS))
- `SODA2/` (IDL; report issues upstream, at
  [github.com/abansemer/soda2](https://github.com/abansemer/soda2))

and third-party dependencies (report to their own maintainers; this project will take an update
once one is available).
