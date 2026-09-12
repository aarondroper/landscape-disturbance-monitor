# Sentinel-2 negative-reflectance handling evaluation

Sentinel-2 Level-2A `raster:bands` scale/offset metadata is applied before index
calculation. Valid Level-2A observations can therefore produce negative scaled
BOA reflectance over very dark surfaces; source DN nodata is identified before
that conversion and remains invalid.

Three treatments were evaluated for normalized-difference indices:

- `REJECT`: reject any negative scaled required band. This is the conservative
  production rule, with finite, nonzero denominators.
- `PRESERVE`: retain negative values for diagnostics. It restored coverage but
  made ratios numerically unstable: more than 91% of 2022 NDVI and more than
  87% of 2023 NDVI fell outside `[-1, 1]`, with extreme magnitudes.
- `CLAMP_ZERO`: replace negative values with zero for diagnostics. It kept
  indices bounded and restored roughly 97–98% full-AOI coverage, but saturated
  dark pixels artificially (disturbance-footprint NDVI medians reached 1.0).

`REJECT` is retained, so some post-2022 observations have reduced coverage.
NBR is the primary indicator for disturbance and future recovery analysis;
NDVI is secondary/contextual, and its completeness must be reported honestly.
No NDVI-based recovery percentages are used.

Sentinel-2 Processing Baseline 04.00 changed SCL class 2 toward
topographic/cast shadows; dark features moved to class 7. The production SCL
mask was not changed by this evaluation.

Canonical 2022/2023 annual outputs were not rebuilt or changed by these
diagnostics. The diagnostic commands write only under
`data/derived/diagnostics/` and do not implement recovery.
