# QSIPlan

[![tests](https://github.com/PennLINC/qsiplan/actions/workflows/tests.yml/badge.svg)](https://github.com/PennLINC/qsiplan/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/PennLINC/qsiplan/branch/main/graph/badge.svg)](https://codecov.io/gh/PennLINC/qsiplan)

Plan and explain [qsiprep](https://github.com/PennLINC/qsiprep)'s
diffusion-MRI preprocessing from BIDS metadata and configuration flags.

`qsiplan` groups a subject's DWI scans the way qsiprep will (distortion
groups, fieldmap estimations, correction units, outputs), validates the
data and curation (missing phase-encoding metadata, IntendedFor conflicts,
shim walls, b-value mismatches...), compiles the execution plan for any
combination of head-motion- and susceptibility-correction methods, and
renders it all as text or as a self-contained interactive HTML page:

```bash
qsiplan /path/to/bids --html grouping.html
```