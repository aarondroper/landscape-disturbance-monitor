"""Validate completeness and deployment inventory for the static web-delivery package."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DELIVERY_DIRECTORY = Path("data/derived/web-delivery")


@dataclass(frozen=True)
class DeliveryInventory:
    root: Path
    file_count: int
    total_bytes: int
    cog_count: int
    json_geojson_count: int
    largest_files: tuple[tuple[str, int], ...]
    missing_manifest_files: tuple[str, ...]


def _manifest_paths(root: Path) -> list[Path]:
    return sorted([*root.glob("*-manifest.json"), *root.glob("data/*-manifest.json")])


def _referenced_paths(value: Any) -> set[str]:
    paths: set[str] = set()
    if isinstance(value, dict):
        if isinstance(value.get("path"), str):
            paths.add(value["path"])
        for child in value.values():
            paths.update(_referenced_paths(child))
    elif isinstance(value, list):
        for child in value:
            paths.update(_referenced_paths(child))
    return paths


def _missing_manifest_files(root: Path) -> tuple[str, ...]:
    referenced: set[str] = set()
    for manifest in _manifest_paths(root):
        try:
            referenced.update(_referenced_paths(json.loads(manifest.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError) as error:
            referenced.add(f"{manifest.relative_to(root)} (unreadable: {error})")
    missing = {
        referenced_path
        for referenced_path in referenced
        if not referenced_path.startswith("data/derived/")
        and not (root / referenced_path).is_file()
    }
    return tuple(sorted(missing))


def inspect_delivery(
    root: Path = DEFAULT_DELIVERY_DIRECTORY, largest_count: int = 10
) -> DeliveryInventory:
    """Return a deployment-oriented inventory without changing any generated files."""

    root = root.resolve()
    files = [path for path in root.rglob("*") if path.is_file()] if root.is_dir() else []
    sizes = sorted(
        ((str(path.relative_to(root)), path.stat().st_size) for path in files),
        key=lambda item: (-item[1], item[0]),
    )
    return DeliveryInventory(
        root=root,
        file_count=len(files),
        total_bytes=sum(size for _, size in sizes),
        cog_count=sum(path.suffix.lower() in {".tif", ".tiff"} for path in files),
        json_geojson_count=sum(path.suffix.lower() in {".json", ".geojson"} for path in files),
        largest_files=tuple(sizes[:largest_count]),
        missing_manifest_files=_missing_manifest_files(root),
    )


def _format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{value} B"
        amount /= 1024
    return f"{value} B"


def report(inventory: DeliveryInventory) -> str:
    lines = [
        f"Delivery directory: {inventory.root}",
        f"File count: {inventory.file_count}",
        f"Total bytes: {inventory.total_bytes} ({_format_bytes(inventory.total_bytes)})",
        f"COG count: {inventory.cog_count}",
        f"JSON/GeoJSON count: {inventory.json_geojson_count}",
        "Largest files:",
    ]
    lines.extend(f"  {size:>12} B  {path}" for path, size in inventory.largest_files)
    lines.append("Missing files referenced by manifests:")
    lines.extend(f"  {path}" for path in inventory.missing_manifest_files)
    if not inventory.missing_manifest_files:
        lines.append("  none")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT_DELIVERY_DIRECTORY)
    args = parser.parse_args(argv)
    inventory = inspect_delivery(args.directory)
    print(report(inventory))
    return 1 if inventory.missing_manifest_files else 0


if __name__ == "__main__":
    raise SystemExit(main())
