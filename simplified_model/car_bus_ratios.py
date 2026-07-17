"""Combine August 2024 corridor boardings with TomTom car-trip summaries.

The output contains one row for every origin and time range in the six
``combined_by_origin_*.csv`` files.  Boardings are summed across every stop in
the origin region and both travel directions.  Hub Center (stop 1503) is
labelled ``all`` and includes boardings from all three corridor route groups.
The near ratio uses the inner/inner car bucket labelled ``0-800m Trips`` in
the combined reports.

Run from the repository root with::

    python simplified_model/car_bus_ratios.py
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMBINED_DIR = Path(__file__).resolve().parent
DEFAULT_HEADWAY_DIR = Path(__file__).resolve().parent / "2024_headway_aggregate"
DEFAULT_CORRIDOR_DIR = (
    PROJECT_ROOT / "data" / "processed" / "stops_consolidated_data_2024"
)
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "car_bus_ratios.csv"

CORRIDORS = ("Orange", "Blue", "Green")
DIRECTIONS = ("inbound", "outbound")
CENTER_STATION_ORIGIN = "1503"
COMBINED_CAR_COLUMNS = (
    "0-800m Trips",
    "0-1600m Trips",
    "800-1600m Trips",
)
COMBINED_REQUIRED_COLUMNS = {"Origin", *COMBINED_CAR_COLUMNS}
HEADWAY_REQUIRED_COLUMNS = {
    "stop_id",
    "corridor",
    "direction",
    "time_period",
    "total_boardings",
}
OUTPUT_COLUMNS = (
    "origin",
    "time",
    "corridor",
    "onboardings",
    "car_trips_0_800m",
    "car_trips_0_1600m",
    "car_trips_800_1600m",
    "bus_ratio_near",
    "bus_ratio_all",
)


@dataclass(frozen=True)
class TimePeriod:
    """Names used by the TomTom file, output row, and headway file."""

    filename_range: str
    display_range: str
    headway_slug: str
    headway_name: str


TIME_PERIODS = (
    TimePeriod("04-00_to_06-00", "04:00 - 06:00", "am_early", "AM Early"),
    TimePeriod("06-00_to_09-00", "06:00 - 09:00", "am_peak", "AM Peak"),
    TimePeriod("09-00_to_15-00", "09:00 - 15:00", "midday", "Midday"),
    TimePeriod("15-00_to_18-00", "15:00 - 18:00", "pm_peak", "PM Peak"),
    TimePeriod("18-00_to_22-00", "18:00 - 22:00", "pm_late", "PM Late"),
    TimePeriod(
        "22-00_to_00-00",
        "22:00 - 00:00",
        "pm_late_night",
        "PM Late Night",
    ),
)


def _parse_nonnegative_decimal(
    value: str | None,
    column: str,
    path: Path,
    row_number: int,
) -> Decimal:
    """Parse a finite nonnegative number with file and row context."""
    if value is None or not value.strip():
        raise ValueError(
            f"{path}, row {row_number}, column {column!r} is blank"
        )
    try:
        number = Decimal(value.strip())
    except InvalidOperation as error:
        raise ValueError(
            f"{path}, row {row_number}, column {column!r} has invalid value "
            f"{value!r}"
        ) from error
    if not number.is_finite() or number < 0:
        raise ValueError(
            f"{path}, row {row_number}, column {column!r} has invalid value "
            f"{value!r}"
        )
    return number


def _format_count(value: Decimal) -> str:
    """Keep integral counts readable while retaining exact fractional data."""
    if value == value.to_integral_value():
        return str(int(value))
    return format(value, "f").rstrip("0").rstrip(".")


def _format_ratio(numerator: Decimal, denominator: Decimal) -> str:
    """Format a ratio to six places, or blank when it is undefined."""
    if denominator == 0:
        return ""
    return f"{numerator / denominator:.6f}"


def load_origin_corridors(
    corridor_dir: str | Path = DEFAULT_CORRIDOR_DIR,
) -> dict[str, str]:
    """Map consolidated origin IDs to Orange, Blue, Green, or ``all``."""
    corridor_dir = Path(corridor_dir).resolve()
    memberships: dict[str, set[str]] = {}

    for corridor in CORRIDORS:
        input_path = corridor_dir / f"{corridor}_corridor_shared_stops.csv"
        if not input_path.is_file():
            raise FileNotFoundError(
                f"Corridor-stop file does not exist: {input_path}"
            )
        with input_path.open(encoding="utf-8-sig", newline="") as input_file:
            reader = csv.DictReader(input_file)
            if "stop_id" not in (reader.fieldnames or ()):
                raise ValueError(f"{input_path} is missing column 'stop_id'")
            seen_in_file: set[str] = set()
            for row_number, row in enumerate(reader, start=2):
                origin = (row.get("stop_id") or "").strip()
                if not origin:
                    raise ValueError(
                        f"{input_path}, row {row_number} has a blank stop_id"
                    )
                if origin in seen_in_file:
                    raise ValueError(
                        f"{input_path} contains duplicate origin {origin!r}"
                    )
                seen_in_file.add(origin)
                memberships.setdefault(origin, set()).add(corridor)

    expected_center_memberships = set(CORRIDORS)
    if memberships.get(CENTER_STATION_ORIGIN) != expected_center_memberships:
        raise ValueError(
            f"Center station {CENTER_STATION_ORIGIN} must belong to all "
            f"corridors; found {memberships.get(CENTER_STATION_ORIGIN)}"
        )

    origin_corridors: dict[str, str] = {}
    for origin, origin_memberships in memberships.items():
        if origin == CENTER_STATION_ORIGIN:
            origin_corridors[origin] = "all"
        elif len(origin_memberships) == 1:
            origin_corridors[origin] = next(iter(origin_memberships))
        else:
            raise ValueError(
                f"Non-center origin {origin!r} belongs to multiple corridors: "
                f"{sorted(origin_memberships)}"
            )
    return origin_corridors


def load_boarding_totals(
    headway_dir: str | Path = DEFAULT_HEADWAY_DIR,
) -> dict[tuple[str, str, str], Decimal]:
    """Sum both directions' total boardings by period, corridor, and stop."""
    headway_dir = Path(headway_dir).resolve()
    totals: dict[tuple[str, str, str], Decimal] = {}

    for time_period in TIME_PERIODS:
        for corridor in CORRIDORS:
            for direction in DIRECTIONS:
                input_path = headway_dir / (
                    f"{corridor}_{direction}_"
                    f"{time_period.headway_slug}_headways.csv"
                )
                if not input_path.is_file():
                    raise FileNotFoundError(
                        f"Headway/boarding file does not exist: {input_path}"
                    )
                with input_path.open(
                    encoding="utf-8-sig", newline=""
                ) as input_file:
                    reader = csv.DictReader(input_file)
                    missing_columns = HEADWAY_REQUIRED_COLUMNS - set(
                        reader.fieldnames or ()
                    )
                    if missing_columns:
                        raise ValueError(
                            f"{input_path} is missing columns: "
                            f"{sorted(missing_columns)}"
                        )

                    seen_stops: set[str] = set()
                    for row_number, row in enumerate(reader, start=2):
                        stop_id = (row.get("stop_id") or "").strip()
                        if not stop_id:
                            raise ValueError(
                                f"{input_path}, row {row_number} has a blank "
                                "stop_id"
                            )
                        if stop_id in seen_stops:
                            raise ValueError(
                                f"{input_path} contains duplicate stop "
                                f"{stop_id!r}"
                            )
                        seen_stops.add(stop_id)
                        if (row.get("corridor") or "").strip() != corridor:
                            raise ValueError(
                                f"{input_path}, row {row_number} has the wrong "
                                "corridor"
                            )
                        if (row.get("direction") or "").strip() != direction:
                            raise ValueError(
                                f"{input_path}, row {row_number} has the wrong "
                                "direction"
                            )
                        if (
                            row.get("time_period") or ""
                        ).strip() != time_period.headway_name:
                            raise ValueError(
                                f"{input_path}, row {row_number} has the wrong "
                                "time period"
                            )
                        boardings = _parse_nonnegative_decimal(
                            row.get("total_boardings"),
                            "total_boardings",
                            input_path,
                            row_number,
                        )
                        key = (
                            time_period.headway_slug,
                            corridor,
                            stop_id,
                        )
                        totals[key] = totals.get(key, Decimal(0)) + boardings

                    if not seen_stops:
                        raise ValueError(
                            f"Headway/boarding file is empty: {input_path}"
                        )
    return totals


