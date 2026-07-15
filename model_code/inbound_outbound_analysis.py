import csv
import re
import xml.etree.ElementTree as ET
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb
from src.config import corridors
from collections import defaultdict
from functools import cache
from pathlib import Path
from zipfile import ZipFile


DEFAULT_RIDERSHIP_PATH = Path(
    "data/raw/ridership_data_august_2024/"
    "AUGUST 2024 RIDERSHIP BY TIME PERIOD, ROUTE AND STOP (DATAVIEW).XLSX"
)

XML_NAMESPACE = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
}


def _column_index(cell_reference: str) -> int:
    letters = re.match(r"[A-Z]+", cell_reference).group()
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter) - ord("A") + 1
    return index - 1


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    if cell.get("t") == "inlineStr":
        return "".join(
            text.text or "" for text in cell.findall(".//main:t", XML_NAMESPACE)
        )

    value = cell.find("main:v", XML_NAMESPACE)
    if value is None:
        return ""
    if cell.get("t") == "s":
        return shared_strings[int(value.text)]
    return value.text


@cache
def _load_xlsx_rows(path: Path) -> tuple[dict[str, str], ...]:
    with ZipFile(path) as workbook:
        shared_strings = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            shared_xml = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(text.text or "" for text in item.findall(".//main:t", XML_NAMESPACE))
                for item in shared_xml.findall("main:si", XML_NAMESPACE)
            ]

        sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        rows = sheet.findall(".//main:sheetData/main:row", XML_NAMESPACE)

        headers = {
            _column_index(cell.get("r")): _cell_value(cell, shared_strings)
            for cell in rows[0].findall("main:c", XML_NAMESPACE)
        }

        return tuple(
            {
                headers[_column_index(cell.get("r"))]: _cell_value(cell, shared_strings)
                for cell in row.findall("main:c", XML_NAMESPACE)
                if _column_index(cell.get("r")) in headers
            }
            for row in rows[1:]
        )


def _read_xlsx_rows(path: str | Path):
    return _load_xlsx_rows(Path(path))


@cache
def _load_stop_coordinates(path: Path) -> dict[str, tuple[float, float]]:
    coordinates = {}
    for row in _read_xlsx_rows(path):
        if row.get("LAT") and row.get("LON"):
            coordinates[row["STOP_ID"]] = (float(row["LAT"]), float(row["LON"]))
    return coordinates


def analyze_route_directions(
    route_number: str | int,
    ridership_path: str | Path = DEFAULT_RIDERSHIP_PATH,
) -> tuple[set[str], set[str], set[str]]:
    """Return stops that are outbound-only, inbound-only, and both, in that order."""
    directions_by_stop = defaultdict(set)

    for row in _read_xlsx_rows(ridership_path):
        if row["ROUTE_NUMBER"] != str(route_number):
            continue

        stop_id = row["STOP_ID"]
        direction = row["DIRECTION_NAME"].upper()
        if (
            stop_id != "99999"
            and row["TIMEPOINT"] != "-1"
            and direction in {"INBOUND", "OUTBOUND"}
        ):
            directions_by_stop[stop_id].add(direction)

    outbound_only = {
        stop_id
        for stop_id, directions in directions_by_stop.items()
        if directions == {"OUTBOUND"}
    }
    inbound_only = {
        stop_id
        for stop_id, directions in directions_by_stop.items()
        if directions == {"INBOUND"}
    }
    both = {
        stop_id
        for stop_id, directions in directions_by_stop.items()
        if directions == {"INBOUND", "OUTBOUND"}
    }

    return outbound_only, inbound_only, both


def combine_route_directions(
    route_directions: dict[str, tuple[set[str], set[str], set[str]]],
) -> tuple[set[str], set[str], set[str]]:
    directions_by_stop = defaultdict(set)

    for outbound, inbound, both in route_directions.values():
        for stop_id in outbound:
            directions_by_stop[stop_id].add("OUTBOUND")
        for stop_id in inbound:
            directions_by_stop[stop_id].add("INBOUND")
        for stop_id in both:
            directions_by_stop[stop_id].update({"INBOUND", "OUTBOUND"})

    outbound_only = {
        stop_id
        for stop_id, directions in directions_by_stop.items()
        if directions == {"OUTBOUND"}
    }
    inbound_only = {
        stop_id
        for stop_id, directions in directions_by_stop.items()
        if directions == {"INBOUND"}
    }
    both = {
        stop_id
        for stop_id, directions in directions_by_stop.items()
        if directions == {"INBOUND", "OUTBOUND"}
    }

    return outbound_only, inbound_only, both


