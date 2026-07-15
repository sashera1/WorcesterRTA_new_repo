import csv
import heapq
from collections import defaultdict
from math import dist
from pathlib import Path

import matplotlib.pyplot as plt
from shapely.geometry import Point
from shapely.ops import transform

from src.config import center_coords
from src.toolkits.geometric_toolset import (
    project_from_deg_to_meters,
    project_from_meters_to_degrees,
)


INPUT_DIR = Path("data/processed/stops_organized_data_2024_by_direction")
OUTPUT_DIR = Path("data/processed/stops_consolidated_data_2024")
CONSOLIDATED_FIELDNAMES = [
    "stop_id",
    "latitude",
    "longitude",
    "inbound_stop_id",
    "outbound_stop_id",
    "direction",
    "extra_inbound",
    "extra_outbound",
]


def consolidate(
    input_csv: str | Path,
    threshold_meters: float = 200,
) -> list[dict[str, str | float]]:
    stops = {}

    with Path(input_csv).open(encoding="utf-8-sig", newline="") as input_file:
        for row in csv.DictReader(input_file):
            point_degrees = Point(float(row["longitude"]), float(row["latitude"]))
            point_meters = transform(project_from_deg_to_meters, point_degrees)
            stops[row["stop_id"]] = {
                "direction": row["direction"],
                "point_meters": point_meters,
            }

    inbound_stops = [
        stop_id for stop_id, stop in stops.items() if stop["direction"] == "INBOUND"
    ]
    outbound_stops = [
        stop_id for stop_id, stop in stops.items() if stop["direction"] == "OUTBOUND"
    ]

    pair_queue = []
    for inbound_id in inbound_stops:
        inbound_point = stops[inbound_id]["point_meters"]
        for outbound_id in outbound_stops:
            outbound_point = stops[outbound_id]["point_meters"]
            distance = dist(
                (inbound_point.x, inbound_point.y),
                (outbound_point.x, outbound_point.y),
            )
            if distance <= threshold_meters:
                heapq.heappush(pair_queue, (distance, inbound_id, outbound_id))

    unpaired_stops = set(stops)
    consolidated_rows = []

    while pair_queue:
        _, inbound_id, outbound_id = heapq.heappop(pair_queue)
        if inbound_id not in unpaired_stops or outbound_id not in unpaired_stops:
            continue

        inbound_point = stops[inbound_id]["point_meters"]
        outbound_point = stops[outbound_id]["point_meters"]
        midpoint_meters = Point(
            (inbound_point.x + outbound_point.x) / 2,
            (inbound_point.y + outbound_point.y) / 2,
        )
        midpoint_degrees = transform(project_from_meters_to_degrees, midpoint_meters)

        consolidated_rows.append(
            {
                "stop_id": f"{inbound_id};{outbound_id}",
                "latitude": midpoint_degrees.y,
                "longitude": midpoint_degrees.x,
                "inbound_stop_id": inbound_id,
                "outbound_stop_id": outbound_id,
                "direction": "PAIRED",
            }
        )
        unpaired_stops.remove(inbound_id)
        unpaired_stops.remove(outbound_id)

    for stop_id in sorted(unpaired_stops, key=int):
        stop = stops[stop_id]
        point_degrees = transform(
            project_from_meters_to_degrees, stop["point_meters"]
        )
        direction = stop["direction"]

        consolidated_rows.append(
            {
                "stop_id": stop_id,
                "latitude": point_degrees.y,
                "longitude": point_degrees.x,
                "inbound_stop_id": stop_id if direction in {"INBOUND", "BOTH"} else "",
                "outbound_stop_id": stop_id if direction in {"OUTBOUND", "BOTH"} else "",
                "direction": direction,
            }
        )

    return consolidated_rows


