"""Aggregate August 2024 corridor service and ridership by time of day.

This is the time-period counterpart to ``aggregate_data.py``.  It combines the
GTFS feed ending August 23 with the replacement feed beginning August 24, then
calculates headways independently within each service date and time period.
Overnight and cross-period gaps are not counted as headways.

Ridership comes from the August 2024 time-period workbook.  Boardings and
disembarkings are summed from ``SUM_PASSENGERS_ON`` and
``SUM_PASSENGERS_OFF``.  Their per-trip averages are calculated from those
totals divided by the summed ``TRIPS_COUNT``; precomputed workbook averages are
not used.

Run from the repository root with::

    python simplified_model/aggregate_data_2024.py
"""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

if __package__:
    from .aggregate_data import (
        CORRIDOR_ROUTES,
        DIRECTION_NAMES,
        HeadwaySummary,
        RidershipSummary,
        ScheduledArrival,
        Trip,
        calculation_status,
        format_decimal,
        format_decimal_count,
        format_gtfs_time,
        format_number,
        load_corridor_stops,
        load_scheduled_arrivals,
        load_service_dates,
        load_target_trips,
        parse_decimal,
        read_xlsx_rows,
        ridership_calculation_status,
        stop_order_for_direction,
    )
else:
    from aggregate_data import (
        CORRIDOR_ROUTES,
        DIRECTION_NAMES,
        HeadwaySummary,
        RidershipSummary,
        ScheduledArrival,
        Trip,
        calculation_status,
        format_decimal,
        format_decimal_count,
        format_gtfs_time,
        format_number,
        load_corridor_stops,
        load_scheduled_arrivals,
        load_service_dates,
        load_target_trips,
        parse_decimal,
        read_xlsx_rows,
        ridership_calculation_status,
        stop_order_for_direction,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
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
DEFAULT_CORRIDOR_DIR = (
    PROJECT_ROOT / "data" / "processed" / "stops_organized_data_2024"
)
DEFAULT_RIDERSHIP_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "ridership_data_august_2024"
    / "AUGUST 2024 RIDERSHIP BY TIME PERIOD, ROUTE AND STOP (DATAVIEW).XLSX"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "2024_headway_aggregate"
AUGUST_START = date(2024, 8, 1)
AUGUST_END = date(2024, 8, 31)


@dataclass(frozen=True)
class TimePeriod:
    name: str
    slug: str
    start_seconds: int
    end_seconds: int

    def contains(self, arrival_seconds: int) -> bool:
        """Test clock time using an inclusive start and exclusive end."""
        clock_seconds = arrival_seconds % (24 * 60 * 60)
        return self.start_seconds <= clock_seconds < self.end_seconds

    @property
    def start_time(self) -> str:
        return format_gtfs_time(self.start_seconds)

    @property
    def end_time(self) -> str:
        # Display the final included minute/second rather than the next period.
        return format_gtfs_time(self.end_seconds - 1)


# Boundaries match data/raw/ridership_data_august_2024/Time Period Settings.jpg.
# The workbook contains no "Other" (midnight-03:59) records, and WRTA has no
# scheduled corridor service in that period, so only its six observed periods
# are emitted.
TIME_PERIODS = (
    TimePeriod("AM Early", "am_early", 4 * 3600, 6 * 3600),
    TimePeriod("AM Peak", "am_peak", 6 * 3600, 9 * 3600),
    TimePeriod("Midday", "midday", 9 * 3600, 15 * 3600),
    TimePeriod("PM Peak", "pm_peak", 15 * 3600, 18 * 3600),
    TimePeriod("PM Late", "pm_late", 18 * 3600, 22 * 3600),
    TimePeriod("PM Late Night", "pm_late_night", 22 * 3600, 24 * 3600),
)


@dataclass(frozen=True)
class FeedSchedule:
    gtfs_dir: Path
    trips: dict[str, Trip]
    arrivals: dict[tuple[str, str, str, str], list[ScheduledArrival]]
    trip_sequences: dict[tuple[str, str, str], list[tuple[int, str]]]
    service_dates: tuple[tuple[date, str, frozenset[str]], ...]


def august_dates() -> set[date]:
    current_date = AUGUST_START
    dates: set[date] = set()
    while current_date <= AUGUST_END:
        dates.add(current_date)
        current_date += timedelta(days=1)
    return dates


def load_feed_schedules(
    gtfs_dirs: tuple[Path, ...],
    corridor_stops,
) -> tuple[FeedSchedule, ...]:
    """Load both 2024 feeds and ensure they cover August exactly once."""
    feeds: list[FeedSchedule] = []
    date_counts: Counter[date] = Counter()

    for gtfs_dir in gtfs_dirs:
        gtfs_dir = gtfs_dir.resolve()
        trips = load_target_trips(gtfs_dir)
        arrivals, trip_sequences = load_scheduled_arrivals(
            gtfs_dir, trips, corridor_stops
        )
        service_dates = tuple(
            service_date
            for service_date in load_service_dates(gtfs_dir)
            if AUGUST_START <= service_date[0] <= AUGUST_END
        )
        if not service_dates:
            raise ValueError(f"GTFS feed has no August 2024 dates: {gtfs_dir}")
        date_counts.update(service_date for service_date, _, _ in service_dates)
        feeds.append(
            FeedSchedule(
                gtfs_dir=gtfs_dir,
                trips=trips,
                arrivals=arrivals,
                trip_sequences=trip_sequences,
                service_dates=service_dates,
            )
        )

    missing_dates = august_dates() - set(date_counts)
    duplicate_dates = sorted(
        service_date for service_date, count in date_counts.items() if count != 1
    )
    if missing_dates or duplicate_dates:
        raise ValueError(
            "The supplied GTFS feeds do not partition August 2024 exactly; "
            f"missing={sorted(missing_dates)}, duplicate={duplicate_dates}"
        )
    return tuple(feeds)


def load_2024_ridership(
    ridership_path: Path,
) -> dict[tuple[str, str, str, str], RidershipSummary]:
    """Sum workbook records by time period, corridor, direction, and stop."""
    rows = read_xlsx_rows(ridership_path)
    if not rows:
        raise ValueError(f"Ridership workbook contains no rows: {ridership_path}")

    required_fields = {
        "TIME_PERIOD",
        "ROUTE_NUMBER",
        "DIRECTION_NAME",
        "STOP_ID",
        "SUM_PASSENGERS_ON",
        "SUM_PASSENGERS_OFF",
        "TRIPS_COUNT",
    }
    missing_fields = required_fields - set(rows[0])
    if missing_fields:
        raise ValueError(
            f"Ridership workbook {ridership_path} is missing columns: "
            f"{sorted(missing_fields)}"
        )

    route_to_corridor = {
        route: corridor
        for corridor, routes in CORRIDOR_ROUTES.items()
        for route in routes
    }
    period_names = {period.name for period in TIME_PERIODS}
    summaries: dict[tuple[str, str, str, str], RidershipSummary] = {}

    for row in rows:
        route = row.get("ROUTE_NUMBER", "").strip()
        corridor = route_to_corridor.get(route)
        if corridor is None:
            continue

        direction = row.get("DIRECTION_NAME", "").strip().lower()
        if direction not in DIRECTION_NAMES.values():
            continue

        time_period = row.get("TIME_PERIOD", "").strip()
        if time_period not in period_names:
            raise ValueError(
                f"Unknown target-route time period {time_period!r} in {ridership_path}"
            )
        stop_id = row.get("STOP_ID", "").strip()
        if not stop_id:
            raise ValueError(f"Target-route ridership row has no STOP_ID: {row}")

        key = (time_period, corridor, direction, stop_id)
        summary = summaries.setdefault(key, RidershipSummary())
        summary.record_count += 1
        summary.trip_count += parse_decimal(
            row.get("TRIPS_COUNT", ""), "TRIPS_COUNT", ridership_path
        )
        summary.total_boardings += parse_decimal(
            row.get("SUM_PASSENGERS_ON", ""),
            "SUM_PASSENGERS_ON",
            ridership_path,
        )
        summary.total_disembarkings += parse_decimal(
            row.get("SUM_PASSENGERS_OFF", ""),
            "SUM_PASSENGERS_OFF",
            ridership_path,
        )

    return summaries


def summarize_time_period_headways(
    feeds: tuple[FeedSchedule, ...],
    corridor: str,
    direction_id: str,
    stop_id: str,
    time_period: TimePeriod,
) -> HeadwaySummary:
    """Pool within-day, within-period headways over August 2024."""
    headways_minutes: list[float] = []
    routes: set[str] = set()
    operating_day_count = 0
    total_arrivals = 0
    first_arrival_seconds: int | None = None
    last_arrival_seconds: int | None = None

    for feed in feeds:
        for _, _, active_service_ids in feed.service_dates:
            daily_arrivals = sorted(
                (
                    scheduled_arrival
                    for service_id in active_service_ids
                    for scheduled_arrival in feed.arrivals.get(
                        (service_id, corridor, direction_id, stop_id), []
                    )
                    if time_period.contains(scheduled_arrival.seconds)
                ),
                key=lambda scheduled_arrival: scheduled_arrival.seconds,
            )
            if not daily_arrivals:
                continue

            operating_day_count += 1
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
        total_arrivals / operating_day_count if operating_day_count else None
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
        service_day_count=operating_day_count,
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


def direction_stop_ids(
    feeds: tuple[FeedSchedule, ...], corridor: str, direction_id: str
) -> set[str]:
    return {
        stop_id
        for feed in feeds
        for _, key_corridor, key_direction, stop_id in feed.arrivals
        if key_corridor == corridor and key_direction == direction_id
    }


def write_output_files(
    output_dir: Path,
    corridor_stops,
    feeds: tuple[FeedSchedule, ...],
    ridership_summaries: dict[tuple[str, str, str, str], RidershipSummary],
) -> list[Path]:
    """Write one CSV per corridor, direction, and observed time period."""
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
        "time_period",
        "time_period_start",
        "time_period_end",
        "routes",
        "ridership_calculation_status",
        "ridership_record_count",
        "ridership_trip_count",
        "average_boardings",
        "average_disembarkings",
        "total_boardings",
        "total_disembarkings",
        "calculation_status",
        "operating_day_count",
        "total_arrivals",
        "mean_arrivals_per_operating_day",
        "headway_observation_count",
        "mean_headway_minutes",
        "headway_variance_minutes_squared",
        "expected_wait_minutes",
        "first_arrival_time",
        "last_arrival_time",
    ]

    ordering_feed = feeds[0]
    for corridor, stops in corridor_stops.items():
        stop_lookup = {stop.stop_id: stop for stop in stops}
        for direction_id, direction_name in DIRECTION_NAMES.items():
            stop_ids = direction_stop_ids(feeds, corridor, direction_id)
            stop_order = stop_order_for_direction(
                corridor,
                direction_id,
                stop_ids,
                ordering_feed.trips,
                ordering_feed.trip_sequences,
            )

            for time_period in TIME_PERIODS:
                output_path = output_dir / (
                    f"{corridor}_{direction_name}_{time_period.slug}_headways.csv"
                )
                output_paths.append(output_path)
                with output_path.open("w", encoding="utf-8", newline="") as output_file:
                    writer = csv.DictWriter(output_file, fieldnames=fieldnames)
                    writer.writeheader()

                    for stop_id in sorted(stop_ids, key=lambda value: stop_order[value]):
                        stop = stop_lookup[stop_id]
                        headway_summary = summarize_time_period_headways(
                            feeds,
                            corridor,
                            direction_id,
                            stop_id,
                            time_period,
                        )
                        ridership_summary = ridership_summaries.get(
                            (time_period.name, corridor, direction_name, stop_id),
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
                                "time_period": time_period.name,
                                "time_period_start": time_period.start_time,
                                "time_period_end": time_period.end_time,
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
                                "operating_day_count": (
                                    headway_summary.service_day_count
                                ),
                                "total_arrivals": headway_summary.total_arrivals,
                                "mean_arrivals_per_operating_day": format_number(
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


def aggregate_data_2024(
    gtfs_dirs: tuple[str | Path, ...] = DEFAULT_GTFS_DIRS,
    corridor_dir: str | Path = DEFAULT_CORRIDOR_DIR,
    ridership_path: str | Path = DEFAULT_RIDERSHIP_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> list[Path]:
    """Calculate and write all August 2024 time-period aggregates."""
    resolved_gtfs_dirs = tuple(Path(path).resolve() for path in gtfs_dirs)
    corridor_dir = Path(corridor_dir).resolve()
    ridership_path = Path(ridership_path).resolve()
    output_dir = Path(output_dir).resolve()

    corridor_stops = load_corridor_stops(corridor_dir)
    feeds = load_feed_schedules(resolved_gtfs_dirs, corridor_stops)
    ridership_summaries = load_2024_ridership(ridership_path)
    return write_output_files(
        output_dir,
        corridor_stops,
        feeds,
        ridership_summaries,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gtfs-dir",
        type=Path,
        action="append",
        dest="gtfs_dirs",
        help=(
            "GTFS directory; repeat for each feed. Defaults to the two August "
            "2024 feeds."
        ),
    )
    parser.add_argument(
        "--corridor-dir",
        type=Path,
        default=DEFAULT_CORRIDOR_DIR,
        help=f"Processed corridor-stop directory (default: {DEFAULT_CORRIDOR_DIR})",
    )
    parser.add_argument(
        "--ridership-path",
        type=Path,
        default=DEFAULT_RIDERSHIP_PATH,
        help=f"Time-period ridership workbook (default: {DEFAULT_RIDERSHIP_PATH})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output CSV directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    written_paths = aggregate_data_2024(
        gtfs_dirs=tuple(arguments.gtfs_dirs or DEFAULT_GTFS_DIRS),
        corridor_dir=arguments.corridor_dir,
        ridership_path=arguments.ridership_path,
        output_dir=arguments.output_dir,
    )
    print(f"Wrote {len(written_paths)} files:")
    for written_path in written_paths:
        print(f"  {written_path}")


if __name__ == "__main__":
    main()
