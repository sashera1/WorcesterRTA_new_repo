"""Add corridor-wide route catchments outside the existing stop regions.

The original features from ``corridors_for_simple_analysis_2024.geojson`` are
copied into the output without modifying their properties or coordinates.  Six
features are appended: a 0-400 m and a 400-800 m feature for each of the
Orange, Blue, and Green corridors.

Stop membership and coordinates come from both August 2024 GTFS feeds.  New
features are clipped against the original regions and against previously added
features, then inset by 0.1 m to retain the separation expected by TomTom.

Run from the repository root with::

    python simplified_model/include_non_corridor_areas.py

Add ``--visualize`` to display the completed GeoJSON after it is generated.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from shapely.geometry import MultiPoint, Point, mapping, shape
from shapely.ops import transform, unary_union
from shapely.plotting import plot_polygon

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.toolkits.geometric_toolset import (
    project_from_deg_to_meters,
    project_from_meters_to_degrees,
)


DEFAULT_INPUT_PATH = (
    PROJECT_ROOT / "simplified_model" / "corridors_for_simple_analysis_2024.geojson"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT / "simplified_model" / "full_routes_for_tomtom_2024.geojson"
)
DEFAULT_GTFS_DIRS = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "gtfs_data_2024"
    / "gtfs_until_august_23_2024",
    PROJECT_ROOT
    / "data"
    / "raw"
    / "gtfs_data_2024"
    / "gtfs_starting_august_24_2024",
)

# These route groups match src/config.py and the 2024 aggregation model.
CORRIDOR_ROUTES = {
    "Orange": ("19", "27", "33"),
    "Blue": ("5", "12"),
    "Green": ("23", "26"),
}
DISTANCE_TIERS_METERS = (400, 800)
TOMTOM_SEPARATION_METERS = 0.1
MINIMUM_COMPONENT_AREA_SQUARE_METERS = 1.0
ORIGINAL_TIER_COLORS = {
    "0-400m": "#737373",
    "400-800m": "#d9d9d9",
}
SUPPLEMENTAL_TIER_COLORS = {
    ("Orange", "0-400m"): "#f28e2b",
    ("Orange", "400-800m"): "#ffbe7d",
    ("Blue", "0-400m"): "#4e79a7",
    ("Blue", "400-800m"): "#a0cbe8",
    ("Green", "0-400m"): "#59a14f",
    ("Green", "400-800m"): "#8cd17d",
}


def _read_csv(path: Path):
    """Yield stripped CSV rows and fail with a useful missing-file message."""
    if not path.is_file():
        raise FileNotFoundError(f"Required GTFS file does not exist: {path}")
    with path.open(encoding="utf-8-sig", newline="") as input_file:
        for row in csv.DictReader(input_file):
            yield {
                key: value.strip() if isinstance(value, str) else value
                for key, value in row.items()
            }


def load_corridor_stop_coordinates(
    gtfs_dirs: tuple[Path, ...] | list[Path],
) -> tuple[
    dict[str, set[tuple[float, float]]],
    dict[str, set[str]],
]:
    """Load every stop served by a configured corridor route in any feed.

    Coordinates are returned as ``(latitude, longitude)`` pairs.  Reading
    ``routes.txt`` lets the configured route numbers match ``route_short_name``
    even if a future feed uses different internal route IDs.
    """
    route_number_to_corridor = {
        route_number: corridor
        for corridor, route_numbers in CORRIDOR_ROUTES.items()
        for route_number in route_numbers
    }
    coordinates_by_corridor = {
        corridor: set() for corridor in CORRIDOR_ROUTES
    }
    stop_ids_by_corridor = {
        corridor: set() for corridor in CORRIDOR_ROUTES
    }

    for supplied_gtfs_dir in gtfs_dirs:
        gtfs_dir = Path(supplied_gtfs_dir).resolve()
        route_id_to_corridor: dict[str, str] = {}
        found_route_numbers: set[str] = set()
        for row in _read_csv(gtfs_dir / "routes.txt"):
            route_number = row.get("route_short_name", "")
            corridor = route_number_to_corridor.get(route_number)
            if corridor is not None:
                route_id_to_corridor[row["route_id"]] = corridor
                found_route_numbers.add(route_number)

        missing_route_numbers = set(route_number_to_corridor) - found_route_numbers
        if missing_route_numbers:
            raise ValueError(
                f"GTFS feed {gtfs_dir} is missing configured routes: "
                f"{sorted(missing_route_numbers)}"
            )

        trip_to_corridor = {
            row["trip_id"]: route_id_to_corridor[row["route_id"]]
            for row in _read_csv(gtfs_dir / "trips.txt")
            if row.get("route_id") in route_id_to_corridor
        }
        if not trip_to_corridor:
            raise ValueError(
                f"GTFS feed contains no trips for configured routes: {gtfs_dir}"
            )

        feed_stop_ids = {corridor: set() for corridor in CORRIDOR_ROUTES}
        for row in _read_csv(gtfs_dir / "stop_times.txt"):
            corridor = trip_to_corridor.get(row.get("trip_id", ""))
            if corridor is not None:
                feed_stop_ids[corridor].add(row["stop_id"])

        stop_coordinates: dict[str, tuple[float, float]] = {}
        for row in _read_csv(gtfs_dir / "stops.txt"):
            try:
                stop_coordinates[row["stop_id"]] = (
                    float(row["stop_lat"]),
                    float(row["stop_lon"]),
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    f"Invalid coordinates for stop {row.get('stop_id')!r} "
                    f"in {gtfs_dir / 'stops.txt'}"
                ) from error

        for corridor, stop_ids in feed_stop_ids.items():
            missing_stop_ids = stop_ids - set(stop_coordinates)
            if missing_stop_ids:
                raise ValueError(
                    f"GTFS feed {gtfs_dir} has stop_times without coordinates "
                    f"for {corridor}: {sorted(missing_stop_ids)}"
                )
            stop_ids_by_corridor[corridor].update(stop_ids)
            coordinates_by_corridor[corridor].update(
                stop_coordinates[stop_id] for stop_id in stop_ids
            )

    empty_corridors = [
        corridor
        for corridor, coordinates in coordinates_by_corridor.items()
        if not coordinates
    ]
    if empty_corridors:
        raise ValueError(f"No GTFS stops found for corridors: {empty_corridors}")

    return coordinates_by_corridor, stop_ids_by_corridor


def _load_source_geojson(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Source GeoJSON does not exist: {path}")
    with path.open(encoding="utf-8") as source_file:
        source = json.load(source_file)
    if source.get("type") != "FeatureCollection":
        raise ValueError(f"Source must be a GeoJSON FeatureCollection: {path}")
    if not isinstance(source.get("features"), list) or not source["features"]:
        raise ValueError(f"Source GeoJSON contains no features: {path}")
    return source


def _source_coverage_meters(features: list[dict]):
    geometries = []
    for feature_index, feature in enumerate(features):
        geometry_data = feature.get("geometry")
        if geometry_data is None:
            continue
        geometry = shape(geometry_data)
        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(
                f"Source feature {feature_index} is not polygonal: "
                f"{geometry.geom_type}"
            )
        if not geometry.is_valid:
            raise ValueError(f"Source feature {feature_index} has invalid geometry")
        geometries.append(
            transform(project_from_deg_to_meters, geometry)
        )
    if not geometries:
        raise ValueError("Source GeoJSON has no nonempty polygon geometries")
    return unary_union(geometries)


def _corridor_tier_candidates(
    coordinates_by_corridor: dict[str, set[tuple[float, float]]],
) -> dict[tuple[str, str], object]:
    """Build each corridor's complete inner union and outer unioned band."""
    inner_distance, outer_distance = DISTANCE_TIERS_METERS
    candidates = {}
    for corridor in CORRIDOR_ROUTES:
        coordinates = sorted(coordinates_by_corridor[corridor])
        points_degrees = MultiPoint([
            Point(longitude, latitude)
            for latitude, longitude in coordinates
        ])
        points_meters = transform(project_from_deg_to_meters, points_degrees)
        inner_union = unary_union([
            point.buffer(inner_distance) for point in points_meters.geoms
        ])
        outer_union = unary_union([
            point.buffer(outer_distance) for point in points_meters.geoms
        ])
        candidates[(corridor, f"0-{inner_distance}m")] = inner_union
        candidates[(corridor, f"{inner_distance}-{outer_distance}m")] = (
            outer_union.difference(inner_union)
        )
    return candidates


