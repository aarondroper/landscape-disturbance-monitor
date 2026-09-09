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

This design was selected to keep memory bounded while preserving an exact
temporal median. Temporary workspaces are cleaned after the run, and final
outputs are promoted atomically after reduction and QA complete.
