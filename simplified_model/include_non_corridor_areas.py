"""Add one-tier corridor-route catchments outside the core stop regions.

The original features from the one-tier corridor GeoJSON are copied into the
output without modifying their properties or coordinates.  Three features are
appended: one 0-400 m feature for each of the Orange, Blue, and Green
corridors.

Core corridor membership comes from the consolidated 2024 stop CSVs.  Stop
membership and coordinates for the supplemental candidates come from both
August 2024 GTFS feeds, excluding every original stop represented by a
consolidated row before any buffers are constructed.  New features are clipped
against the original regions and against previously added features, then inset
by 0.1 m to retain the separation expected by TomTom.

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
    PROJECT_ROOT
    / "data"
    / "final_corrections"
    / "corridors_for_simple_analysis_2024_0_400m.geojson"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "final_corrections"
    / "full_routes_for_tomtom_2024_0_400m.geojson"
)
DEFAULT_CONSOLIDATED_STOP_DIR = (
    PROJECT_ROOT / "data" / "processed" / "stops_consolidated_data_2024"
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
DISTANCE_TIERS_METERS = (400,)
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
        raise FileNotFoundError(f"Required CSV file does not exist: {path}")
    with path.open(encoding="utf-8-sig", newline="") as input_file:
        for row in csv.DictReader(input_file):
            yield {
                key: value.strip() if isinstance(value, str) else value
                for key, value in row.items()
            }


def _normalize_distance_tiers(distance_tiers) -> tuple[int, ...]:
    tiers = tuple(sorted(set(distance_tiers)))
    if not tiers:
        raise ValueError("distance_tiers cannot be empty")
    if tiers[0] <= 0:
        raise ValueError("distance tiers must be greater than zero")
    return tiers


def _tier_labels(distance_tiers: tuple[int, ...]) -> tuple[str, ...]:
    labels = []
    inner_distance = 0
    for outer_distance in distance_tiers:
        labels.append(f"{inner_distance}-{outer_distance}m")
        inner_distance = outer_distance
    return tuple(labels)


def _tier_label_sort_key(tier_label: str) -> float:
    return float(tier_label.split("-", 1)[0])


def load_consolidated_stop_members(
    consolidated_stop_dir: str | Path,
) -> tuple[dict[str, set[str]], dict[str, set[str]], set[str]]:
    """Load representative IDs and every original stop folded into them."""
    consolidated_stop_dir = Path(consolidated_stop_dir).resolve()
    representative_ids_by_corridor = {}
    member_ids_by_corridor = {}

    for corridor in CORRIDOR_ROUTES:
        path = consolidated_stop_dir / f"{corridor}_corridor_shared_stops.csv"
        representative_ids = set()
        member_ids = set()

        for row in _read_csv(path):
            representative_id = row.get("stop_id", "")
            composite_members = {
                stop_id for stop_id in representative_id.split(";") if stop_id
            }
            structured_members = {
                row.get("inbound_stop_id", ""),
                row.get("outbound_stop_id", ""),
            } - {""}
            for field in ("extra_inbound", "extra_outbound"):
                structured_members.update(
                    stop_id
                    for stop_id in row.get(field, "").split(";")
                    if stop_id
                )

            if not representative_id or not structured_members:
                raise ValueError(f"Invalid consolidated stop row in {path}: {row}")
            if composite_members != structured_members:
                raise ValueError(
                    f"Consolidated stop membership mismatch for "
                    f"{representative_id!r} in {path}"
                )

            representative_ids.add(representative_id)
            member_ids.update(structured_members)

        if not representative_ids:
            raise ValueError(f"No consolidated stops found for {corridor}: {path}")
        representative_ids_by_corridor[corridor] = representative_ids
        member_ids_by_corridor[corridor] = member_ids

    all_member_ids = set().union(*member_ids_by_corridor.values())
    return (
        representative_ids_by_corridor,
        member_ids_by_corridor,
        all_member_ids,
    )


def load_corridor_stop_coordinates(
    gtfs_dirs: tuple[Path, ...] | list[Path],
) -> dict[str, dict[str, set[tuple[float, float]]]]:
    """Load every stop served by a configured corridor route in any feed.

    Coordinates are retained by stop ID as ``(latitude, longitude)`` pairs.
    Reading ``routes.txt`` lets the configured route numbers match
    ``route_short_name`` even if a future feed uses different internal route
    IDs.
    """
    route_number_to_corridor = {
        route_number: corridor
        for corridor, route_numbers in CORRIDOR_ROUTES.items()
        for route_number in route_numbers
    }
    stops_by_corridor = {
        corridor: {} for corridor in CORRIDOR_ROUTES
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
            for stop_id in stop_ids:
                stops_by_corridor[corridor].setdefault(stop_id, set()).add(
                    stop_coordinates[stop_id]
                )

    empty_corridors = [
        corridor
        for corridor, stops in stops_by_corridor.items()
        if not stops
    ]
    if empty_corridors:
        raise ValueError(f"No GTFS stops found for corridors: {empty_corridors}")

    return stops_by_corridor


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


def _validate_source_regions(
    source: dict,
    distance_tiers: tuple[int, ...],
    representative_ids_by_corridor: dict[str, set[str]],
) -> None:
    expected_tier_labels = set(_tier_labels(distance_tiers))
    expected_stop_ids = set().union(*representative_ids_by_corridor.values())
    expected_pairs = {
        (stop_id, tier_label)
        for stop_id in expected_stop_ids
        for tier_label in expected_tier_labels
    }
    actual_pairs = [
        (
            feature.get("properties", {}).get("stop_id"),
            feature.get("properties", {}).get("tier"),
        )
        for feature in source["features"]
    ]

    if len(actual_pairs) != len(set(actual_pairs)):
        raise ValueError("Source GeoJSON contains duplicate stop/tier features")
    if set(actual_pairs) != expected_pairs:
        actual_tiers = {tier for _, tier in actual_pairs}
        actual_stop_ids = {stop_id for stop_id, _ in actual_pairs}
        raise ValueError(
            "Source GeoJSON does not match the requested consolidated stops "
            f"and tiers; expected tiers {sorted(expected_tier_labels)}, got "
            f"{sorted(actual_tiers, key=str)}; missing stop IDs "
            f"{sorted(expected_stop_ids - actual_stop_ids)}, unexpected stop "
            f"IDs {sorted(actual_stop_ids - expected_stop_ids, key=str)}"
        )

    metadata_tiers = source.get("metadata", {}).get("distance_tiers_used")
    if metadata_tiers is not None and tuple(metadata_tiers) != distance_tiers:
        raise ValueError(
            "Source GeoJSON metadata distance tiers do not match the "
            f"requested tiers: {metadata_tiers} != {list(distance_tiers)}"
        )


def _filter_supplemental_stops(
    stops_by_corridor: dict[str, dict[str, set[tuple[float, float]]]],
    member_ids_by_corridor: dict[str, set[str]],
    all_consolidated_member_ids: set[str],
) -> tuple[
    dict[str, set[tuple[float, float]]],
    dict[str, int],
    dict[str, int],
]:
    """Exclude every stop already represented by a consolidated region."""
    coordinates_by_corridor = {}
    supplemental_stop_counts = {}
    excluded_stop_counts = {}

    for corridor in CORRIDOR_ROUTES:
        route_stops = stops_by_corridor[corridor]
        missing_member_ids = member_ids_by_corridor[corridor] - set(route_stops)
        if missing_member_ids:
            raise ValueError(
                f"Consolidated {corridor} stops are missing from the supplied "
                f"GTFS feeds: {sorted(missing_member_ids)}"
            )

        excluded_ids = set(route_stops) & all_consolidated_member_ids
        supplemental_ids = set(route_stops) - all_consolidated_member_ids
        coordinates = {
            coordinate
            for stop_id in supplemental_ids
            for coordinate in route_stops[stop_id]
        }
        if not coordinates:
            raise ValueError(
                f"No non-corridor GTFS stops remain for {corridor} after "
                "excluding consolidated members"
            )

        coordinates_by_corridor[corridor] = coordinates
        supplemental_stop_counts[corridor] = len(supplemental_ids)
        excluded_stop_counts[corridor] = len(excluded_ids)

    return (
        coordinates_by_corridor,
        supplemental_stop_counts,
        excluded_stop_counts,
    )


def _corridor_tier_candidates(
    coordinates_by_corridor: dict[str, set[tuple[float, float]]],
    distance_tiers: tuple[int, ...],
) -> dict[tuple[str, str], object]:
    """Build each corridor's complete union for every radial tier."""
    candidates = {}
    for corridor in CORRIDOR_ROUTES:
        coordinates = sorted(coordinates_by_corridor[corridor])
        points_degrees = MultiPoint([
            Point(longitude, latitude)
            for latitude, longitude in coordinates
        ])
        points_meters = transform(project_from_deg_to_meters, points_degrees)
        inner_distance = 0
        inner_union = None
        for outer_distance in distance_tiers:
            outer_union = unary_union([
                point.buffer(outer_distance) for point in points_meters.geoms
            ])
            tier_geometry = (
                outer_union
                if inner_union is None
                else outer_union.difference(inner_union)
            )
            candidates[
                (corridor, f"{inner_distance}-{outer_distance}m")
            ] = tier_geometry
            inner_distance = outer_distance
            inner_union = outer_union
    return candidates


