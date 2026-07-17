"""Calculate scheduled corridor headways and random-arrival wait times.

The corridor CSVs identify the stops shared by the routes in each corridor.  GTFS
``trips.txt`` and ``stop_times.txt`` provide the scheduled arrivals at those
stops.  Headways are calculated between consecutive arrivals on the same
service date, corridor, direction, and stop.  The calculation combines all
routes assigned to a corridor because a passenger travelling along the shared
part of the corridor can use any of them.

The April 2025 ridership workbooks provide boardings and disembarkings.  Their
``SUM_PASSENGERS_ON`` and ``SUM_PASSENGERS_OFF`` values are summed across the
matching corridor routes.  Per-trip averages are then calculated from those
combined totals and the combined ``TRIPS_COUNT``; the workbook's precomputed
``AVG_PASSENGERS_*`` columns are deliberately not used.

For the observed headway distribution H, the expected wait of a passenger who
arrives at a random time is calculated with the supplied formula::

    E[W] = mean(H) / 2 + variance(H) / (2 * mean(H))

``variance(H)`` is the population variance.  Service dates come from
``calendar.txt`` with additions/removals from ``calendar_dates.txt``.  This
means that weekday results correctly weight Monday-Thursday, Friday, and
holiday schedules over the GTFS feed's actual date range.  Headways never span
two service dates, so the overnight gap is excluded.

Run from the repository root with::

    python simplified_model/aggregate_data.py

The script writes one CSV per corridor, direction, and service type to this
directory by default.  Alternative input/output directories can be supplied
through command-line flags; run with ``--help`` for details.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable
from zipfile import ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GTFS_DIR = PROJECT_ROOT / "data" / "raw" / "gtfs_data_2025" / "version_1"
DEFAULT_CORRIDOR_DIR = (
    PROJECT_ROOT / "data" / "processed" / "stops_organized_data_2025"
)
DEFAULT_RIDERSHIP_DIR = (
    PROJECT_ROOT / "data" / "raw" / "ridership_data_april_2025"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "2025_headway_aggregate"

RIDERSHIP_FILENAMES = {
    "weekday": "APR25 AVG WEEKDAY RIDERSHIP BY ROUTE AND STOP (DATAVIEW).XLSX",
    "saturday": "APR25 AVG SATURDAY RIDERSHIP BY ROUTE AND STOP (DATAVIEW).XLSX",
    "sunday": "APR25 AVG SUNDAY RIDERSHIP BY ROUTE AND STOP (DATAVIEW).XLSX",
}
XLSX_NAMESPACE = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
}

# These route groups match src/config.py.  The identifiers are both route_id
# and route_short_name in the 2025 WRTA feed.
CORRIDOR_ROUTES = {
    "Orange": ("19", "27", "33"),
    "Blue": ("5", "12"),
    "Green": ("23", "26"),
}

# GTFS direction_id has agency-specific meaning.  Inspection of the headsigns
# for all seven WRTA routes shows that 0 leaves Hub Center and 1 approaches it.
DIRECTION_NAMES = {"0": "outbound", "1": "inbound"}
SERVICE_TYPES = ("weekday", "saturday", "sunday")
CALENDAR_DAY_COLUMNS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


@dataclass(frozen=True)
class CorridorStop:
    stop_id: str
    latitude: str
    longitude: str


@dataclass(frozen=True)
class Trip:
    route_id: str
    service_id: str
    direction_id: str


@dataclass(frozen=True)
class ScheduledArrival:
    seconds: int
    route_id: str


@dataclass(frozen=True)
class HeadwaySummary:
    service_day_count: int
    total_arrivals: int
    mean_arrivals_per_service_day: float | None
    headway_observation_count: int
    mean_headway_minutes: float | None
    headway_variance_minutes_squared: float | None
    expected_wait_minutes: float | None
    routes: tuple[str, ...]
    first_arrival_seconds: int | None
    last_arrival_seconds: int | None


@dataclass
class RidershipSummary:
    """Raw-sum ridership totals and their shared weighted denominator."""

    record_count: int = 0
    trip_count: Decimal = Decimal(0)
    total_boardings: Decimal = Decimal(0)
    total_disembarkings: Decimal = Decimal(0)

    @property
    def average_boardings(self) -> Decimal | None:
        if self.trip_count <= 0:
            return None
        return self.total_boardings / self.trip_count

    @property
    def average_disembarkings(self) -> Decimal | None:
        if self.trip_count <= 0:
            return None
        return self.total_disembarkings / self.trip_count


def read_csv_rows(path: Path) -> Iterable[dict[str, str]]:
    """Yield rows from a UTF-8 GTFS or processed CSV file."""
    if not path.is_file():
        raise FileNotFoundError(f"Required input file not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        yield from csv.DictReader(input_file)


def xlsx_column_index(cell_reference: str) -> int:
    """Convert an Excel cell reference such as AA12 to a zero-based column."""
    letters = "".join(character for character in cell_reference if character.isalpha())
    if not letters:
        raise ValueError(f"Invalid XLSX cell reference: {cell_reference!r}")

    index = 0
    for letter in letters.upper():
        index = index * 26 + ord(letter) - ord("A") + 1
    return index - 1


def xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    """Read a string or numeric value from an XLSX worksheet cell."""
    if cell.get("t") == "inlineStr":
        return "".join(
            text.text or "" for text in cell.findall(".//main:t", XLSX_NAMESPACE)
        )

    value = cell.find("main:v", XLSX_NAMESPACE)
    if value is None or value.text is None:
        return ""
    if cell.get("t") == "s":
        return shared_strings[int(value.text)]
    return value.text


def read_xlsx_rows(path: Path) -> tuple[dict[str, str], ...]:
    """Read the first worksheet using only the Python standard library."""
    if not path.is_file():
        raise FileNotFoundError(f"Required ridership workbook not found: {path}")

    with ZipFile(path) as workbook:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            shared_xml = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(
                    text.text or ""
                    for text in item.findall(".//main:t", XLSX_NAMESPACE)
                )
                for item in shared_xml.findall("main:si", XLSX_NAMESPACE)
            ]

        sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        worksheet_rows = sheet.findall(
            ".//main:sheetData/main:row", XLSX_NAMESPACE
        )

        if not worksheet_rows:
            return ()

        headers = {
            xlsx_column_index(cell.get("r", "")): xlsx_cell_value(
                cell, shared_strings
            )
            for cell in worksheet_rows[0].findall("main:c", XLSX_NAMESPACE)
        }
        return tuple(
            {
                headers[column_index]: xlsx_cell_value(cell, shared_strings)
                for cell in worksheet_row.findall("main:c", XLSX_NAMESPACE)
                if (column_index := xlsx_column_index(cell.get("r", "")))
                in headers
            }
            for worksheet_row in worksheet_rows[1:]
        )


def parse_decimal(value: str, field_name: str, source_path: Path) -> Decimal:
    """Parse a finite workbook number, treating an empty numeric cell as zero."""
    value = (value or "").strip()
    if not value:
        return Decimal(0)
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(
            f"Invalid {field_name} value {value!r} in {source_path}"
        ) from error
    if not parsed.is_finite():
        raise ValueError(f"Non-finite {field_name} value {value!r} in {source_path}")
    return parsed


def load_ridership_summaries(
    ridership_dir: Path,
) -> dict[tuple[str, str, str, str], RidershipSummary]:
    """Sum ridership by service type, corridor, direction, and stop."""
    route_to_corridor = {
        route: corridor
        for corridor, routes in CORRIDOR_ROUTES.items()
        for route in routes
    }
    summaries: dict[tuple[str, str, str, str], RidershipSummary] = {}
    required_fields = {
        "ROUTE_NUMBER",
        "DIRECTION_NAME",
        "STOP_ID",
        "SUM_PASSENGERS_ON",
        "SUM_PASSENGERS_OFF",
        "TRIPS_COUNT",
    }

    for service_type, filename in RIDERSHIP_FILENAMES.items():
        source_path = ridership_dir / filename
        rows = read_xlsx_rows(source_path)
        if not rows:
            raise ValueError(f"Ridership workbook contains no data rows: {source_path}")

        missing_fields = required_fields - set(rows[0])
        if missing_fields:
            raise ValueError(
                f"Ridership workbook {source_path} is missing columns: "
                f"{sorted(missing_fields)}"
            )

        for row in rows:
            route = row.get("ROUTE_NUMBER", "").strip()
            corridor = route_to_corridor.get(route)
            if corridor is None:
                continue

            direction = row.get("DIRECTION_NAME", "").strip().lower()
            if direction not in DIRECTION_NAMES.values():
                continue

            stop_id = row.get("STOP_ID", "").strip()
            if not stop_id:
                raise ValueError(
                    f"A target-route ridership row has no STOP_ID in {source_path}"
                )

            key = (service_type, corridor, direction, stop_id)
            summary = summaries.setdefault(key, RidershipSummary())
            summary.record_count += 1
            summary.trip_count += parse_decimal(
                row.get("TRIPS_COUNT", ""), "TRIPS_COUNT", source_path
            )
            summary.total_boardings += parse_decimal(
                row.get("SUM_PASSENGERS_ON", ""),
                "SUM_PASSENGERS_ON",
                source_path,
            )
            summary.total_disembarkings += parse_decimal(
                row.get("SUM_PASSENGERS_OFF", ""),
                "SUM_PASSENGERS_OFF",
                source_path,
            )

    return summaries


def parse_gtfs_date(value: str) -> date:
    """Parse the YYYYMMDD date format used by GTFS."""
    value = value.strip()
    if len(value) != 8 or not value.isdigit():
        raise ValueError(f"Invalid GTFS date: {value!r}")
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def parse_gtfs_time(value: str) -> int:
    """Return seconds after service-day midnight; GTFS permits hours >= 24."""
    try:
        hours, minutes, seconds = (int(part) for part in value.strip().split(":"))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid GTFS time: {value!r}") from error

    if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
        raise ValueError(f"Invalid GTFS time: {value!r}")
    return hours * 3600 + minutes * 60 + seconds


def format_gtfs_time(seconds: int | None) -> str:
    """Format seconds after service-day midnight without wrapping after 24:00."""
    if seconds is None:
        return ""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def service_type_for_date(service_date: date) -> str:
    if service_date.weekday() < 5:
        return "weekday"
    if service_date.weekday() == 5:
        return "saturday"
    return "sunday"


def load_corridor_stops(corridor_dir: Path) -> dict[str, list[CorridorStop]]:
    """Load the processed stop membership and coordinates for each corridor."""
    corridor_stops: dict[str, list[CorridorStop]] = {}

    for corridor in CORRIDOR_ROUTES:
        path = corridor_dir / f"{corridor}_corridor_shared_stops.csv"
        stops: list[CorridorStop] = []
        seen_stop_ids: set[str] = set()

        for row in read_csv_rows(path):
            stop_id = row.get("stop_id", "").strip()
            if not stop_id:
                raise ValueError(f"A row in {path} has no stop_id")
            if stop_id in seen_stop_ids:
                raise ValueError(f"Duplicate stop_id {stop_id!r} in {path}")
            seen_stop_ids.add(stop_id)
            stops.append(
                CorridorStop(
                    stop_id=stop_id,
                    latitude=row.get("latitude", "").strip(),
                    longitude=row.get("longitude", "").strip(),
                )
            )

        if not stops:
            raise ValueError(f"No corridor stops found in {path}")
        corridor_stops[corridor] = stops

    return corridor_stops


def load_service_dates(gtfs_dir: Path) -> list[tuple[date, str, frozenset[str]]]:
    """Expand GTFS calendars into dates, service types, and active service IDs."""
    calendar_rows = list(read_csv_rows(gtfs_dir / "calendar.txt"))
    exception_rows = list(read_csv_rows(gtfs_dir / "calendar_dates.txt"))
    if not calendar_rows and not exception_rows:
        raise ValueError("GTFS calendar.txt and calendar_dates.txt contain no service")

    calendar_services: list[tuple[dict[str, str], date, date]] = []
    all_dates: list[date] = []
    for row in calendar_rows:
        start_date = parse_gtfs_date(row["start_date"])
        end_date = parse_gtfs_date(row["end_date"])
        if end_date < start_date:
            raise ValueError(
                f"Service {row['service_id']!r} ends before it starts in calendar.txt"
            )
        calendar_services.append((row, start_date, end_date))
        all_dates.extend((start_date, end_date))

    exceptions_by_date: dict[date, list[tuple[str, str]]] = defaultdict(list)
    for row in exception_rows:
        exception_date = parse_gtfs_date(row["date"])
        exception_type = row["exception_type"].strip()
        if exception_type not in {"1", "2"}:
            raise ValueError(
                f"Unknown calendar exception_type {exception_type!r} on {exception_date}"
            )
        exceptions_by_date[exception_date].append(
            (row["service_id"].strip(), exception_type)
        )
        all_dates.append(exception_date)

    first_date = min(all_dates)
    last_date = max(all_dates)
    expanded_dates: list[tuple[date, str, frozenset[str]]] = []
    current_date = first_date

    while current_date <= last_date:
        weekday_column = CALENDAR_DAY_COLUMNS[current_date.weekday()]
        active_services = {
            row["service_id"].strip()
            for row, start_date, end_date in calendar_services
            if start_date <= current_date <= end_date
            and row.get(weekday_column, "0").strip() == "1"
        }

        for service_id, exception_type in exceptions_by_date.get(current_date, []):
            if exception_type == "1":
                active_services.add(service_id)
            else:
                active_services.discard(service_id)

        expanded_dates.append(
            (
                current_date,
                service_type_for_date(current_date),
                frozenset(active_services),
            )
        )
        current_date += timedelta(days=1)

    return expanded_dates


def load_target_trips(gtfs_dir: Path) -> dict[str, Trip]:
    """Load trips belonging to one of the configured corridor routes."""
    target_routes = {route for routes in CORRIDOR_ROUTES.values() for route in routes}
    trips: dict[str, Trip] = {}

    for row in read_csv_rows(gtfs_dir / "trips.txt"):
        route_id = row["route_id"].strip()
        if route_id not in target_routes:
            continue

        direction_id = row.get("direction_id", "").strip()
        if direction_id not in DIRECTION_NAMES:
            raise ValueError(
                f"Target trip {row['trip_id']!r} has unsupported direction_id "
                f"{direction_id!r}"
            )
        trips[row["trip_id"].strip()] = Trip(
            route_id=route_id,
            service_id=row["service_id"].strip(),
            direction_id=direction_id,
        )

    routes_found = {trip.route_id for trip in trips.values()}
    missing_routes = sorted(target_routes - routes_found)
    if missing_routes:
        raise ValueError(f"No GTFS trips found for corridor routes: {missing_routes}")
    return trips


def load_scheduled_arrivals(
    gtfs_dir: Path,
    trips: dict[str, Trip],
    corridor_stops: dict[str, list[CorridorStop]],
) -> tuple[
    dict[tuple[str, str, str, str], list[ScheduledArrival]],
    dict[tuple[str, str, str], list[tuple[int, str]]],
]:
    """Load target arrivals and trip stop sequences in one pass over stop_times."""
    stops_by_corridor = {
        corridor: {stop.stop_id for stop in stops}
        for corridor, stops in corridor_stops.items()
    }
    route_stops: dict[str, set[str]] = defaultdict(set)
    arrivals: dict[
        tuple[str, str, str, str], list[ScheduledArrival]
    ] = defaultdict(list)
    trip_sequences: dict[
        tuple[str, str, str], list[tuple[int, str]]
    ] = defaultdict(list)

    route_to_corridor = {
        route: corridor
        for corridor, routes in CORRIDOR_ROUTES.items()
        for route in routes
    }

    for row in read_csv_rows(gtfs_dir / "stop_times.txt"):
        trip_id = row["trip_id"].strip()
        trip = trips.get(trip_id)
        if trip is None:
            continue

        stop_id = row["stop_id"].strip()
        route_stops[trip.route_id].add(stop_id)
        corridor = route_to_corridor[trip.route_id]
        if stop_id not in stops_by_corridor[corridor]:
            continue

        arrival_time = row.get("arrival_time", "").strip()
        departure_time = row.get("departure_time", "").strip()
        time_value = arrival_time or departure_time
        if not time_value:
            raise ValueError(
                f"Trip {trip_id!r}, stop {stop_id!r} has neither arrival nor departure time"
            )

        key = (trip.service_id, corridor, trip.direction_id, stop_id)
        arrivals[key].append(
            ScheduledArrival(parse_gtfs_time(time_value), trip.route_id)
        )
        trip_sequences[(corridor, trip.direction_id, trip_id)].append(
            (int(row["stop_sequence"]), stop_id)
        )

    # The processed files are intended to contain the intersection of stops
    # served by every route in a corridor.  Fail loudly if the two inputs drift.
    for corridor, routes in CORRIDOR_ROUTES.items():
        listed_stop_ids = stops_by_corridor[corridor]
        for route in routes:
            unserved = listed_stop_ids - route_stops[route]
            if unserved:
                raise ValueError(
                    f"{corridor} corridor file contains stops not served by route "
                    f"{route}: {sorted(unserved)}"
                )

    if not arrivals:
        raise ValueError("No scheduled arrivals matched the processed corridor stops")
    return dict(arrivals), dict(trip_sequences)


def stop_order_for_direction(
    corridor: str,
    direction_id: str,
    stop_ids: set[str],
    trips: dict[str, Trip],
    trip_sequences: dict[tuple[str, str, str], list[tuple[int, str]]],
) -> dict[str, int]:
    """Order stops using the trip covering the most corridor stops."""
    candidates: list[tuple[int, int, str, list[str]]] = []
    route_priority = {
        route: index for index, route in enumerate(CORRIDOR_ROUTES[corridor])
    }

    for (trip_corridor, trip_direction, trip_id), sequence_rows in trip_sequences.items():
        if trip_corridor != corridor or trip_direction != direction_id:
            continue

        ordered_ids: list[str] = []
        seen: set[str] = set()
        for _, stop_id in sorted(sequence_rows):
            if stop_id in stop_ids and stop_id not in seen:
                ordered_ids.append(stop_id)
                seen.add(stop_id)
        if ordered_ids:
            candidates.append(
                (
                    -len(ordered_ids),
                    route_priority[trips[trip_id].route_id],
                    trip_id,
                    ordered_ids,
                )
            )

    if not candidates:
        return {stop_id: index for index, stop_id in enumerate(sorted(stop_ids), start=1)}

    _, _, _, best_order = min(candidates)
    missing_stop_ids = stop_ids - set(best_order)
    if missing_stop_ids:
        # This should not occur for shared-corridor stops.  Keep the output
        # complete and deterministic if a future feed contains short turns.
        best_order.extend(sorted(missing_stop_ids))
    return {stop_id: index for index, stop_id in enumerate(best_order, start=1)}


def summarize_stop_headways(
    corridor: str,
    direction_id: str,
    stop_id: str,
    service_type: str,
    service_dates: list[tuple[date, str, frozenset[str]]],
    arrivals: dict[tuple[str, str, str, str], list[ScheduledArrival]],
) -> HeadwaySummary:
    """Pool within-day headways over all dates in one service-type category."""
    headways_minutes: list[float] = []
    routes: set[str] = set()
    service_day_count = 0
    total_arrivals = 0
    first_arrival_seconds: int | None = None
    last_arrival_seconds: int | None = None

    for _, date_service_type, active_service_ids in service_dates:
        if date_service_type != service_type:
            continue

        daily_arrivals = sorted(
            (
                scheduled_arrival
                for service_id in active_service_ids
                for scheduled_arrival in arrivals.get(
                    (service_id, corridor, direction_id, stop_id), []
                )
            ),
            key=lambda scheduled_arrival: scheduled_arrival.seconds,
        )
        if not daily_arrivals:
            continue

        service_day_count += 1
        total_arrivals += len(daily_arrivals)
        routes.update(arrival.route_id for arrival in daily_arrivals)
        daily_times = [arrival.seconds for arrival in daily_arrivals]
        first_arrival_seconds = (
            daily_times[0]
            if first_arrival_seconds is None
            else min(first_arrival_seconds, daily_times[0])
        )
        last_arrival_seconds = (
            daily_times[-1]
            if last_arrival_seconds is None
            else max(last_arrival_seconds, daily_times[-1])
        )
        headways_minutes.extend(
            (later - earlier) / 60
            for earlier, later in zip(daily_times, daily_times[1:])
        )

    mean_arrivals = (
        total_arrivals / service_day_count if service_day_count else None
    )
    if headways_minutes:
        mean_headway = statistics.fmean(headways_minutes)
        headway_variance = statistics.pvariance(headways_minutes)
        expected_wait = (
            mean_headway / 2 + headway_variance / (2 * mean_headway)
            if mean_headway > 0
            else None
        )
    else:
        mean_headway = None
        headway_variance = None
        expected_wait = None

    return HeadwaySummary(
        service_day_count=service_day_count,
        total_arrivals=total_arrivals,
        mean_arrivals_per_service_day=mean_arrivals,
        headway_observation_count=len(headways_minutes),
        mean_headway_minutes=mean_headway,
        headway_variance_minutes_squared=headway_variance,
        expected_wait_minutes=expected_wait,
        routes=tuple(
            sorted(
                routes,
                key=lambda route: (
                    (0, int(route)) if route.isdigit() else (1, route)
                ),
            )
        ),
        first_arrival_seconds=first_arrival_seconds,
        last_arrival_seconds=last_arrival_seconds,
    )


def format_number(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return ""
    return f"{value:.6f}"


def format_decimal(value: Decimal | None) -> str:
    """Format ridership measures consistently without converting through float."""
    if value is None or not value.is_finite():
        return ""
    return f"{value:.6f}"


def format_decimal_count(value: Decimal) -> str:
    """Keep an integral trip denominator readable while supporting factored data."""
    if value == value.to_integral_value():
        return str(int(value))
    return format_decimal(value)


def calculation_status(summary: HeadwaySummary) -> str:
    """Explain why a row does or does not contain headway statistics."""
    if summary.service_day_count == 0:
        return "no_service"
    if summary.headway_observation_count == 0:
        return "insufficient_daily_arrivals"
    return "ok"


def ridership_calculation_status(summary: RidershipSummary) -> str:
    if summary.record_count == 0:
        return "no_matching_ridership_record"
    if summary.trip_count <= 0:
        return "no_positive_trip_count"
    return "ok"


def write_output_files(
    output_dir: Path,
    corridor_stops: dict[str, list[CorridorStop]],
    trips: dict[str, Trip],
    service_dates: list[tuple[date, str, frozenset[str]]],
    arrivals: dict[tuple[str, str, str, str], list[ScheduledArrival]],
    trip_sequences: dict[tuple[str, str, str], list[tuple[int, str]]],
    ridership_summaries: dict[tuple[str, str, str, str], RidershipSummary],
) -> list[Path]:
    """Write all corridor x direction x service-type result files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[Path] = []
    fieldnames = [
        "stop_order",
        "stop_id",
        "latitude",
        "longitude",
        "corridor",
        "direction",
        "gtfs_direction_id",
        "service_type",
        "routes",
        "ridership_calculation_status",
        "ridership_record_count",
        "ridership_trip_count",
        "average_boardings",
        "average_disembarkings",
        "total_boardings",
        "total_disembarkings",
        "calculation_status",
        "service_day_count",
        "total_arrivals",
        "mean_arrivals_per_service_day",
        "headway_observation_count",
        "mean_headway_minutes",
        "headway_variance_minutes_squared",
        "expected_wait_minutes",
        "first_arrival_time",
        "last_arrival_time",
    ]

    for corridor, stops in corridor_stops.items():
        stop_lookup = {stop.stop_id: stop for stop in stops}
        for direction_id, direction_name in DIRECTION_NAMES.items():
            direction_stop_ids = {
                key_stop_id
                for _, key_corridor, key_direction, key_stop_id in arrivals
                if key_corridor == corridor and key_direction == direction_id
            }
            stop_order = stop_order_for_direction(
                corridor,
                direction_id,
                direction_stop_ids,
                trips,
                trip_sequences,
            )

            for service_type in SERVICE_TYPES:
                output_path = output_dir / (
                    f"{corridor}_{direction_name}_{service_type}_headways.csv"
                )
                output_paths.append(output_path)

                with output_path.open("w", encoding="utf-8", newline="") as output_file:
                    writer = csv.DictWriter(output_file, fieldnames=fieldnames)
                    writer.writeheader()

                    for stop_id in sorted(
                        direction_stop_ids, key=lambda value: stop_order[value]
                    ):
                        stop = stop_lookup[stop_id]
                        headway_summary = summarize_stop_headways(
                            corridor,
                            direction_id,
                            stop_id,
                            service_type,
                            service_dates,
                            arrivals,
                        )
                        ridership_summary = ridership_summaries.get(
                            (service_type, corridor, direction_name, stop_id),
                            RidershipSummary(),
                        )
                        writer.writerow(
                            {
                                "stop_order": stop_order[stop_id],
                                "stop_id": stop_id,
                                "latitude": stop.latitude,
                                "longitude": stop.longitude,
                                "corridor": corridor,
                                "direction": direction_name,
                                "gtfs_direction_id": direction_id,
                                "service_type": service_type,
                                "routes": ";".join(headway_summary.routes),
                                "ridership_calculation_status": (
                                    ridership_calculation_status(ridership_summary)
                                ),
                                "ridership_record_count": (
                                    ridership_summary.record_count
                                ),
                                "ridership_trip_count": format_decimal_count(
                                    ridership_summary.trip_count
                                ),
                                "average_boardings": format_decimal(
                                    ridership_summary.average_boardings
                                ),
                                "average_disembarkings": format_decimal(
                                    ridership_summary.average_disembarkings
                                ),
                                "total_boardings": format_decimal(
                                    ridership_summary.total_boardings
                                ),
                                "total_disembarkings": format_decimal(
                                    ridership_summary.total_disembarkings
                                ),
                                "calculation_status": calculation_status(
                                    headway_summary
                                ),
                                "service_day_count": (
                                    headway_summary.service_day_count
                                ),
                                "total_arrivals": headway_summary.total_arrivals,
                                "mean_arrivals_per_service_day": format_number(
                                    headway_summary.mean_arrivals_per_service_day
                                ),
                                "headway_observation_count": (
                                    headway_summary.headway_observation_count
                                ),
                                "mean_headway_minutes": format_number(
                                    headway_summary.mean_headway_minutes
                                ),
                                "headway_variance_minutes_squared": format_number(
                                    headway_summary.headway_variance_minutes_squared
                                ),
                                "expected_wait_minutes": format_number(
                                    headway_summary.expected_wait_minutes
                                ),
                                "first_arrival_time": format_gtfs_time(
                                    headway_summary.first_arrival_seconds
                                ),
                                "last_arrival_time": format_gtfs_time(
                                    headway_summary.last_arrival_seconds
                                ),
                            }
                        )

    return output_paths