def _supplemental_features(
    candidates: dict[tuple[str, str], object],
    original_coverage,
) -> list[dict]:
    """Create six mutually exclusive additions with near tiers taking priority."""
    tier_order = ("0-400m", "400-800m")
    occupied = original_coverage
    features = []

    # All inner tiers are assigned before any outer tier.  Within a tier, the
    # stable corridor order above resolves the very small places where raw
    # route buffers from different corridors meet.
    for tier_label in tier_order:
        for corridor in CORRIDOR_ROUTES:
            geometry = candidates[(corridor, tier_label)].difference(occupied)
            geometry = geometry.buffer(-TOMTOM_SEPARATION_METERS)
            polygon_parts = (
                list(geometry.geoms)
                if geometry.geom_type == "MultiPolygon"
                else [geometry]
            )
            geometry = unary_union([
                polygon
                for polygon in polygon_parts
                if polygon.area >= MINIMUM_COMPONENT_AREA_SQUARE_METERS
            ])
            if geometry.is_empty:
                raise ValueError(
                    f"Supplemental region is empty: {corridor} {tier_label}"
                )
            if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
                raise ValueError(
                    f"Supplemental region is not polygonal: {corridor} "
                    f"{tier_label} ({geometry.geom_type})"
                )
            if not geometry.is_valid:
                raise ValueError(
                    f"Supplemental region is invalid: {corridor} {tier_label}"
                )

            geometry_degrees = transform(
                project_from_meters_to_degrees, geometry
            )
            if not geometry_degrees.is_valid:
                geometry_degrees = geometry_degrees.buffer(0)
            if (
                geometry_degrees.is_empty
                or geometry_degrees.geom_type not in {"Polygon", "MultiPolygon"}
                or not geometry_degrees.is_valid
            ):
                raise ValueError(
                    f"Could not export a valid supplemental region: "
                    f"{corridor} {tier_label}"
                )
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "stop_id": f"NON_CORRIDOR_{corridor.upper()}",
                        "corridor": corridor,
                        "tier": tier_label,
                        "range": tier_label,
                        "name": f"{corridor}_{tier_label}",
                        "region_type": "non_corridor_route_area",
                    },
                    "geometry": mapping(geometry_degrees),
                }
            )
            occupied = unary_union([occupied, geometry])

    return features


