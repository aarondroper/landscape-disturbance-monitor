# Local NBR recovery analysis

Milestone 5A calculates spectral recovery from the fixed 80-object disturbance
footprint and the complete approved annual August 2017–2026 series. It reads
only existing canonical local rasters; it does not query STAC, rebuild annual
composites, or alter disturbance detection or polygons.

NBR is the primary recovery indicator. For every retained disturbance pixel,
the calculation is performed before aggregation to objects:

```text
recovery_fraction_y = (NBR_y - NBR_2018) / (NBR_2017 - NBR_2018)
```

The 2018 value is the post-disturbance spectral benchmark and 2017 is the
pre-disturbance spectral baseline. A value near 0 is approximately the 2018
state, 0.5 is approximately halfway toward the 2017 baseline, 1 is the 2017
NBR baseline, values above 1 exceed that spectral baseline, and values below 0
are below the 2018 state. Values are not clamped or discarded. These are NBR
spectral-recovery fractions, not ecological, biomass, or restored-equivalence
percentages.

Annual pixels with missing NBR remain nodata. They are not interpolated or
spatially filled. A retained object-year is categorized by its NBR valid
fraction:

- `GOOD`: at least 0.95;
- `USABLE_WITH_COVERAGE_FLAG`: at least 0.80 and below 0.95;
- `POOR`: below 0.80.

POOR object-years remain in the analytical JSON and retain numerical statistics
when valid pixels exist, but are explicitly marked as not recommended for
equivalent reporting. Coverage and threshold fractions always distinguish
missing pixels from valid recovery pixels. NDVI is contextual only: the
analysis retains its valid fraction and median and calculates no NDVI
recovery.

## Command and outputs

```bash
python -m landscape_monitor.build_recovery
```

The command writes `data/derived/recovery/`, including one float32 analytical
recovery raster per year, `disturbance-timeseries.json`,
`recovery-summary.json`, and five QA figures. The disturbance footprint is
fixed at 170,206 pixels (6,808.24 ha) across 80 labelled objects. Later-year
coverage is incomplete at the retained-footprint level and can be much poorer
for individual object-years, so late trajectories must be read with their
coverage status. In particular, low coverage limits equivalent comparison of
some late observations, including disturbance-004 after 2021.