def aggregate_data(
    gtfs_dir: str | Path = DEFAULT_GTFS_DIR,
    corridor_dir: str | Path = DEFAULT_CORRIDOR_DIR,
    ridership_dir: str | Path = DEFAULT_RIDERSHIP_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> list[Path]:
    """Calculate and write every corridor headway output; return written paths."""
    gtfs_dir = Path(gtfs_dir).resolve()
    corridor_dir = Path(corridor_dir).resolve()
    ridership_dir = Path(ridership_dir).resolve()
    output_dir = Path(output_dir).resolve()

    corridor_stops = load_corridor_stops(corridor_dir)
    ridership_summaries = load_ridership_summaries(ridership_dir)
    service_dates = load_service_dates(gtfs_dir)
    trips = load_target_trips(gtfs_dir)
    arrivals, trip_sequences = load_scheduled_arrivals(
        gtfs_dir, trips, corridor_stops
    )
    return write_output_files(
        output_dir,
        corridor_stops,
        trips,
        service_dates,
        arrivals,
        trip_sequences,
        ridership_summaries,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gtfs-dir",
        type=Path,
        default=DEFAULT_GTFS_DIR,
        help=f"GTFS directory (default: {DEFAULT_GTFS_DIR})",
    )
    parser.add_argument(
        "--corridor-dir",
        type=Path,
        default=DEFAULT_CORRIDOR_DIR,
        help=f"Processed corridor-stop directory (default: {DEFAULT_CORRIDOR_DIR})",
    )
    parser.add_argument(
        "--ridership-dir",
        type=Path,
        default=DEFAULT_RIDERSHIP_DIR,
        help=f"Ridership workbook directory (default: {DEFAULT_RIDERSHIP_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output CSV directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    written_paths = aggregate_data(
        gtfs_dir=arguments.gtfs_dir,
        corridor_dir=arguments.corridor_dir,
        ridership_dir=arguments.ridership_dir,
        output_dir=arguments.output_dir,
    )
    print(f"Wrote {len(written_paths)} files:")
    for written_path in written_paths:
        print(f"  {written_path}")