def create_full_routes_geojson(
    input_path: str | Path = DEFAULT_INPUT_PATH,
    gtfs_dirs: tuple[str | Path, ...] | list[str | Path] = DEFAULT_GTFS_DIRS,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
) -> dict:
    """Preserve the source regions and append six corridor-level regions."""
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    resolved_gtfs_dirs = tuple(Path(path).resolve() for path in gtfs_dirs)

    source = _load_source_geojson(input_path)
    original_features = source["features"]
    original_coverage = _source_coverage_meters(original_features)
    coordinates_by_corridor, stop_ids_by_corridor = (
        load_corridor_stop_coordinates(resolved_gtfs_dirs)
    )
    candidates = _corridor_tier_candidates(coordinates_by_corridor)
    supplemental_features = _supplemental_features(
        candidates, original_coverage
    )
    if len(supplemental_features) != 6:
        raise AssertionError(
            f"Expected exactly 6 supplemental regions, got "
            f"{len(supplemental_features)}"
        )

    metadata = dict(source.get("metadata", {}))
    metadata.update(
        {
            "corridor_routes": {
                corridor: list(routes)
                for corridor, routes in CORRIDOR_ROUTES.items()
            },
            "supplemental_distance_tiers_used": list(DISTANCE_TIERS_METERS),
            "supplemental_stop_counts": {
                corridor: len(stop_ids_by_corridor[corridor])
                for corridor in CORRIDOR_ROUTES
            },
            "supplemental_gtfs_sources": [
                str(path.relative_to(PROJECT_ROOT))
                if path.is_relative_to(PROJECT_ROOT)
                else str(path)
                for path in resolved_gtfs_dirs
            ],
            "supplemental_region_count": len(supplemental_features),
            "original_region_count": len(original_features),
            "tomtom_separation_meters": TOMTOM_SEPARATION_METERS,
            "minimum_supplemental_component_area_square_meters": (
                MINIMUM_COMPONENT_AREA_SQUARE_METERS
            ),
            "total_regions": len(original_features) + len(supplemental_features),
        }
    )

    # Reuse the loaded feature dictionaries directly.  Only the six new
    # features are transformed, so every original coordinate/property value is
    # preserved exactly in the new JSON document.
    output = {
        key: value
        for key, value in source.items()
        if key not in {"metadata", "features"}
    }
    output["metadata"] = metadata
    output["features"] = [*original_features, *supplemental_features]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output_file:
        json.dump(output, output_file, indent=2)
    return output


