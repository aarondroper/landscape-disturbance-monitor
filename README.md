# Landscape Disturbance & Recovery Monitor

This repository contains the approved first three milestones for the
Kårböle/Ljusdal 2018 disturbance case study. It probes Sentinel-2 STAC and
remote COG feasibility, builds August 2017/2018 composites on a 20 m
EPSG:32633 grid, calculates NBR and dNBR, detects and filters disturbance
components, polygonizes the retained objects, and records sensitivity results.

Recovery analysis, later-year processing, and frontend work are not yet
implemented.

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

Run tests and lint checks:

```bash
pytest
ruff check .
```

Configuration is in [`config/project.toml`](config/project.toml). Generated
STAC inventory is written to `data/inventory/`; prototype outputs are written
to `data/derived/prototype/`, and disturbance outputs to
`data/derived/disturbance/`. These reproducible build outputs are intentionally
excluded from Git; see [`data/README.md`](data/README.md).
