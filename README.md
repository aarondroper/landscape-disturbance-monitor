# Landscape Disturbance & Recovery Monitor

This repository contains the approved first three milestones plus milestone
4A for the Kårböle/Ljusdal 2018 disturbance case study. It probes Sentinel-2
STAC and remote COG feasibility, builds August 2017/2018 prototype products,
detects and filters the fixed disturbance objects, and validates one
memory-bounded annual Sentinel-2 NBR/NDVI composite. Recovery analysis and
frontend work are planned but not implemented.

## Setup

Python 3.12 or newer is required. Install the package and development tools in
a virtual environment with:

```bash
python -m pip install -e '.[dev]'
```

## Commands

Run the STAC discovery and remote-COG probe:

```bash
python -m landscape_monitor.stac_probe
```

Build the August composite and NBR/dNBR prototype outputs:

```bash
python -m landscape_monitor.build_composite_prototype
```

Build the filtered disturbance masks, polygons, diagnostics, and summary:

```bash
python -m landscape_monitor.build_disturbance
```

Build one explicit annual NBR/NDVI composite (milestone 4A):

```bash
python -m landscape_monitor.build_annual_series --year 2019
```

Run tests and lint checks:

```bash
pytest
ruff check .
```

Configuration is in [`config/project.toml`](config/project.toml). Generated
STAC inventory is written to `data/inventory/`; prototype outputs are written
to `data/derived/prototype/`, disturbance outputs to
`data/derived/disturbance/`, and milestone-4A annual outputs to
`data/derived/annual/`. Temporary date-level derived products are written
under `data/.tmp/annual/` and removed after a successful or failed run unless
explicit diagnostic retention is requested. These reproducible build
outputs are intentionally excluded from Git; see [`data/README.md`](data/README.md).