def graph_stops_by_direction(
    ax,
    inbound: set[str],
    outbound: set[str],
    both: set[str],
    color: str | tuple[float, float, float],
):
    coordinates = _load_stop_coordinates(DEFAULT_RIDERSHIP_PATH)
    existing_labels = set(ax.get_legend_handles_labels()[1])

    for stops, marker, label in [
        (inbound, "I", "Inbound"),
        (outbound, "O", "Outbound"),
        (both, "B", "Both"),
    ]:
        points = [coordinates[stop_id] for stop_id in sorted(stops) if stop_id in coordinates]
        if points:
            latitudes, longitudes = zip(*points)
            ax.scatter(
                longitudes,
                latitudes,
                marker=f"${marker}$",
                color=color,
                s=80,
                label=None if label in existing_labels else label,
            )
            existing_labels.add(label)


def lighten_color(color: str, amount: float = 0.65) -> tuple[float, float, float]:
    red, green, blue = to_rgb(color)
    return (
        red + (1 - red) * amount,
        green + (1 - green) * amount,
        blue + (1 - blue) * amount,
    )


def write_shared_stops_by_direction(
    corridor: str,
    shared_stops: set[str],
    inbound: set[str],
    outbound: set[str],
    both: set[str],
    output_dir: str | Path = "data/processed/stops_organized_data_2024_by_direction",
):
    coordinates = _load_stop_coordinates(DEFAULT_RIDERSHIP_PATH)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with (output_dir / f"{corridor}_corridor_shared_stops.csv").open(
        "w", encoding="utf-8", newline=""
    ) as output_file:
        writer = csv.writer(output_file)
        writer.writerow(["stop_id", "latitude", "longitude", "direction"])

        for stop_id in sorted(shared_stops, key=int):
            latitude, longitude = coordinates[stop_id]
            if stop_id in both:
                direction = "BOTH"
            elif stop_id in inbound:
                direction = "INBOUND"
            else:
                direction = "OUTBOUND"

            writer.writerow([stop_id, latitude, longitude, direction])


if __name__ == "__main__":
    fig, ax = plt.subplots(figsize=(10, 8))
    route_directions = {}

    for corridor, routes in corridors.items():
        for route in routes:
            outbound_only, inbound_only, both = analyze_route_directions(route)
            route_directions[route] = (outbound_only, inbound_only, both)
            print(f"Route {route} ({corridor} corridor):")
            print("\tOutbound only:", outbound_only)
            print("\tInbound only:", inbound_only)
            print("\tBoth:", both)

    combined_outbound, combined_inbound, combined_both = combine_route_directions(
        route_directions
    )

    route_stops = {
        route: set().union(*direction_sets)
        for route, direction_sets in route_directions.items()
    }
    corridor_stops = {
        corridor: set().union(*(route_stops[route] for route in routes))
        for corridor, routes in corridors.items()
    }

    corridors_by_stop = defaultdict(set)
    for corridor, stops in corridor_stops.items():
        for stop_id in stops:
            corridors_by_stop[stop_id].add(corridor)

    multi_corridor_stops = {
        stop_id
        for stop_id, stop_corridors in corridors_by_stop.items()
        if len(stop_corridors) > 1
    }

    for corridor, routes in corridors.items():
        stops_on_every_route = set.intersection(
            *(route_stops[route] for route in routes)
        )
        print(f"Corridor {corridor}:")
        print("\tStops on every route:", stops_on_every_route)
        fully_shared_stops = stops_on_every_route - multi_corridor_stops
        partially_shared_stops = (
            corridor_stops[corridor] - stops_on_every_route - multi_corridor_stops
        )

        write_shared_stops_by_direction(
            corridor,
            stops_on_every_route,
            combined_inbound,
            combined_outbound,
            combined_both,
        )

        graph_stops_by_direction(
            ax,
            combined_inbound & fully_shared_stops,
            combined_outbound & fully_shared_stops,
            combined_both & fully_shared_stops,
            color=corridor,
        )
        graph_stops_by_direction(
            ax,
            combined_inbound & partially_shared_stops,
            combined_outbound & partially_shared_stops,
            combined_both & partially_shared_stops,
            color=lighten_color(corridor),
        )

    graph_stops_by_direction(
        ax,
        combined_inbound & multi_corridor_stops,
        combined_outbound & multi_corridor_stops,
        combined_both & multi_corridor_stops,
        color="black",
    )

    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Stops by Direction")
    ax.set_aspect(1.35)
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend()
    plt.show()

    
