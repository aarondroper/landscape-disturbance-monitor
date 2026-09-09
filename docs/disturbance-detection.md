# Operational disturbance detection

This milestone converts the validated August 2017/2018 NBR change rasters into
reproducible disturbance objects. It produces analytical rasters and a WGS84
GeoJSON for later application use. Recovery, disturbance year, causal
attribution, and frontend work are outside this milestone.

## Interpretation

**Observation.** The prototype shows a large coherent positive dNBR feature in
the central/eastern part of the provisional Kårböle/Ljusdal AOI, with reduced
2018 NBR in the same area. The source composites and masks are described in
`docs/composite-prototype.md`.

**Operational rule.** A candidate pixel is retained when the aligned prototype
rasters satisfy:

```text
NBR_2017 > 0.30 AND dNBR_2017_2018 >= 0.30
```

Only 8-neighbour connected components of at least `5.0 ha` are retained. At
20 m resolution, one pixel is `0.04 ha`, so the minimum is 125 pixels. These
values are explicit configuration in `[disturbance]` in
`config/project.toml`; the workflow uses thresholding and connected-component
filtering only. It does not apply opening, closing, dilation, erosion, hole
filling, or manual polygon merging.

The NBR baseline guard is used to focus the project-specific rule on pixels
that had substantial vegetation signal before the change. The dNBR threshold
is used here because it isolates the strong, spatially coherent decrease seen
in this case-study comparison. Neither value is a universal burn-severity
threshold. No low/moderate/high severity classes are produced.

**Interpretation.** The output should be described as **major detected
vegetation disturbance**. In this known case study, the principal coherent
feature is consistent with the 2018 wildfire context, but detected raster
change is not automatic causal attribution and every polygon is not
necessarily wildfire.

## Outputs and diagnostics

The build command is:

```bash
python -m landscape_monitor.build_disturbance
```

It consumes the existing `data/derived/prototype/` rasters without re-querying
STAC or recomputing Sentinel-2 composites. It writes:

- `data/derived/disturbance/disturbance_mask.tif`
- `data/derived/disturbance/disturbance_labels.tif`
- `data/derived/disturbance/disturbances.geojson` in EPSG:4326
- `data/derived/disturbance/disturbance-summary.json`
- four analytical QA PNGs for the candidate mask, retained mask, dNBR
  boundaries, and 2018 NBR boundaries

Object IDs are deterministic: retained components are ordered by descending
area, then centroid easting, centroid northing, and a final raw-label tie
breaker. The summary records object statistics calculated from the pixels of
each retained label, not polygon bounding boxes. AOI-boundary-touching means
that a labelled pixel is adjacent to the rasterized analysis-AOI boundary;
such objects may be truncated.

## Results

The default rule produced 206,523 raw candidate pixels (`8,260.92 ha`,
13.4281% of the 61,519.56 ha valid analysis area). There were 6,137 raw
components. The 5 ha / 125-pixel filter retained 80 components and 170,206
pixels (`6,808.24 ha`, 11.0668% of valid analysis area), removing 6,057
components and `1,452.68 ha`. The largest retained component is
`disturbance-001` at `2,406.48 ha`; the median retained component is `9.44
ha`. Two retained components touch the analysis-AOI boundary:
`disturbance-004` (`295.76 ha`) and `disturbance-055` (`6.96 ha`).

The largest objects have the following core pixel statistics:

| ID | area (ha) | NBR2017 mean | NBR2018 mean | dNBR mean | dNBR p90 | dNBR max |
|---|---:|---:|---:|---:|---:|---:|
| disturbance-001 | 2,406.48 | 0.5831 | 0.0892 | 0.4939 | 0.6742 | 1.2019 |
| disturbance-002 | 2,316.48 | 0.5816 | 0.0190 | 0.5626 | 0.8210 | 1.2945 |
| disturbance-003 | 450.92 | 0.6061 | 0.0539 | 0.5522 | 0.8021 | 1.2668 |
| disturbance-004 | 295.76 | 0.6910 | 0.2588 | 0.4322 | 0.5518 | 0.9208 |
| disturbance-005 | 213.56 | 0.5611 | 0.0388 | 0.5223 | 0.7251 | 0.9748 |

The GeoJSON contains 80 WGS84 features, is 4,904,620 bytes, and contains
54,035 coordinate positions. Evaluated in the analysis CRS, its polygons cover
exactly `68,082,400 m²`, equal to the retained raster pixel area. A separate
WGS84-roundtrip check differed by only `12.65 m²` (`1.9e-7` relative), due to
coordinate rounding.

The requested one-dimensional sensitivities were:

| dNBR minimum | raw area (ha) | retained area (ha) | retained components | largest (ha) |
|---:|---:|---:|---:|---:|
| 0.25 | 10,370.00 | 8,542.20 | 91 | 6,131.76 |
| 0.30 | 8,260.92 | 6,808.24 | 80 | 2,406.48 |
| 0.35 | 6,567.84 | 5,448.80 | 59 | 2,005.64 |
| 0.40 | 5,148.84 | 4,274.56 | 58 | 1,358.72 |

| baseline NBR minimum | raw area (ha) | retained area (ha) | retained components | largest (ha) |
|---:|---:|---:|---:|---:|
| 0.20 | 8,509.36 | 7,060.52 | 78 | 2,713.92 |
| 0.30 | 8,260.92 | 6,808.24 | 80 | 2,406.48 |
| 0.40 | 7,790.36 | 6,358.00 | 85 | 2,258.88 |

| minimum patch (ha) | retained area (ha) | retained components | largest (ha) |
|---:|---:|---:|---:|
| 1 | 7,463.16 | 406 | 2,406.48 |
| 2 | 7,184.24 | 204 | 2,406.48 |
| 5 | 6,808.24 | 80 | 2,406.48 |
| 10 | 6,519.84 | 38 | 2,406.48 |

The QA images show that the main coherent positive dNBR feature remains
intact after filtering, while isolated fine speckle is substantially reduced.
The result still contains many secondary patches elsewhere and the main
feature is visibly fragmented into multiple retained components, with jagged
boundaries and internal unclassified gaps. Those gaps were not filled or
smoothed; they appear as the direct raster threshold result and should be
reviewed before any later boundary-cleanup decision. No obvious MGRS tile-edge
seam became apparent in the inspected candidate, retained-mask, dNBR-overlay,
or 2018-NBR-overlay images. The two boundary-touching objects are flagged in
the object properties and should be treated as potentially truncated.

The default `0.30 / 0.30 / 5.0 ha` rule is suitable to retain as the initial
operational rule for this case study because it preserves the central coherent
signal while removing most small components, but the sensitivity and visible
fragmentation show that it is not a final causal perimeter.

## Limitations

The comparison is an August 2017 versus August 2018 seasonal composite and
can contain phenology, illumination, land-cover, residual masking, and other
non-fire change. A minimum patch threshold removes small components but does
not make a component causal or fire-specific. The provisional rectangular
AOI and boundary-truncated components require care in later interpretation.
The vector output is not aggressively simplified at this stage, and no final
web-optimized COGs or frontend representation are created here.
