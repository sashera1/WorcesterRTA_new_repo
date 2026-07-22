"""Print August 2024 corridor and systemwide ridership totals.

Ridership is measured as passenger boardings (``SUM_PASSENGERS_ON``).  For
each colored corridor, boardings on its shared corridor stops are reported
separately from boardings elsewhere on the same routes.  The script also
prints totals for the seven colored-corridor routes and for every WRTA route
in the workbook.

Run from the repository root with::

    python simplified_model/last_min_ridership_aggregates.py
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

if __package__:
    from .aggregate_data import (
        CORRIDOR_ROUTES,
        load_corridor_stops,
        parse_decimal,
        read_xlsx_rows,
    )
else:
    from aggregate_data import (
        CORRIDOR_ROUTES,
        load_corridor_stops,
        parse_decimal,
        read_xlsx_rows,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RIDERSHIP_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "ridership_data_august_2024"
    / "AUGUST 2024 RIDERSHIP BY TIME PERIOD, ROUTE AND STOP (DATAVIEW).XLSX"
)
DEFAULT_CORRIDOR_DIR = (
    PROJECT_ROOT / "data" / "processed" / "stops_organized_data_2024"
)
DISPLAY_ORDER = ("Blue", "Orange", "Green")


@dataclass
class CorridorRidership:
    """Boardings within and outside one route group's shared corridor."""

    on_corridor: Decimal = Decimal(0)
    outside_corridor: Decimal = Decimal(0)

    @property
    def all_route_stops(self) -> Decimal:
        return self.on_corridor + self.outside_corridor


@dataclass(frozen=True)
class RidershipAggregates:
    by_corridor: dict[str, CorridorRidership]
    all_lines: Decimal

    @property
    def on_all_corridors(self) -> Decimal:
        return sum(
            (summary.on_corridor for summary in self.by_corridor.values()),
            start=Decimal(0),
        )

    @property
    def outside_all_corridors(self) -> Decimal:
        return sum(
            (summary.outside_corridor for summary in self.by_corridor.values()),
            start=Decimal(0),
        )

    @property
    def all_corridor_routes(self) -> Decimal:
        return self.on_all_corridors + self.outside_all_corridors

    @property
    def non_corridor_routes(self) -> Decimal:
        return self.all_lines - self.all_corridor_routes


def calculate_ridership_aggregates(
    ridership_path: str | Path = DEFAULT_RIDERSHIP_PATH,
    corridor_dir: str | Path = DEFAULT_CORRIDOR_DIR,
) -> RidershipAggregates:
    """Aggregate August boardings by corridor location and across all routes."""
    ridership_path = Path(ridership_path).resolve()
    corridor_dir = Path(corridor_dir).resolve()
    rows = read_xlsx_rows(ridership_path)
    if not rows:
        raise ValueError(f"Ridership workbook contains no rows: {ridership_path}")

    required_fields = {"ROUTE_NUMBER", "STOP_ID", "SUM_PASSENGERS_ON"}
    missing_fields = required_fields - set(rows[0])
    if missing_fields:
        raise ValueError(
            f"Ridership workbook {ridership_path} is missing columns: "
            f"{sorted(missing_fields)}"
        )

    corridor_stop_ids = {
        corridor: {stop.stop_id for stop in stops}
        for corridor, stops in load_corridor_stops(corridor_dir).items()
    }
    route_to_corridor = {
        route: corridor
        for corridor, routes in CORRIDOR_ROUTES.items()
        for route in routes
    }
    by_corridor = {
        corridor: CorridorRidership() for corridor in CORRIDOR_ROUTES
    }
    target_routes_seen: set[str] = set()
    matched_corridors: set[str] = set()
    all_lines = Decimal(0)

    for row in rows:
        boardings = parse_decimal(
            row.get("SUM_PASSENGERS_ON", ""),
            "SUM_PASSENGERS_ON",
            ridership_path,
        )
        all_lines += boardings

        route = row.get("ROUTE_NUMBER", "").strip()
        corridor = route_to_corridor.get(route)
        if corridor is None:
            continue

        target_routes_seen.add(route)
        stop_id = row.get("STOP_ID", "").strip()
        if not stop_id:
            raise ValueError(
                f"Corridor-route ridership row has no STOP_ID in {ridership_path}"
            )

        summary = by_corridor[corridor]
        if stop_id in corridor_stop_ids[corridor]:
            summary.on_corridor += boardings
            matched_corridors.add(corridor)
        else:
            summary.outside_corridor += boardings

    missing_routes = set(route_to_corridor) - target_routes_seen
    if missing_routes:
        raise ValueError(
            f"Ridership workbook is missing configured corridor routes: "
            f"{sorted(missing_routes)}"
        )
    missing_corridor_matches = set(CORRIDOR_ROUTES) - matched_corridors
    if missing_corridor_matches:
        raise ValueError(
            "No workbook stops matched the processed stop list for corridors: "
            f"{sorted(missing_corridor_matches)}"
        )

    return RidershipAggregates(by_corridor=by_corridor, all_lines=all_lines)


