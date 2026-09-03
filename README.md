# QSIPlan

[![tests](https://github.com/PennLINC/QSIPlan/actions/workflows/tests.yml/badge.svg)](https://github.com/PennLINC/QSIPlan/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/PennLINC/QSIPlan/branch/main/graph/badge.svg)](https://codecov.io/gh/PennLINC/QSIPlan)

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
## Development

Set up the pinned lint/format hooks once — they run automatically on every
commit and use the exact tool versions CI does, so nothing passes locally and
then fails in CI:

```bash
pip install -e '.[tests,dev]'
pre-commit install
```

To lint the whole tree the way CI does (or before a first commit):

```bash
pre-commit run --all-files
```

The pinned versions live in a single place, `.pre-commit-config.yaml`; bump a
`rev` there and both local hooks and CI follow.
