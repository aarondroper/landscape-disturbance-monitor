# August NBR composite prototype

This milestone tests whether an August 2017 pre-disturbance composite and an
August 2018 post-disturbance composite produce a coherent change signal over
the provisional Kårböle/Ljusdal AOI. August was retained because the supplied
feasibility inventory confirms observations in both years and it is the
requested seasonal comparison around the 2018 fire. This is an exploratory
diagnostic, not a final disturbance method.

## Processing definition

- AOI: WGS84 `15.12, 61.86, 15.60, 62.08` (west, south, east, north).
- Date windows: `2017-08-01`–`2017-08-31` and `2018-08-01`–`2018-08-31` UTC.
- Grid: `EPSG:32633`, 20 m north-up pixels. Transformed AOI bounds were
  snapped outward to `[506260, 6858580, 531580, 6883240]` metres, producing
  width `1266`, height `1233`, and `1,541,878` AOI pixel centres. The same
  transform and dimensions are used for both years; each pixel is 0.04 ha.
- Only the source windows intersecting this grid were read from remote HTTPS
  COGs. No complete Sentinel scene or local raw-imagery cache was created.
- SCL classes `0, 1, 3, 8, 9, 10, 11` were invalidated. Scene-level cloud
  cover was not used as a pixel mask.
- Items were grouped by UTC calendar date. Within each date, all relevant
  Items were read and mosaicked in `(MGRS tile, Item ID)` order. The first
  valid pixel wins; overlapping valid pixels were not averaged. The exact
  Item IDs are preserved in `data/derived/prototype/prototype-summary.json`.
- NIR and SWIR2 were read at their source resolution and averaged onto the
  20 m grid; SCL was nearest-neighbour resampled. NBR was calculated from
  scaled reflectances as `(NIR - SWIR2) / (NIR + SWIR2)`. Negative physical
  reflectance, non-finite values, and zero denominators were treated as
  invalid. dNBR is `NBR_2017 - NBR_2018`.

## Observations and coverage

2017 used 17 Items on 9 grouped dates: Aug 1, 3, 6, 13, 16, 20, 23, 26,
and 30; 7 dates contributed at least one valid AOI pixel. Same-date SCL-valid
AOI percentages were 45.67, 64.66, 53.98, 7.22, 0.00, 24.72, 0.00, 0.00,
and 97.76%. The annual median is finite for
99.77% of AOI pixels. Valid-date counts have median 3, interquartile range
2–4, maximum 6, and 3,499 zero-count pixels.

2018 used 68 Items on 19 grouped dates: Aug 1, 3, 5, 6, 8, 10, 11, 13, 15,
16, 18, 20, 21, 23, 25, 26, 28, 30, and 31; 15 dates contributed at least one
valid AOI pixel. Same-date SCL-valid AOI percentages ranged from 0.00% to
89.91%; the full list is in the JSON report.
The annual median is finite for 99.97% of AOI pixels. Valid-date counts have
median 6, interquartile range 5–7, maximum 13, and 390 zero-count pixels.

Earth Search STAC raster metadata reported NIR and SWIR2 scale `0.0001` with
offsets `0.0` and `-0.1` across the selected Items. Those values were applied
per asset before reprojection; the two offset variants were not collapsed into
an undocumented `/10000` assumption. SCL reported no scale/offset.

## Numeric diagnostics

The finite composite NBR distributions were:

| Composite | min | p01 | p05 | median | p95 | p99 | max | mean | std |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2017 | -0.745 | 0.085 | 0.247 | 0.598 | 0.744 | 0.785 | 0.955 | 0.560 | 0.154 |
| 2018 | -0.621 | -0.263 | 0.030 | 0.493 | 0.686 | 0.739 | 0.838 | 0.440 | 0.208 |

Finite dNBR had min `-0.996`, p01 `-0.280`, p05 `-0.110`, p25 `0.021`,
median `0.077`, p75 `0.177`, p90 `0.373`, p95 `0.504`, p99 `0.749`, max
`1.295`, mean `0.120`, and standard deviation `0.188`.

Exploratory dNBR areas are shown below. These are not severity classes or a
chosen disturbance threshold.

| dNBR threshold | no baseline mask | NBR2017 > 0.2 | NBR2017 > 0.3 | NBR2017 > 0.4 |
|---:|---:|---:|---:|---:|
| >= 0.10 | 25,306.24 ha | 24,988.12 ha | 24,363.16 ha | 23,067.76 ha |
| >= 0.20 | 13,676.96 ha | 13,470.68 ha | 13,122.52 ha | 12,405.60 ha |
| >= 0.30 | 8,643.04 ha | 8,509.36 ha | 8,260.92 ha | 7,790.36 ha |
| >= 0.40 | 5,386.48 ha | 5,326.56 ha | 5,148.84 ha | 4,810.56 ha |
| >= 0.50 | 3,141.60 ha | 3,127.04 ha | 3,025.44 ha | 2,787.76 ha |

The large changes in diagnostic area under increasingly strict baseline-NBR
masks show that non-vegetated/low-NBR surfaces materially affect exploratory
area totals. No baseline mask is selected here.

## Visual QA

The dNBR quicklook shows a large, spatially coherent positive red feature in
the central-to-eastern part of the AOI. The same area is visibly lower and
more yellow in the 2018 NBR quicklook than in 2017, supporting a clean first
prototype signal. The feature is well inside the provisional rectangle, with
substantial unaffected context around it.

There is broad fine-scale texture and some blue/red background variability,
consistent with land-cover differences, illumination/seasonal effects, and
uneven cloud-screened observation counts. The 2017 count image is noticeably
patchier and has several dates with little or no valid coverage, although the
median composite is nearly complete; 2018 coverage is stronger. No obvious
cloud or cloud-shadow swaths dominate the composites, and no conspicuous
tile-edge seam is visible in the inspected quicklooks. The AOI is suitable as
a provisional case-study rectangle, but it is broader than the coherent
disturbance feature and should remain explicitly provisional.

The generated GeoTIFFs and PNGs, plus the complete provenance and statistics,
are under `data/derived/prototype/`. The GeoTIFFs are tiled and DEFLATE
compressed AOI-only analytical outputs; COG compliance is not claimed.
