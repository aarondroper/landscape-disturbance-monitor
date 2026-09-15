# Methodology

## Study design and data source

Landscape Disturbance Monitor examines the 2018 Kårböle/Ljusdal wildfire
landscape in Hälsingland, Sweden. The analysis uses Copernicus Sentinel-2
Level-2A imagery discovered through the Element 84 Earth Search STAC API.
Annual observations cover August 1–31 for 2017–2026.

The workflow reads only the source windows intersecting the study area from
remote Cloud Optimized GeoTIFFs. It does not download complete Sentinel-2
scenes or maintain a local raw-imagery cache.

## Analysis grid

Analytical products use one consistent north-up grid in EPSG:32633 at 20 m
resolution. The snapped bounds are `[506260, 6858580, 531580, 6883240]`
metres, with dimensions `1266 × 1233`. A pixel represents 0.04 ha.

Using one grid for every annual composite keeps masks, indices, disturbance
labels, recovery rasters, and later delivery products pixel-aligned.

## Scene selection and annual compositing

STAC Items are grouped by UTC calendar date. Items from the same date and
pass are mosaicked in deterministic `(MGRS tile, Item ID)` order; the first
valid pixel wins rather than averaging overlapping valid pixels. Raster
scale/offset metadata is applied before index calculation.

SCL classes `0, 1, 3, 8, 9, 10, 11` are invalid. Scene-level cloud cover is
retained as metadata but is not used as a pixel mask.

Annual NBR and NDVI composites use an exact temporal median of valid August
observations. Processing is sequential and memory-bounded: AOI-only,
per-acquisition index rasters are reduced in 256 × 256 blocks rather than
holding a complete temporal stack in memory. The one-year builder is the
analytical primitive; the batch command adds explicit-year validation,
sequential execution, resumability, and post-build checks.

## Reflectance validity

Sentinel-2 Level-2A scale and offset metadata is honored before normalized
indices are calculated. Negative scaled reflectance can occur in later
processing baselines. Diagnostic comparisons showed that preserving those
values can produce pathological normalized differences, while clamping them
to zero introduces artificial saturation. The production NBR/NDVI rule
therefore rejects negative scaled reflectance, finite-invalid values, and
zero denominators.

The historical `PRESERVE` and `CLAMP_ZERO` treatments remain available only
for diagnostics and do not define production outputs.

## Spectral indices

NBR is the primary analytical index:

```text
NBR = (NIR - SWIR2) / (NIR + SWIR2)
```

NDVI is calculated as secondary contextual information:

```text
NDVI = (NIR - Red) / (NIR + Red)
```

No NDVI-based recovery percentage is produced.

## Disturbance detection

Major detected vegetation disturbance is defined by the project-specific rule:

```text
NBR_2017 > 0.30
AND
dNBR = NBR_2017 - NBR_2018 >= 0.30
```

Candidate pixels are retained as 8-neighbour connected components with an
area of at least 5 ha, or 125 pixels at 20 m resolution. No opening, closing,
dilation, erosion, hole filling, or manual polygon merging is applied.

The current rule retains 80 project-derived disturbance objects covering
approximately 6,808 ha. These are detected spectral disturbance areas, not an
authoritative wildfire perimeter or a burn-severity classification. The
August comparison can also contain phenology, illumination, land-cover,
masking, and other non-fire change.

## Spectral recovery

For each retained disturbance pixel and year, spectral recovery relative to
the 2017 NBR baseline is:

```text
R_y = (NBR_y - NBR_2018) / (NBR_2017 - NBR_2018)
```

Values are intentionally unbounded:

- `0` is approximately the 2018 spectral state;
- `1` is the 2017 NBR baseline;
- values above `1` exceed that spectral baseline;
- values below `0` are below the 2018 spectral state.

This is spectral recovery, not ecological recovery, biomass recovery, or a
restored-equivalence measure. Missing annual pixels remain missing; they are
not interpolated or spatially filled.

## Coverage QA

Object-year observations are classified by the fraction of retained object
pixels with valid NBR:

| Status | Valid fraction | Interpretation |
|---|---:|---|
| `GOOD` | `>= 0.95` | Suitable for straightforward recovery reporting |
| `USABLE_WITH_COVERAGE_FLAG` | `>= 0.80` and `< 0.95` | Available with an explicit coverage flag |
| `POOR` | `< 0.80` | Available, but unsuitable for straightforward recovery reporting |

Poor-coverage observations remain in the analytical outputs so that missingness
is visible rather than silently discarded.

## RGB imagery

Natural-color imagery uses a separate 10 m source/presentation workflow. It
does not replace the 20 m analytical NBR, NDVI, disturbance, or recovery
products. Benchmark years are 2017, 2018, 2020, 2023, and 2026.

All benchmark years use the same display transform: black point `0.01`, white
point `0.22`, and gamma `1.0`. Negative RGB reflectance is clamped only in
this visualization path; analytical index validity remains governed by the
production rejection rule. The later-year 2023 and 2026 imagery has lower
source RGB signal and can appear darker under the shared treatment.

## Browser products

The local pipeline produces the generated package consumed by the frontend:

- disturbance geometry in WGS84 GeoJSON;
- disturbance summaries and annual time-series JSON;
- annual NBR COGs;
- annual spectral-recovery COGs;
- the fixed 2017→2018 dNBR COG; and
- benchmark-year RGB imagery COGs.

Browser derivatives are reprojected to EPSG:3857 and validated before
delivery. The generated package is reproducible and intentionally ignored by
Git.

## Limitations

The result is a fixed August case-study analysis of the 2017→2018 spectral
disturbance, not continuous or operational monitoring. Disturbance objects
are project-derived detections, not causal fire boundaries. Coverage varies
by year and object, and Sentinel-2 spectral measures are proxies rather than
direct measurements of ecological condition.
