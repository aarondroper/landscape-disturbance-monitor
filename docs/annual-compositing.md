# Memory-bounded annual compositing

Milestone 4A builds August Sentinel-2 NBR and NDVI composites one explicitly
selected year at a time. Each usable acquisition date is written as AOI-only,
temporary per-acquisition float32 index GeoTIFFs. The exact temporal median is
then reduced block by block using 256×256 reduction blocks, so complete
acquisition rasters are not retained in memory and no complete Sentinel scene
is downloaded.

The 2019 stress validation used 80 STAC Items grouped into 19 acquisitions.
Peak process memory was approximately 289 MiB from internal telemetry and
295,424 KiB from `/usr/bin/time -v`. Peak temporary disk usage was
approximately 52 MiB, and the validation took approximately 44 minutes in
that environment. These figures are validation observations, not guaranteed
runtime or resource requirements elsewhere.

The current local annual outputs for 2019 and 2020 both validate as complete.
The 2020 output contains 72 STAC Items grouped into 18 acquisitions, with
100% NBR and NDVI coverage; its child process peak RSS was approximately
298 MiB. These are local validation results, not a claim that the full
configured year range has been generated.

This design was selected to keep memory bounded while preserving an exact
temporal median. Temporary workspaces are cleaned after the run, and final
outputs are promoted atomically after reduction and QA complete.

## Resumable explicit-year orchestration

The one-year command remains the analytical primitive:

```bash
python -m landscape_monitor.build_annual_series --year 2019
```

Milestone 4B adds a small orchestration layer around that command. Years must
always be supplied explicitly; the batch command never expands a request to
all configured years. Duplicate requested years are sorted chronologically
and removed. For example:

```bash
python -m landscape_monitor.build_annual_batch --years 2019 2020
python -m landscape_monitor.build_annual_batch --years 2019 2020 --dry-run
```

Before processing, each `data/derived/annual/<year>/` directory is classified
from its actual files and metadata as `COMPLETE`, `MISSING`, or `INVALID`. A
complete year is validated and skipped. A missing or empty year directory is
passed to the existing single-year command. A non-empty directory with
missing, malformed, unreadable, or inconsistent outputs is `INVALID`; the
batch reports the reasons and stops without deleting or silently overwriting
it. The batch does not use its status report as the source of truth.

Required analytical completeness includes `nbr.tif`, `ndvi.tif`,
`valid_count.tif`, and a parseable `annual-summary.json`; the summary must
match the requested year and contain the established annual-build provenance.
All three rasters must be readable, single-band products on the approved
EPSG:32633, 20 m, 1266×1233 analysis grid with matching transforms and
bounds. The optional `nbr-qa.png` is not required for analytical completeness.

Years are processed strictly sequentially. Each missing year runs in a fresh
child Python process using `build_annual_series`; no annual worker pool or
annual concurrency is used. A non-zero child exit, or a post-build validation
failure, stops later years. Earlier successful outputs remain in place and
later years are recorded as `not_attempted`. Successful non-dry-run attempts
write the generated, Git-ignored `data/derived/annual/build-status.json` with
timestamps, per-year validation, child exit codes, and overall status. Dry runs
perform validation and report skip/build decisions without launching a child
or writing the status file.

## Regression check against the approved 2017/2018 prototype

On 2026-09-10, the generalized annual pipeline was run for 2017 and 2018 and
compared with the approved prototype NBR rasters. Both pairs used the identical
EPSG:32633 grid, transform, dimensions, bounds, float32 dtype, and `-9999`
nodata convention. The valid masks matched exactly. For 2017, all 1,538,379
shared valid pixels matched exactly; for 2018, all 1,541,488 shared valid
pixels matched exactly. In both comparisons, maximum, mean, and median absolute
difference and RMSE were 0.0, and the counts above 1e-6, 1e-5, 1e-4, and 1e-3
were all zero.

The annual provenance matched the prototype inventory exactly: 17 Items in 9
groups for 2017 and 68 Items in 19 groups for 2018, with identical Item sets,
grouped dates, per-date Item lists, and per-date valid-pixel counts. An earlier
generated prototype summary declared 6 and 14 usable dates, respectively,
although its per-date records contain 7 and 15 positive-validity dates. The
prototype metadata-counting logic now uses those per-date records, and the
generalized annual summaries report 7 and 15 usable dates. This metadata
inconsistency did not affect the raster regression result.

The builds remained sequential and memory-bounded. Child peak RSS was 287.88
MiB for 2017 and 288.28 MiB for 2018; peak AOI-only temporary storage was 30.179
MiB and 61.129 MiB, respectively, and both temporary workspaces were cleaned.