def format_boardings(value: Decimal) -> str:
    """Format whole boardings with separators while retaining any fractions."""
    if value == value.to_integral_value():
        return f"{int(value):,}"
    return f"{value:,.6f}".rstrip("0").rstrip(".")


def print_ridership_aggregates(aggregates: RidershipAggregates) -> None:
    """Print a compact table and systemwide reconciliation to the terminal."""
    headings = (
        "Corridor",
        "On shared corridor",
        "Elsewhere on same routes",
        "All route stops",
    )
    corridor_rows = []
    for corridor in DISPLAY_ORDER:
        summary = aggregates.by_corridor[corridor]
        corridor_rows.append(
            (
                corridor,
                format_boardings(summary.on_corridor),
                format_boardings(summary.outside_corridor),
                format_boardings(summary.all_route_stops),
            )
        )
    total_row = (
        "All three",
        format_boardings(aggregates.on_all_corridors),
        format_boardings(aggregates.outside_all_corridors),
        format_boardings(aggregates.all_corridor_routes),
    )
    table_rows = [*corridor_rows, total_row]

    widths = [
        max(len(headings[index]), *(len(row[index]) for row in table_rows))
        for index in range(len(headings))
    ]
    print("August 2024 ridership (passenger boardings)")
    print(
        f"{headings[0]:<{widths[0]}}  "
        + "  ".join(
            f"{heading:>{widths[index]}}"
            for index, heading in enumerate(headings[1:], start=1)
        )
    )
    print("  ".join("-" * width for width in widths))
    for row in corridor_rows:
        print(
            f"{row[0]:<{widths[0]}}  "
            + "  ".join(
                f"{value:>{widths[index]}}"
                for index, value in enumerate(row[1:], start=1)
            )
        )
    print("  ".join("-" * width for width in widths))
    print(
        f"{total_row[0]:<{widths[0]}}  "
        + "  ".join(
            f"{value:>{widths[index]}}"
            for index, value in enumerate(total_row[1:], start=1)
        )
    )

    print()
    print(
        "All other WRTA routes:         "
        f"{format_boardings(aggregates.non_corridor_routes)}"
    )
    print(
        "All WRTA routes:               "
        f"{format_boardings(aggregates.all_lines)}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ridership-path",
        type=Path,
        default=DEFAULT_RIDERSHIP_PATH,
        help=f"August 2024 ridership workbook (default: {DEFAULT_RIDERSHIP_PATH})",
    )
    parser.add_argument(
        "--corridor-dir",
        type=Path,
        default=DEFAULT_CORRIDOR_DIR,
        help=f"Processed corridor-stop directory (default: {DEFAULT_CORRIDOR_DIR})",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    aggregates = calculate_ridership_aggregates(
        ridership_path=arguments.ridership_path,
        corridor_dir=arguments.corridor_dir,
    )
    print_ridership_aggregates(aggregates)


if __name__ == "__main__":
    main()