def _load_combined_car_rows(
    input_path: Path,
) -> list[tuple[str, tuple[Decimal, Decimal, Decimal]]]:
    """Read and validate one combined-by-origin car-trip file."""
    if not input_path.is_file():
        raise FileNotFoundError(
            f"Combined-by-origin file does not exist: {input_path}"
        )
    rows: list[tuple[str, tuple[Decimal, Decimal, Decimal]]] = []
    seen_origins: set[str] = set()
    with input_path.open(encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        missing_columns = COMBINED_REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing_columns:
            raise ValueError(
                f"{input_path} is missing columns: {sorted(missing_columns)}"
            )
        for row_number, row in enumerate(reader, start=2):
            origin = (row.get("Origin") or "").strip()
            if not origin:
                raise ValueError(
                    f"{input_path}, row {row_number} has a blank origin"
                )
            if origin in seen_origins:
                raise ValueError(
                    f"{input_path} contains duplicate origin {origin!r}"
                )
            seen_origins.add(origin)
            car_trips = tuple(
                _parse_nonnegative_decimal(
                    row.get(column), column, input_path, row_number
                )
                for column in COMBINED_CAR_COLUMNS
            )
            rows.append((origin, car_trips))
    if not rows:
        raise ValueError(f"Combined-by-origin file is empty: {input_path}")
    return rows


def _boardings_for_origin(
    origin: str,
    corridor: str,
    time_period: TimePeriod,
    boarding_totals: dict[tuple[str, str, str], Decimal],
) -> Decimal:
    """Sum every component stop and applicable corridor for one origin."""
    stop_ids = [stop_id.strip() for stop_id in origin.split(";")]
    if any(not stop_id for stop_id in stop_ids) or len(stop_ids) != len(
        set(stop_ids)
    ):
        raise ValueError(f"Origin has invalid component stop IDs: {origin!r}")
    applicable_corridors = CORRIDORS if corridor == "all" else (corridor,)

    total = Decimal(0)
    for stop_id in stop_ids:
        for applicable_corridor in applicable_corridors:
            key = (
                time_period.headway_slug,
                applicable_corridor,
                stop_id,
            )
            if key not in boarding_totals:
                raise ValueError(
                    f"No boarding row found for origin {origin!r}, stop "
                    f"{stop_id!r}, corridor {applicable_corridor}, and period "
                    f"{time_period.display_range}"
                )
            total += boarding_totals[key]
    return total


def write_car_bus_ratios(
    combined_dir: str | Path = DEFAULT_COMBINED_DIR,
    headway_dir: str | Path = DEFAULT_HEADWAY_DIR,
    corridor_dir: str | Path = DEFAULT_CORRIDOR_DIR,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
) -> Path:
    """Write the single origin-by-time car/bus ratio CSV and return its path."""
    combined_dir = Path(combined_dir).resolve()
    output_path = Path(output_path).resolve()
    origin_corridors = load_origin_corridors(corridor_dir)
    boarding_totals = load_boarding_totals(headway_dir)

    output_rows: list[dict[str, str]] = []
    reference_origins: list[str] | None = None
    for time_period in TIME_PERIODS:
        combined_path = combined_dir / (
            f"combined_by_origin_{time_period.filename_range}.csv"
        )
        car_rows = _load_combined_car_rows(combined_path)
        current_origins = [origin for origin, _ in car_rows]
        if reference_origins is None:
            reference_origins = current_origins
        elif current_origins != reference_origins:
            raise ValueError(
                f"{combined_path} does not contain the same ordered origins "
                "as the other combined reports"
            )

        for origin, car_trips in car_rows:
            corridor = origin_corridors.get(origin)
            if corridor is None:
                raise ValueError(
                    f"Origin {origin!r} is not present in the consolidated "
                    "corridor-stop data"
                )
            onboardings = _boardings_for_origin(
                origin,
                corridor,
                time_period,
                boarding_totals,
            )
            near_car_trips, mixed_car_trips, outer_car_trips = car_trips
            all_car_trips = sum(car_trips, Decimal(0))
            output_rows.append(
                {
                    "origin": origin,
                    "time": time_period.display_range,
                    "corridor": corridor,
                    "onboardings": _format_count(onboardings),
                    "car_trips_0_800m": _format_count(near_car_trips),
                    "car_trips_0_1600m": _format_count(mixed_car_trips),
                    "car_trips_800_1600m": _format_count(outer_car_trips),
                    "bus_ratio_near": _format_ratio(
                        onboardings,
                        onboardings + near_car_trips,
                    ),
                    "bus_ratio_all": _format_ratio(
                        onboardings,
                        onboardings + all_car_trips,
                    ),
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--combined-dir",
        type=Path,
        default=DEFAULT_COMBINED_DIR,
        help=f"Combined car-trip CSV directory (default: {DEFAULT_COMBINED_DIR})",
    )
    parser.add_argument(
        "--headway-dir",
        type=Path,
        default=DEFAULT_HEADWAY_DIR,
        help=f"2024 headway/boarding CSV directory (default: {DEFAULT_HEADWAY_DIR})",
    )
    parser.add_argument(
        "--corridor-dir",
        type=Path,
        default=DEFAULT_CORRIDOR_DIR,
        help=f"Consolidated corridor-stop directory (default: {DEFAULT_CORRIDOR_DIR})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Output CSV (default: {DEFAULT_OUTPUT_PATH})",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    written_path = write_car_bus_ratios(
        combined_dir=arguments.combined_dir,
        headway_dir=arguments.headway_dir,
        corridor_dir=arguments.corridor_dir,
        output_path=arguments.output,
    )
    print(f"Wrote {written_path}")
