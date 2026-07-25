"""Display Union Station waits before and after schedule regularization.

The calculation uses the same August 2024 GTFS feeds, corridor route groups,
time blocks, and random-arrival wait formula as the non-capital-investment
projection.  For each corridor and time block:

* ``expected before`` is ``mean_headway / 2 + variance / (2 * mean_headway)``;
* ``expected after`` is half the mean headway, representing evenly spaced
  service with the same average frequency;
* ``worst before`` is the longest scheduled within-day headway observed; and
* ``worst after`` is the even headway at the same average frequency.

Expected waits are averaged equally across usable inbound and outbound records,
matching the projection's treatment of multiple service records at stop 1503.
Worst-case waits use the larger direction-specific value.

Run from the repository root with::

    python simplified_model/last_min_display_wait_times.py
"""

from __future__ import annotations

import argparse
import statistics
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from .aggregate_data import CORRIDOR_ROUTES, DIRECTION_NAMES, load_corridor_stops
    from .aggregate_data_2024 import (
        DEFAULT_CORRIDOR_DIR,
        DEFAULT_GTFS_DIRS,
        TIME_PERIODS,
        FeedSchedule,
        TimePeriod,
        load_feed_schedules,
    )
else:
    from aggregate_data import CORRIDOR_ROUTES, DIRECTION_NAMES, load_corridor_stops
    from aggregate_data_2024 import (
        DEFAULT_CORRIDOR_DIR,
        DEFAULT_GTFS_DIRS,
        TIME_PERIODS,
        FeedSchedule,
        TimePeriod,
        load_feed_schedules,
    )


UNION_STATION_STOP_ID = "1503"


@dataclass(frozen=True)
class DirectionWaits:
    """Wait measures for one corridor, direction, and time block."""

    expected_before_minutes: float
    expected_after_minutes: float
    worst_before_minutes: float
    worst_after_minutes: float


@dataclass(frozen=True)
class CorridorWaits:
    """Direction-aggregated wait measures displayed in one table row."""

    corridor: str
    time_block: str
    expected_before_minutes: float | None
    expected_after_minutes: float | None
    worst_before_minutes: float | None
    worst_after_minutes: float | None
    usable_direction_count: int