def _supplemental_features(
    candidates: dict[tuple[str, str], object],
    original_coverage,
    distance_tiers: tuple[int, ...],
) -> list[dict]:
    """Create mutually exclusive additions with near tiers taking priority."""
    tier_order = _tier_labels(distance_tiers)
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
    consolidated_stop_dir: str | Path = DEFAULT_CONSOLIDATED_STOP_DIR,
    distance_tiers: tuple[int, ...] | list[int] = DISTANCE_TIERS_METERS,
) -> dict:
    """Preserve source regions and append filtered corridor-level regions."""
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    consolidated_stop_dir = Path(consolidated_stop_dir).resolve()
    resolved_gtfs_dirs = tuple(Path(path).resolve() for path in gtfs_dirs)
    tiers = _normalize_distance_tiers(distance_tiers)

    source = _load_source_geojson(input_path)
    original_features = source["features"]
    (
        representative_ids_by_corridor,
        member_ids_by_corridor,
        all_consolidated_member_ids,
    ) = load_consolidated_stop_members(consolidated_stop_dir)
    _validate_source_regions(
        source,
        tiers,
        representative_ids_by_corridor,
    )
    original_coverage = _source_coverage_meters(original_features)
    stops_by_corridor = load_corridor_stop_coordinates(resolved_gtfs_dirs)
    (
        coordinates_by_corridor,
        supplemental_stop_counts,
        excluded_stop_counts,
    ) = _filter_supplemental_stops(
        stops_by_corridor,
        member_ids_by_corridor,
        all_consolidated_member_ids,
    )
    candidates = _corridor_tier_candidates(coordinates_by_corridor, tiers)
    supplemental_features = _supplemental_features(
        candidates,
        original_coverage,
        tiers,
    )
    expected_supplemental_count = len(CORRIDOR_ROUTES) * len(tiers)
    if len(supplemental_features) != expected_supplemental_count:
        raise AssertionError(
            f"Expected exactly {expected_supplemental_count} supplemental "
            f"regions, got "
            f"{len(supplemental_features)}"
        )

    metadata = dict(source.get("metadata", {}))
    metadata.update(
        {
            "corridor_routes": {
                corridor: list(routes)
                for corridor, routes in CORRIDOR_ROUTES.items()
            },
            "supplemental_distance_tiers_used": list(tiers),
            "all_corridor_route_stop_counts": {
                corridor: len(stops_by_corridor[corridor])
                for corridor in CORRIDOR_ROUTES
            },
            "consolidated_member_stop_counts": {
                corridor: len(member_ids_by_corridor[corridor])
                for corridor in CORRIDOR_ROUTES
            },
            "excluded_consolidated_stop_counts": excluded_stop_counts,
            "supplemental_stop_counts": supplemental_stop_counts,
            "consolidated_stop_sources": [
                str(
                    (
                        consolidated_stop_dir
                        / f"{corridor}_corridor_shared_stops.csv"
                    ).relative_to(PROJECT_ROOT)
                )
                if (
                    consolidated_stop_dir
                    / f"{corridor}_corridor_shared_stops.csv"
                ).is_relative_to(PROJECT_ROOT)
                else str(
                    consolidated_stop_dir
                    / f"{corridor}_corridor_shared_stops.csv"
                )
                for corridor in CORRIDOR_ROUTES
            ],
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

    # Reuse the loaded feature dictionaries directly.  Only the supplemental
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
        for tier in sorted(original_tiers, key=_tier_label_sort_key)
    ]
    legend_handles.extend(
        Patch(
            facecolor=SUPPLEMENTAL_TIER_COLORS.get(
                (corridor, tier), "#bdbdbd"
            ),
            edgecolor="#202020",
            label=f"{corridor} {tier}",
        )
        for corridor in CORRIDOR_ROUTES
        for tier in sorted(
            {
                supplemental_tier
                for supplemental_corridor, supplemental_tier
                in supplemental_regions
                if supplemental_corridor == corridor
            },
            key=_tier_label_sort_key,
        )
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
            "Append mutually exclusive, filtered corridor-route regions to a "
            "2024 stop-region GeoJSON."
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
        "--consolidated-stop-dir",
        type=Path,
        default=DEFAULT_CONSOLIDATED_STOP_DIR,
        help=(
            "Directory containing the consolidated Orange, Blue, and Green "
            f"stop CSVs (default: {DEFAULT_CONSOLIDATED_STOP_DIR})"
        ),
    )
    parser.add_argument(
        "--distance-tier",
        type=int,
        action="append",
        dest="distance_tiers",
        help=(
            "Outer distance in meters; repeat for multiple tiers. "
            "Defaults to one 400 m tier."
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
    distance_tiers = (
        tuple(args.distance_tiers)
        if args.distance_tiers
        else DISTANCE_TIERS_METERS
    )
    output = create_full_routes_geojson(
        input_path=args.input,
        gtfs_dirs=gtfs_dirs,
        output_path=args.output,
        consolidated_stop_dir=args.consolidated_stop_dir,
        distance_tiers=distance_tiers,
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
