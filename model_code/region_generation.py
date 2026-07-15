import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path as MatplotlibPath
from shapely import voronoi_polygons
from shapely.geometry import MultiPoint, Point, mapping, shape
from shapely.ops import transform, unary_union

from src.toolkits.geometric_toolset import (
    project_from_deg_to_meters,
    project_from_meters_to_degrees,
)


def _load_split_region(region_path: str | Path):
    with Path(region_path).open(encoding="utf-8") as region_file:
        geojson = json.load(region_file)

    if geojson["type"] == "FeatureCollection":
        return unary_union([
            shape(feature["geometry"])
            for feature in geojson["features"]
            if feature.get("geometry")
        ])
    if geojson["type"] == "Feature":
        return shape(geojson["geometry"])
    return shape(geojson)


def make_geojson_corridor(
    stop_id_paths: str | Path | list[str | Path],
    distance_tiers: list[int],
    include_external_tier: bool,
    output_path: str | Path,
    region_to_split: str | Path | None = None,
):
    if include_external_tier and region_to_split is None:
        raise ValueError(
            "region_to_split is required when include_external_tier is True"
        )
    if not distance_tiers:
        raise ValueError("distance_tiers cannot be empty")

    tiers = sorted(set(distance_tiers))
    if tiers[0] <= 0:
        raise ValueError("distance tiers must be greater than zero")

    if isinstance(stop_id_paths, (str, Path)):
        stop_id_paths = [stop_id_paths]

    stops = {}
    for stop_path in stop_id_paths:
        with Path(stop_path).open(encoding="utf-8-sig", newline="") as stop_file:
            for row in csv.DictReader(stop_file):
                stops[row["stop_id"]] = (
                    float(row["latitude"]),
                    float(row["longitude"]),
                )

    if not stops:
        raise ValueError("no stops were found in the supplied CSV files")

    stop_ids = list(stops)
    points_degrees = MultiPoint(
        [Point(stops[stop_id][1], stops[stop_id][0]) for stop_id in stop_ids]
    )
    points_meters = transform(project_from_deg_to_meters, points_degrees)
    stop_points = dict(zip(stop_ids, points_meters.geoms))

    greatest_distance = tiers[-1]
    greatest_distance_region = unary_union([
        point.buffer(greatest_distance) for point in points_meters.geoms
    ])

    split_region_meters = None
    if region_to_split is not None:
        split_region_degrees = _load_split_region(region_to_split)
        split_region_meters = transform(
            project_from_deg_to_meters, split_region_degrees
        )

    if include_external_tier:
        working_region = split_region_meters
    elif split_region_meters is not None:
        working_region = greatest_distance_region.intersection(split_region_meters)
    else:
        working_region = greatest_distance_region

    if len(stop_points) == 1:
        voronoi_by_stop = {stop_ids[0]: working_region}
    else:
        raw_voronoi = voronoi_polygons(
            points_meters,
            extend_to=working_region.envelope,
        )
        voronoi_by_stop = {}
        for stop_id, stop_point in stop_points.items():
            for voronoi_cell in raw_voronoi.geoms:
                if voronoi_cell.distance(stop_point) < 1e-6:
                    voronoi_by_stop[stop_id] = voronoi_cell.intersection(
                        working_region
                    )
                    break

    features = []
    for stop_id, stop_point in stop_points.items():
        voronoi_cell = voronoi_by_stop[stop_id]
        inner_distance = 0

        for outer_distance in tiers:
            tier_geometry = voronoi_cell.intersection(
                stop_point.buffer(outer_distance)
            )
            if inner_distance:
                tier_geometry = tier_geometry.difference(
                    stop_point.buffer(inner_distance)
                )

            tier_geometry = tier_geometry.buffer(-0.1)
            if not tier_geometry.is_empty:
                tier_label = f"{inner_distance}-{outer_distance}m"
                geometry_degrees = transform(
                    project_from_meters_to_degrees, tier_geometry
                )
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "stop_id": stop_id,
                            "tier": tier_label,
                            "name": f"{stop_id}_{tier_label}",
                        },
                        "geometry": mapping(geometry_degrees),
                    }
                )

            inner_distance = outer_distance

        if include_external_tier:
            external_geometry = voronoi_cell.difference(
                stop_point.buffer(greatest_distance)
            ).buffer(-0.1)
            if not external_geometry.is_empty:
                tier_label = f"{greatest_distance}+m"
                geometry_degrees = transform(
                    project_from_meters_to_degrees, external_geometry
                )
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "stop_id": stop_id,
                            "tier": tier_label,
                            "name": f"{stop_id}_{tier_label}",
                        },
                        "geometry": mapping(geometry_degrees),
                    }
                )

    feature_collection = {
        "type": "FeatureCollection",
        "metadata": {
            "distance_tiers_used": tiers,
            "include_external_tier": include_external_tier,
            "total_regions": len(features),
        },
        "features": features,
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output_file:
        json.dump(feature_collection, output_file, indent=2)

    return feature_collection


def visualize_geojson(geojson_path: str | Path):
    with Path(geojson_path).open(encoding="utf-8") as geojson_file:
        geojson = json.load(geojson_file)

    tier_labels = sorted(
        {feature["properties"]["tier"] for feature in geojson["features"]},
        key=lambda tier: float(tier.split("-", 1)[0].replace("+m", "")),
    )
    color_map = plt.get_cmap("viridis", len(tier_labels))
    colors = {
        tier: color_map(index) for index, tier in enumerate(tier_labels)
    }

    fig, ax = plt.subplots(figsize=(10, 8))

    for feature in geojson["features"]:
        geometry = shape(feature["geometry"])
        tier = feature["properties"]["tier"]
        polygons = [geometry] if geometry.geom_type == "Polygon" else geometry.geoms

        for polygon in polygons:
            vertices = []
            codes = []
            for ring in [polygon.exterior, *polygon.interiors]:
                ring_coordinates = list(ring.coords)
                vertices.extend(ring_coordinates)
                codes.extend(
                    [MatplotlibPath.MOVETO]
                    + [MatplotlibPath.LINETO] * (len(ring_coordinates) - 2)
                    + [MatplotlibPath.CLOSEPOLY]
                )

            ax.add_patch(
                PathPatch(
                    MatplotlibPath(vertices, codes),
                    facecolor=colors[tier],
                    edgecolor="black",
                    linewidth=0.3,
                    alpha=0.75,
                )
            )

    ax.autoscale_view()
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Generated Stop Regions")
    ax.set_aspect(1.35)
    ax.grid(True, linestyle="--", alpha=0.3)
    ax.legend(
        handles=[Patch(facecolor=colors[tier], label=tier) for tier in tier_labels],
        title="Distance tier",
    )
    plt.tight_layout()
    plt.show()

make_geojson_corridor(
    stop_id_paths=[
        "data/processed/stops_consolidated_data_2024/Orange_corridor_shared_stops.csv",
        "data/processed/stops_consolidated_data_2024/Blue_corridor_shared_stops.csv",
        "data/processed/stops_consolidated_data_2024/Green_corridor_shared_stops.csv",
    ],
    distance_tiers=[200, 400],
    include_external_tier=False,
    #region_to_split="data/raw/worcester_municipal_boundary.geojson",
    output_path="data/processed/area_around_stops_new/tiered_corridor_bidirectional.geojson",
)

visualize_geojson(
    "data/processed/area_around_stops_new/tiered_corridor_bidirectional.geojson"
)