def write_consolidated_csv(
    rows: list[dict[str, str | float]], output_csv: str | Path
):
    with Path(output_csv).open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=CONSOLIDATED_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def consolidated_cleanup(
    consolidated_csv: str | Path,
    center_radius_meters: float = 500,
) -> list[dict[str, str | float]]:
    consolidated_csv = Path(consolidated_csv)
    with consolidated_csv.open(encoding="utf-8-sig", newline="") as input_file:
        rows = list(csv.DictReader(input_file))

    for row in rows:
        row.setdefault("extra_inbound", "")
        row.setdefault("extra_outbound", "")

    paired_rows = [row for row in rows if row["direction"] == "PAIRED"]
    if not paired_rows:
        write_consolidated_csv(rows, consolidated_csv)
        return rows

    center_degrees = Point(center_coords[1], center_coords[0])
    center_meters = transform(project_from_deg_to_meters, center_degrees)

    paired_points = {
        id(row): transform(
            project_from_deg_to_meters,
            Point(float(row["longitude"]), float(row["latitude"])),
        )
        for row in paired_rows
    }
    rows_to_remove = set()

    for row in rows:
        if row["direction"] not in {"INBOUND", "OUTBOUND"}:
            continue

        stop_point = transform(
            project_from_deg_to_meters,
            Point(float(row["longitude"]), float(row["latitude"])),
        )
        distance_from_center = dist(
            (stop_point.x, stop_point.y),
            (center_meters.x, center_meters.y),
        )
        if distance_from_center <= center_radius_meters:
            continue

        nearest_pair = min(
            paired_rows,
            key=lambda pair: dist(
                (stop_point.x, stop_point.y),
                (paired_points[id(pair)].x, paired_points[id(pair)].y),
            ),
        )
        extra_column = (
            "extra_inbound" if row["direction"] == "INBOUND" else "extra_outbound"
        )
        existing_extra_ids = [
            stop_id for stop_id in nearest_pair[extra_column].split(";") if stop_id
        ]
        existing_extra_ids.append(row["stop_id"])
        nearest_pair[extra_column] = ";".join(existing_extra_ids)
        nearest_pair["stop_id"] = f"{nearest_pair['stop_id']};{row['stop_id']}"
        rows_to_remove.add(id(row))

    cleaned_rows = [row for row in rows if id(row) not in rows_to_remove]
    write_consolidated_csv(cleaned_rows, consolidated_csv)
    return cleaned_rows


def visualize_consolidated(
    input_dir: str | Path = OUTPUT_DIR,
):
    input_dir = Path(input_dir)
    rows_by_corridor = {}
    corridors_by_stop = defaultdict(set)

    for input_csv in sorted(input_dir.glob("*_corridor_shared_stops.csv")):
        corridor = input_csv.name.split("_corridor_shared_stops.csv")[0]
        with input_csv.open(encoding="utf-8-sig", newline="") as input_file:
            rows = list(csv.DictReader(input_file))
        rows_by_corridor[corridor] = rows

        for row in rows:
            member_stop_ids = {
                row["inbound_stop_id"],
                row["outbound_stop_id"],
            } - {""}
            for stop_id in member_stop_ids:
                corridors_by_stop[stop_id].add(corridor)

    fig, ax = plt.subplots(figsize=(10, 8))
    existing_labels = set()
    markers = {
        "INBOUND": "I",
        "OUTBOUND": "O",
        "BOTH": "B",
        "PAIRED": "P",
    }

    for corridor, rows in rows_by_corridor.items():
        for row in rows:
            member_stop_ids = {
                row["inbound_stop_id"],
                row["outbound_stop_id"],
            } - {""}
            is_multi_corridor = any(
                len(corridors_by_stop[stop_id]) > 1 for stop_id in member_stop_ids
            )
            direction = row["direction"]
            label = direction.title()

            ax.scatter(
                float(row["longitude"]),
                float(row["latitude"]),
                marker=f"${markers[direction]}$",
                color="black" if is_multi_corridor else corridor,
                s=80,
                label=None if label in existing_labels else label,
            )
            existing_labels.add(label)

    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Directionally Consolidated Stops")
    ax.set_aspect(1.35)
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend()
    plt.show()


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for input_csv in sorted(INPUT_DIR.glob("*_corridor_shared_stops.csv")):
        consolidated_rows = consolidate(input_csv)
        output_csv = OUTPUT_DIR / input_csv.name
        write_consolidated_csv(consolidated_rows, output_csv)
        cleaned_rows = consolidated_cleanup(output_csv)
        print(f"Wrote {len(cleaned_rows)} stops to {output_csv}")
    visualize_consolidated()