def visualize_geojson(
    geojson_path: str | Path = DEFAULT_OUTPUT_PATH,
):
    """Display preserved stop regions and corridor-wide additions on one map."""
    geojson_path = Path(geojson_path).resolve()
    geojson = _load_source_geojson(geojson_path)
    figure, axis = plt.subplots(figsize=(13, 9))
    original_tiers = set()
    supplemental_regions = set()

    for feature_index, feature in enumerate(geojson["features"]):
        geometry_data = feature.get("geometry")
        if geometry_data is None:
            continue
        geometry = shape(geometry_data)
        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(
                f"Feature {feature_index} is not polygonal: "
                f"{geometry.geom_type}"
            )

        properties = feature.get("properties", {})
        tier = properties.get("range", properties.get("tier", "unknown"))
        if properties.get("region_type") == "non_corridor_route_area":
            corridor = properties.get("corridor", "unknown")
            region_key = (corridor, tier)
            supplemental_regions.add(region_key)
            face_color = SUPPLEMENTAL_TIER_COLORS.get(
                region_key, "#bdbdbd"
            )
            edge_color = "#202020"
            line_width = 0.35
            alpha = 0.8
        else:
            original_tiers.add(tier)
            face_color = ORIGINAL_TIER_COLORS.get(tier, "#bdbdbd")
            edge_color = "#666666"
            line_width = 0.15
            alpha = 0.72

        plot_polygon(
            geometry,
            ax=axis,
            add_points=False,
            facecolor=face_color,
            edgecolor=edge_color,
            linewidth=line_width,
            alpha=alpha,
        )

    legend_handles = [
        Patch(
            facecolor=ORIGINAL_TIER_COLORS.get(tier, "#bdbdbd"),
            edgecolor="#666666",
            label=f"Existing {tier}",
        )
        for tier in ("0-400m", "400-800m")
        if tier in original_tiers
    ]
    legend_handles.extend(
        Patch(
            facecolor=SUPPLEMENTAL_TIER_COLORS[(corridor, tier)],
            edgecolor="#202020",
            label=f"{corridor} {tier}",
        )
        for corridor in CORRIDOR_ROUTES
        for tier in ("0-400m", "400-800m")
        if (corridor, tier) in supplemental_regions
    )

    axis.autoscale_view()
    axis.set_aspect(1.35)
    axis.set_xlabel("Longitude")
    axis.set_ylabel("Latitude")
    axis.set_title("2024 Full-Route Corridor Regions for TomTom")
    axis.grid(True, linestyle="--", alpha=0.25)
    if legend_handles:
        axis.legend(handles=legend_handles, loc="best", ncols=2)
    figure.tight_layout()
    plt.show()
    return figure, axis


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Append six mutually exclusive full-route corridor regions to the "
            "existing 2024 stop-region GeoJSON."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"Source corridor GeoJSON (default: {DEFAULT_INPUT_PATH})",
    )
    parser.add_argument(
        "--gtfs-dir",
        type=Path,
        action="append",
        dest="gtfs_dirs",
        help=(
            "2024 GTFS directory; repeat to use multiple feeds. "
            "Defaults to both August 2024 feeds."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Output GeoJSON (default: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Display the completed GeoJSON after writing it.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gtfs_dirs = tuple(args.gtfs_dirs) if args.gtfs_dirs else DEFAULT_GTFS_DIRS
    output = create_full_routes_geojson(
        input_path=args.input,
        gtfs_dirs=gtfs_dirs,
        output_path=args.output,
    )
    print(
        f"Wrote {output['metadata']['total_regions']} regions "
        f"({output['metadata']['supplemental_region_count']} supplemental) "
        f"to {args.output.resolve()}"
    )
    if args.visualize:
        visualize_geojson(args.output)


if __name__ == "__main__":
    main()
    #visualize_geojson("simplified_model/full_routes_for_tomtom_2024.geojson")
