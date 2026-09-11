"""Render and evaluate RGB display variants from local reflectance masters.

This module intentionally has no STAC or remote-COG path.  It consumes an
already-generated local ``rgb-reflectance.tif`` and writes only named display
variants alongside it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import rasterio
from matplotlib import pyplot as plt
from rasterio.enums import ColorInterp

from .build_rgb_imagery import (
    RGB_BLOCK_SIZE,
    VISUALIZATION_BOUNDS,
    AnalysisGrid,
    MemoryTelemetry,
    _quicklook_array,
    _read_master_block,
    _windows,
    create_alpha,
    create_visualization_grid,
    fixed_display_transform,
    validate_cog,
    validate_visualization_grid,
)
from .config import ProjectConfig, load_config

DISPLAY_VARIANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
YEARS = (2017, 2018)


def display_parameters(
    config: ProjectConfig, white_point: float | None = None
) -> dict[str, float]:
    """Return the fixed display transform, overriding only the white point."""
    values = {
        "black_point": config.rgb_black_point,
        "white_point": config.rgb_white_point if white_point is None else float(white_point),
        "gamma": config.rgb_gamma,
    }
    if values["gamma"] != 1.0:
        raise ValueError("local RGB display evaluation requires gamma = 1.0")
    if not 0 <= values["black_point"] < values["white_point"]:
        raise ValueError("display points must be ordered")
    return values


def _variant_tag(variant: str) -> str:
    if not DISPLAY_VARIANT_RE.fullmatch(variant):
        raise ValueError("display variant must contain only letters, digits, '.', '_' or '-'")
    if variant in {"canonical", "rgb-web", "rgb-reflectance"}:
        raise ValueError("canonical RGB products cannot be used as display variants")
    if variant.startswith("candidate-"):
        return "w" + variant.removeprefix("candidate-")
    return variant


def variant_paths(output_dir: Path, variant: str) -> tuple[Path, Path]:
    """Return named COG and quicklook paths without targeting canonical files."""
    tag = _variant_tag(variant)
    return output_dir / f"rgb-web-{tag}.tif", output_dir / f"rgb-quicklook-{tag}.png"


def _assert_candidate_path(path: Path, master_path: Path) -> None:
    if path.resolve() == master_path.resolve() or path.name in {
        "rgb-web.tif",
        "rgb-reflectance.tif",
    }:
        raise ValueError("display candidate cannot overwrite canonical RGB products")
    if not path.name.startswith("rgb-web-") or path.suffix.lower() != ".tif":
        raise ValueError("display candidate output must be a named rgb-web-*.tif variant")


def _assert_canonical_path(path: Path, master_path: Path) -> None:
    if path.name != "rgb-web.tif" or master_path.name != "rgb-reflectance.tif":
        raise ValueError("canonical RGB rendering requires the canonical master and output names")


def _render_master_to_path(
    master_path: Path,
    output_path: Path,
    grid: AnalysisGrid,
    *,
    black_point: float,
    white_point: float,
    gamma: float,
    telemetry: MemoryTelemetry | None = None,
) -> None:
    with rasterio.open(master_path) as master:
        validate_visualization_grid(master, grid)
        with rasterio.open(
            output_path,
            "w",
            driver="COG",
            height=grid.height,
            width=grid.width,
            count=4,
            dtype="uint8",
            crs=grid.crs,
            transform=grid.transform,
            compress="DEFLATE",
            level=6,
            blocksize=RGB_BLOCK_SIZE,
            overview_resampling="average",
            BIGTIFF="IF_SAFER",
        ) as output:
            output.colorinterp = (
                ColorInterp.red,
                ColorInterp.green,
                ColorInterp.blue,
                ColorInterp.alpha,
            )
            for window in _windows(grid):
                values = _read_master_block(master, window)
                valid = np.all(np.isfinite(values), axis=0)
                rendered = fixed_display_transform(
                    values,
                    black_point=black_point,
                    white_point=white_point,
                    gamma=gamma,
                )
                output.write(
                    np.concatenate((rendered, create_alpha(valid)[None, ...]), axis=0),
                    window=window,
                )
                del values, rendered, valid
    if telemetry is not None:
        telemetry.record("after local web COG render")


def render_master_to_cog(
    master_path: Path,
    output_path: Path,
    grid: AnalysisGrid,
    *,
    black_point: float,
    white_point: float,
    gamma: float,
    telemetry: MemoryTelemetry | None = None,
) -> dict[str, Any]:
    """Render one local float32 master into a validated RGBA COG."""
    master_path = Path(master_path)
    output_path = Path(output_path)
    _assert_candidate_path(output_path, master_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    temp_path = output_path.with_name(f".{output_path.name}.tmp")
    try:
        _render_master_to_path(
            master_path,
            temp_path,
            grid,
            black_point=black_point,
            white_point=white_point,
            gamma=gamma,
            telemetry=telemetry,
        )
        os.replace(temp_path, output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    metadata = validate_cog(output_path, grid)
    metadata.update(
        {
            "source_master": str(master_path),
            "output": str(output_path),
            "black_point": black_point,
            "white_point": white_point,
            "gamma": gamma,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "file_size_bytes": output_path.stat().st_size,
        }
    )
    return metadata


def render_master_to_canonical_cog(
    master_path: Path,
    output_path: Path,
    grid: AnalysisGrid,
    *,
    black_point: float,
    white_point: float,
    gamma: float,
    telemetry: MemoryTelemetry | None = None,
) -> dict[str, Any]:
    """Render a local master to the canonical output using explicit parameters."""
    master_path = Path(master_path)
    output_path = Path(output_path)
    _assert_canonical_path(output_path, master_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    temp_path = output_path.with_name(f".{output_path.name}.tmp")
    try:
        _render_master_to_path(
            master_path,
            temp_path,
            grid,
            black_point=black_point,
            white_point=white_point,
            gamma=gamma,
            telemetry=telemetry,
        )
        os.replace(temp_path, output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    metadata = validate_cog(output_path, grid)
    metadata.update(
        {
            "source_master": str(master_path),
            "output": str(output_path),
            "black_point": black_point,
            "white_point": white_point,
            "gamma": gamma,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "file_size_bytes": output_path.stat().st_size,
        }
    )
    return metadata


def calculate_tonal_statistics(
    rgb_reflectance: np.ndarray,
    *,
    black_point: float,
    white_point: float,
    gamma: float = 1.0,
) -> dict[str, Any]:
    """Calculate source clipping and rendered tonal statistics over valid pixels."""
    rgb = np.asarray(rgb_reflectance, dtype=np.float32)
    if rgb.ndim != 3 or rgb.shape[0] != 3:
        raise ValueError("rgb_reflectance must have shape (3, rows, columns)")
    valid = np.all(np.isfinite(rgb), axis=0)
    if not np.any(valid):
        raise ValueError("no valid RGB pixels available for tonal statistics")
    source = rgb[:, valid]
    rendered = fixed_display_transform(
        rgb, black_point=black_point, white_point=white_point, gamma=gamma
    )[:, valid]
    channels: dict[str, dict[str, float | int]] = {}
    for index, name in enumerate(("red", "green", "blue")):
        source_channel = source[index]
        rendered_channel = rendered[index].astype(np.float64)
        channels[name] = {
            "fraction_source_le_black": float(np.mean(source_channel <= black_point)),
            "fraction_source_ge_white": float(np.mean(source_channel >= white_point)),
            "fraction_rendered_eq_0": float(np.mean(rendered_channel == 0)),
            "fraction_rendered_eq_255": float(np.mean(rendered_channel == 255)),
            "rendered_p1": float(np.percentile(rendered_channel, 1)),
            "rendered_p5": float(np.percentile(rendered_channel, 5)),
            "rendered_p25": float(np.percentile(rendered_channel, 25)),
            "rendered_median": float(np.percentile(rendered_channel, 50)),
            "rendered_p75": float(np.percentile(rendered_channel, 75)),
            "rendered_p95": float(np.percentile(rendered_channel, 95)),
            "rendered_p99": float(np.percentile(rendered_channel, 99)),
            "rendered_mean": float(np.mean(rendered_channel)),
            "valid_pixel_count": int(source_channel.size),
        }
    high = source >= white_point
    low = source <= black_point
    return {
        "black_point": black_point,
        "white_point": white_point,
        "gamma": gamma,
        "valid_pixel_count": int(np.count_nonzero(valid)),
        "channels": channels,
        "fraction_any_channel_clips_high": float(np.mean(np.any(high, axis=0))),
        "fraction_all_channels_clip_high": float(np.mean(np.all(high, axis=0))),
        "fraction_any_channel_clips_low": float(np.mean(np.any(low, axis=0))),
        "fraction_all_channels_clip_low": float(np.mean(np.all(low, axis=0))),
    }


def _master_array(path: Path) -> np.ndarray:
    with rasterio.open(path) as dataset:
        values = dataset.read().astype(np.float32, copy=False)
        nodata = dataset.nodata
    if nodata is not None:
        values[values == nodata] = np.nan
    values[~np.isfinite(values)] = np.nan
    return values


def _save_rgba_figure(
    path: Path,
    panels: Sequence[tuple[str, np.ndarray]],
    *,
    columns: int,
    figsize: tuple[float, float],
) -> None:
    rows = int(np.ceil(len(panels) / columns))
    figure, axes = plt.subplots(rows, columns, figsize=figsize, squeeze=False)
    try:
        for axis, (title, rgba) in zip(axes.flat, panels, strict=False):
            axis.imshow(
                np.moveaxis(rgba[:3], 0, -1),
                origin="upper",
                alpha=rgba[3] / 255.0,
                extent=VISUALIZATION_BOUNDS,
                interpolation="nearest",
                resample=False,
                vmin=0,
                vmax=255,
            )
            axis.set_title(title)
            axis.set_aspect("equal")
            axis.set_axis_off()
        for axis in axes.flat[len(panels) :]:
            axis.set_visible(False)
        figure.tight_layout()
        figure.savefig(path, dpi=140)
    finally:
        plt.close(figure)


def _read_qa_rgba(path: Path, max_dimension: int = 1400) -> np.ndarray:
    return _quicklook_array(path, max_dimension=max_dimension)


def render_year(
    config_path: Path,
    output_root: Path,
    year: int,
    *,
    white_point: float | None = None,
    variant: str = "canonical",
) -> dict[str, Any]:
    """Render a named variant from one existing local reflectance master."""
    if year not in YEARS:
        raise ValueError(f"local display evaluation supports only {YEARS}")
    config = load_config(config_path)
    grid = create_visualization_grid(config)
    output_dir = Path(output_root) / str(year)
    master_path = output_dir / "rgb-reflectance.tif"
    if not master_path.exists():
        raise FileNotFoundError(f"local reflectance master not found: {master_path}")
    parameters = display_parameters(config, white_point)
    telemetry = MemoryTelemetry()
    if variant == "canonical":
        output_path = output_dir / "rgb-web.tif"
        quicklook_path = output_dir / "rgb-quicklook.png"
        metadata = render_master_to_canonical_cog(
            master_path, output_path, grid, telemetry=telemetry, **parameters
        )
    else:
        output_path, quicklook_path = variant_paths(output_dir, variant)
        metadata = render_master_to_cog(
            master_path, output_path, grid, telemetry=telemetry, **parameters
        )
    rgba = _read_qa_rgba(output_path)
    _save_rgba_figure(
        quicklook_path,
        [(f"{year} RGB display {parameters['white_point']:.2f}", rgba)],
        columns=1,
        figsize=(10, 8),
    )
    metadata.update(
        {
            "year": year,
            "variant": variant,
            "quicklook": str(quicklook_path),
            "peak_max_rss_mib": telemetry.peak_mib,
        }
    )
    return metadata


def build_review_artifacts(
    config_path: Path, output_root: Path, *, candidate_white_point: float = 0.22
) -> dict[str, Any]:
    """Create historical 0.30 versus production 0.22 diagnostics from local masters."""
    config = load_config(config_path)
    historical_parameters = display_parameters(config, 0.30)
    candidate_parameters = display_parameters(config, candidate_white_point)
    output_root = Path(output_root)
    stats: dict[str, Any] = {
        "historical_diagnostic": historical_parameters,
        "candidate": candidate_parameters,
        "years": {},
    }
    panels: list[tuple[str, np.ndarray]] = []
    for year in YEARS:
        output_dir = output_root / str(year)
        historical_path, _ = variant_paths(output_dir, "diagnostic-030")
        candidate_path, _ = variant_paths(output_dir, "candidate-022")
        if not historical_path.exists():
            render_year(
                config_path,
                output_root,
                year,
                white_point=0.30,
                variant="diagnostic-030",
            )
        if not candidate_path.exists():
            render_year(
                config_path,
                output_root,
                year,
                white_point=candidate_white_point,
                variant="candidate-022",
            )
        historical = _read_qa_rgba(historical_path)
        candidate = _read_qa_rgba(candidate_path)
        if historical.shape != candidate.shape:
            raise ValueError(f"historical and candidate QA shapes differ for {year}")
        _save_rgba_figure(
            output_dir / "rgb-ab-comparison.png",
            [
                ("0.01–0.30 historical diagnostic", historical),
                ("0.01–0.22 production", candidate),
            ],
            columns=2,
            figsize=(18, 8),
        )
        panels.extend(
            [
                (f"{year} · 0.01–0.30 diagnostic", historical),
                (f"{year} · 0.01–0.22 production", candidate),
            ]
        )
        master = _master_array(output_dir / "rgb-reflectance.tif")
        stats["years"][str(year)] = {
            "historical_diagnostic_0.01_0.30": calculate_tonal_statistics(
                master, **historical_parameters
            ),
            "production_0.01_0.22": calculate_tonal_statistics(
                master, **candidate_parameters
            ),
        }
    review_path = output_root / "rgb-display-comparison.png"
    _save_rgba_figure(review_path, panels, columns=2, figsize=(18, 14))
    diagnostics_path = output_root / "rgb-display-diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "comparison_image": str(review_path),
        "diagnostics": str(diagnostics_path),
        "statistics": stats,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--year", type=int, help="render one local 2017 or 2018 master")
    mode.add_argument("--compare", action="store_true", help="write local A/B review artifacts")
    parser.add_argument("--config", type=Path, default=Path("config/project.toml"))
    parser.add_argument("--output-root", type=Path, default=Path("data/derived/web-imagery"))
    parser.add_argument("--white-point", type=float, default=None)
    parser.add_argument("--output-variant", default="canonical")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.compare:
        result = build_review_artifacts(args.config, args.output_root)
        print(f"Wrote {result['comparison_image']} and {result['diagnostics']}", flush=True)
        return
    result = render_year(
        args.config,
        args.output_root,
        args.year,
        white_point=args.white_point,
        variant=args.output_variant,
    )
    print(
        f"Wrote {result['output']}; size={result['file_size_bytes']} bytes; "
        f"elapsed={result['elapsed_seconds']:.3f}s; peak RSS={result['peak_max_rss_mib']:.2f} MiB",
        flush=True,
    )


if __name__ == "__main__":
    main()