def _time_block_label(time_period: TimePeriod) -> str:
    """Format a model time block using its display-style clock boundaries."""

    start_hour = (time_period.start_seconds // 3600) % 24
    start_minute = (time_period.start_seconds % 3600) // 60
    end_hour = (time_period.end_seconds // 3600) % 24
    end_minute = (time_period.end_seconds % 3600) // 60
    return (
        f"{start_hour:02d}:{start_minute:02d} - "
        f"{end_hour:02d}:{end_minute:02d}"
    )


def _direction_headways(
    feeds: tuple[FeedSchedule, ...],
    corridor: str,
    direction_id: str,
    time_period: TimePeriod,
    stop_id: str,
) -> list[float]:
    """Return within-day scheduled headways in minutes for one service record."""

    headways: list[float] = []
    for feed in feeds:
        for _, _, active_service_ids in feed.service_dates:
            daily_arrivals = sorted(
                scheduled_arrival.seconds
                for service_id in active_service_ids
                for scheduled_arrival in feed.arrivals.get(
                    (service_id, corridor, direction_id, stop_id),
                    (),
                )
                if time_period.contains(scheduled_arrival.seconds)
            )
            headways.extend(
                (later - earlier) / 60
                for earlier, later in zip(
                    daily_arrivals,
                    daily_arrivals[1:],
                )
            )
    return headways


def _calculate_direction_waits(
    feeds: tuple[FeedSchedule, ...],
    corridor: str,
    direction_id: str,
    time_period: TimePeriod,
    stop_id: str,
) -> DirectionWaits | None:
    """Calculate before/after expected and worst-case waits for one direction."""

    headways = _direction_headways(
        feeds,
        corridor,
        direction_id,
        time_period,
        stop_id,
    )
    if not headways:
        return None

    mean_headway = statistics.fmean(headways)
    if mean_headway <= 0:
        return None
    headway_variance = statistics.pvariance(headways)
    expected_before = (
        mean_headway / 2 + headway_variance / (2 * mean_headway)
    )
    expected_after = mean_headway / 2
    return DirectionWaits(
        expected_before_minutes=expected_before,
        expected_after_minutes=expected_after,
        worst_before_minutes=max(headways),
        worst_after_minutes=mean_headway,
    )


def calculate_union_station_waits(
    gtfs_dirs: tuple[str | Path, ...] = DEFAULT_GTFS_DIRS,
    corridor_dir: str | Path = DEFAULT_CORRIDOR_DIR,
    stop_id: str = UNION_STATION_STOP_ID,
) -> list[CorridorWaits]:
    """Calculate every corridor/time-block row for Union Station."""

    resolved_gtfs_dirs = tuple(Path(path).resolve() for path in gtfs_dirs)
    corridor_stops = load_corridor_stops(Path(corridor_dir).resolve())
    missing_corridors = [
        corridor
        for corridor, stops in corridor_stops.items()
        if stop_id not in {stop.stop_id for stop in stops}
    ]
    if missing_corridors:
        raise ValueError(
            f"Stop {stop_id} is missing from corridor stop lists: "
            f"{', '.join(missing_corridors)}"
        )

    feeds = load_feed_schedules(resolved_gtfs_dirs, corridor_stops)
    rows: list[CorridorWaits] = []
    for corridor in CORRIDOR_ROUTES:
        for time_period in TIME_PERIODS:
            direction_waits = [
                waits
                for direction_id in DIRECTION_NAMES
                if (
                    waits := _calculate_direction_waits(
                        feeds,
                        corridor,
                        direction_id,
                        time_period,
                        stop_id,
                    )
                )
                is not None
            ]
            if not direction_waits:
                rows.append(
                    CorridorWaits(
                        corridor=corridor,
                        time_block=_time_block_label(time_period),
                        expected_before_minutes=None,
                        expected_after_minutes=None,
                        worst_before_minutes=None,
                        worst_after_minutes=None,
                        usable_direction_count=0,
                    )
                )
                continue

            rows.append(
                CorridorWaits(
                    corridor=corridor,
                    time_block=_time_block_label(time_period),
                    expected_before_minutes=statistics.fmean(
                        waits.expected_before_minutes
                        for waits in direction_waits
                    ),
                    expected_after_minutes=statistics.fmean(
                        waits.expected_after_minutes
                        for waits in direction_waits
                    ),
                    worst_before_minutes=max(
                        waits.worst_before_minutes
                        for waits in direction_waits
                    ),
                    worst_after_minutes=max(
                        waits.worst_after_minutes
                        for waits in direction_waits
                    ),
                    usable_direction_count=len(direction_waits),
                )
            )
    return rows


def _format_wait(value: float | None) -> str:
    """Format a wait in minutes for the console table."""

    return "N/A" if value is None else f"{value:.1f}"


def display_waits(
    rows: list[CorridorWaits],
    stop_id: str = UNION_STATION_STOP_ID,
) -> None:
    """Print the wait table and overall worst cases."""

    headings = (
        "Corridor",
        "Time block",
        "Expected before",
        "Expected after",
        "Worst before",
        "Worst after",
    )
    table_rows = [
        (
            row.corridor,
            row.time_block,
            _format_wait(row.expected_before_minutes),
            _format_wait(row.expected_after_minutes),
            _format_wait(row.worst_before_minutes),
            _format_wait(row.worst_after_minutes),
        )
        for row in rows
    ]
    widths = [
        max(len(headings[index]), *(len(row[index]) for row in table_rows))
        for index in range(len(headings))
    ]

    print(f"Union Station scheduled waits (stop {stop_id}), minutes")
    print(
        "  ".join(
            f"{heading:<{widths[index]}}"
            for index, heading in enumerate(headings)
        )
    )
    print("  ".join("-" * width for width in widths))
    for row in table_rows:
        print(
            f"{row[0]:<{widths[0]}}  "
            f"{row[1]:<{widths[1]}}  "
            + "  ".join(
                f"{row[index]:>{widths[index]}}"
                for index in range(2, len(headings))
            )
        )

    usable_rows = [row for row in rows if row.worst_before_minutes is not None]
    if not usable_rows:
        print("\nNo calculable Union Station headways were found.")
        return
    worst_before = max(
        usable_rows,
        key=lambda row: row.worst_before_minutes or 0,
    )
    worst_after = max(
        usable_rows,
        key=lambda row: row.worst_after_minutes or 0,
    )
    print()
    print(
        "Overall worst before: "
        f"{worst_before.worst_before_minutes:.1f} minutes "
        f"({worst_before.corridor}, {worst_before.time_block})"
    )
    print(
        "Overall worst after:  "
        f"{worst_after.worst_after_minutes:.1f} minutes "
        f"({worst_after.corridor}, {worst_after.time_block})"
    )
    print(
        "\nExpected waits assume random passenger arrivals. Worst before is the "
        "longest scheduled within-day gap; worst after is the even headway at "
        "the same average frequency."
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
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    rows = calculate_union_station_waits(
        gtfs_dirs=tuple(arguments.gtfs_dirs or DEFAULT_GTFS_DIRS),
        corridor_dir=arguments.corridor_dir,
    )
    display_waits(rows)


if __name__ == "__main__":
    main()
