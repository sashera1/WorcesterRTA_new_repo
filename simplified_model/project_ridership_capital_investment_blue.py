"""Project ridership with a Green/Orange wait benchmark for Blue service.

This is the capital-investment counterpart to ``project_ridership.py``.  For
each time period, it calculates the mean improved expected wait across usable
Green and Orange stop-pair origins.  That single time-specific benchmark is
then used as the projected expected wait for every usable Blue origin.

Green, Orange, and Hub Center retain the original Sasha-schema improvement:
their projected expected wait is half their matched mean headway.  All
projections use nearby car trips and the existing change factor of 0.01418.

Run from the repository root with::

    python simplified_model/project_ridership_capital_investment_blue.py
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from .project_ridership import (
        DEFAULT_CHANGE_FACTOR,
        WaitMetric,
        load_wait_metrics,
    )
    from .simple_model import (
        CORRIDORS,
        DEFAULT_CORRIDOR_DIR,
        DEFAULT_HEADWAY_DIR,
        DEFAULT_RATIO_PATH,
        PROJECTION_COLUMNS,
        PROJECTION_REQUIRED_COLUMNS,
        RATIO_CORRIDORS,
        TIME_PERIOD_BY_DISPLAY,
        TIME_PERIODS,
        WaitSource,
        load_region_wait_sources,
    )
else:
    from project_ridership import (
        DEFAULT_CHANGE_FACTOR,
        WaitMetric,
        load_wait_metrics,
    )
    from simple_model import (
        CORRIDORS,
        DEFAULT_CORRIDOR_DIR,
        DEFAULT_HEADWAY_DIR,
        DEFAULT_RATIO_PATH,
        PROJECTION_COLUMNS,
        PROJECTION_REQUIRED_COLUMNS,
        RATIO_CORRIDORS,
        TIME_PERIOD_BY_DISPLAY,
        TIME_PERIODS,
        WaitSource,
        load_region_wait_sources,
    )


DEFAULT_OUTPUT_PATH = (
    Path(__file__).resolve().parent
    / "projected-ridership_sasha_shema_capital_investment_blue.csv"
)
BLUE_BENCHMARK_CORRIDORS = {"Green", "Orange"}


@dataclass(frozen=True)
class RegionWaits:
    """Matched current and evenly spaced waits for one origin-period."""

    current_expected_wait: float
    ideal_expected_wait: float


@dataclass(frozen=True)
class RatioRow:
    """A validated source row plus the headway sources for its origin."""

    row_number: int
    values: dict[str, str]
    origin: str
    time: str
    corridor: str
    sources: tuple[WaitSource, ...]


def _parse_nonnegative_number(
    value: str | None,
    column: str,
    path: Path,
    row_number: int,
) -> float:
    """Parse a finite, nonnegative number with file and row context."""
    text = (value or "").strip()
    try:
        number = float(text)
    except ValueError as error:
        raise ValueError(
            f"{path}, row {row_number}, column {column!r} has invalid "
            f"value {text!r}"
        ) from error
    if not math.isfinite(number) or number < 0:
        raise ValueError(
            f"{path}, row {row_number}, column {column!r} has invalid "
            f"value {text!r}"
        )
    return number


def _split_origin(origin: str) -> list[str]:
    """Return the unique physical stops represented by an origin string."""
    stop_ids = [stop_id.strip() for stop_id in origin.split(";")]
    if (
        not stop_ids
        or any(not stop_id for stop_id in stop_ids)
        or len(stop_ids) != len(set(stop_ids))
    ):
        raise ValueError(f"Origin has invalid component stop IDs: {origin!r}")
    return stop_ids


def region_waits(
    origin: str,
    time: str,
    sources: tuple[WaitSource, ...],
    metrics: dict[tuple[str, str, str, str], WaitMetric | None],
) -> RegionWaits | None:
    """Average matched waits within physical stops and then across a pair."""
    metrics_by_stop: dict[str, list[WaitMetric]] = {
        stop_id: [] for stop_id in _split_origin(origin)
    }
    for source in sources:
        key = (time, source.corridor, source.direction, source.stop_id)
        if key not in metrics:
            raise ValueError(
                f"No headway row found for origin {origin!r} and key {key}"
            )
        metric = metrics[key]
        if metric is not None:
            metrics_by_stop[source.stop_id].append(metric)

    current_component_waits: list[float] = []
    ideal_component_waits: list[float] = []
    for stop_metrics in metrics_by_stop.values():
        if not stop_metrics:
            return None
        current_component_waits.append(
            statistics.fmean(
                metric.current_expected_wait for metric in stop_metrics
            )
        )
        ideal_component_waits.append(
            statistics.fmean(
                metric.ideal_expected_wait for metric in stop_metrics
            )
        )
    return RegionWaits(
        current_expected_wait=statistics.fmean(current_component_waits),
        ideal_expected_wait=statistics.fmean(ideal_component_waits),
    )


def _load_ratio_rows(
    ratio_path: Path,
    sources_by_origin: dict[str, tuple[WaitSource, ...]],
) -> tuple[list[str], list[RatioRow]]:
    """Load and validate ratio-row identity and corridor membership."""
    rows: list[RatioRow] = []
    seen_keys: set[tuple[str, str]] = set()
    with ratio_path.open("r", encoding="utf-8-sig", newline="") as ratio_file:
        reader = csv.DictReader(ratio_file)
        input_columns = list(reader.fieldnames or ())
        missing_columns = PROJECTION_REQUIRED_COLUMNS - set(input_columns)
        if missing_columns:
            raise ValueError(
                f"{ratio_path} is missing columns: {sorted(missing_columns)}"
            )
        duplicate_columns = set(PROJECTION_COLUMNS) & set(input_columns)
        if duplicate_columns:
            raise ValueError(
                f"{ratio_path} already contains projection columns: "
                f"{sorted(duplicate_columns)}"
            )

        for row_number, row in enumerate(reader, start=2):
            origin = (row.get("origin") or "").strip()
            time = (row.get("time") or "").strip()
            corridor = (row.get("corridor") or "").strip()
            if not origin or not time:
                raise ValueError(
                    f"{ratio_path}, row {row_number} has a blank origin or time"
                )
            key = (origin, time)
            if key in seen_keys:
                raise ValueError(f"{ratio_path} contains duplicate key {key}")
            seen_keys.add(key)
            if time not in TIME_PERIOD_BY_DISPLAY:
                raise ValueError(
                    f"{ratio_path}, row {row_number} has unknown time {time!r}"
                )
            if corridor not in RATIO_CORRIDORS:
                raise ValueError(
                    f"{ratio_path}, row {row_number} has unknown corridor "
                    f"{corridor!r}"
                )

            sources = sources_by_origin.get(origin)
            if sources is None:
                raise ValueError(
                    f"No consolidated stop mapping found for origin {origin!r}"
                )
            source_corridors = {source.corridor for source in sources}
            expected_corridors = (
                set(CORRIDORS) if corridor == "all" else {corridor}
            )
            if source_corridors != expected_corridors:
                raise ValueError(
                    f"Ratio corridor {corridor!r} does not match origin "
                    f"{origin!r} sources {sorted(source_corridors)}"
                )
            rows.append(
                RatioRow(
                    row_number=row_number,
                    values=dict(row),
                    origin=origin,
                    time=time,
                    corridor=corridor,
                    sources=sources,
                )
            )
    if not rows:
        raise ValueError(f"Ratio CSV is empty: {ratio_path}")
    return input_columns, rows


def calculate_blue_wait_benchmarks(
    rows: list[RatioRow],
    metrics: dict[tuple[str, str, str, str], WaitMetric | None],
) -> dict[str, float]:
    """Calculate one equally weighted Green/Orange ideal wait per period."""
    ideal_waits_by_time: dict[str, list[float]] = {
        time_period.display_range: [] for time_period in TIME_PERIODS
    }
    for ratio_row in rows:
        if ratio_row.corridor not in BLUE_BENCHMARK_CORRIDORS:
            continue
        waits = region_waits(
            ratio_row.origin,
            ratio_row.time,
            ratio_row.sources,
            metrics,
        )
        if waits is not None:
            ideal_waits_by_time[ratio_row.time].append(
                waits.ideal_expected_wait
            )

    benchmarks: dict[str, float] = {}
    for time, ideal_waits in ideal_waits_by_time.items():
        if not ideal_waits:
            raise ValueError(
                f"No usable Green or Orange ideal waits exist for {time}"
            )
        benchmarks[time] = statistics.fmean(ideal_waits)
    return benchmarks


def write_capital_investment_blue_projection(
    ratio_path: str | Path = DEFAULT_RATIO_PATH,
    headway_dir: str | Path = DEFAULT_HEADWAY_DIR,
    corridor_dir: str | Path = DEFAULT_CORRIDOR_DIR,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    change_factor: int | float = DEFAULT_CHANGE_FACTOR,
) -> Path:
    """Write the Blue capital-investment projection and return its path."""
    ratio_path = Path(ratio_path).resolve()
    output_path = Path(output_path).resolve()
    if not ratio_path.is_file():
        raise FileNotFoundError(f"Ratio file does not exist: {ratio_path}")
    if ratio_path == output_path:
        raise ValueError("Projection output must be a new CSV path")
    factor = float(change_factor)
    if not math.isfinite(factor):
        raise ValueError("change_factor must be finite")

    sources_by_origin = load_region_wait_sources(corridor_dir)
    metrics = load_wait_metrics(headway_dir)
    input_columns, ratio_rows = _load_ratio_rows(
        ratio_path,
        sources_by_origin,
    )
    blue_benchmarks = calculate_blue_wait_benchmarks(ratio_rows, metrics)

    projected_rows: list[dict[str, str]] = []
    for ratio_row in ratio_rows:
        waits = region_waits(
            ratio_row.origin,
            ratio_row.time,
            ratio_row.sources,
            metrics,
        )
        if waits is None:
            continue

        if ratio_row.corridor == "Blue":
            projected_expected_wait = blue_benchmarks[ratio_row.time]
        else:
            projected_expected_wait = waits.ideal_expected_wait
        headway_change = (
            waits.current_expected_wait - projected_expected_wait
        )

        onboardings = _parse_nonnegative_number(
            ratio_row.values.get("onboardings"),
            "onboardings",
            ratio_path,
            ratio_row.row_number,
        )
        nearby_car_trips = _parse_nonnegative_number(
            ratio_row.values.get("car_trips_0_800m"),
            "car_trips_0_800m",
            ratio_path,
            ratio_row.row_number,
        )
        bus_ratio_near = _parse_nonnegative_number(
            ratio_row.values.get("bus_ratio_near"),
            "bus_ratio_near",
            ratio_path,
            ratio_row.row_number,
        )
        if bus_ratio_near > 1:
            raise ValueError(
                f"{ratio_path}, row {ratio_row.row_number} has "
                "bus_ratio_near above 1"
            )

        projected_ratio = bus_ratio_near + factor * headway_change
        projected_ridership = (
            nearby_car_trips + onboardings
        ) * projected_ratio
        ridership_increase = projected_ridership - onboardings
        projected_rows.append(
            {
                **ratio_row.values,
                "bus_ratio_near_projected": f"{projected_ratio:.6f}",
                "projected_ridership": f"{projected_ridership:.6f}",
                "ridership_increase": f"{ridership_increase:.6f}",
            }
        )

    if not projected_rows:
        raise ValueError("No origin-period rows had usable headway metrics")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=[*input_columns, *PROJECTION_COLUMNS],
        )
        writer.writeheader()
        writer.writerows(projected_rows)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ratios",
        type=Path,
        default=DEFAULT_RATIO_PATH,
        help=f"Car/bus ratio CSV (default: {DEFAULT_RATIO_PATH})",
    )
    parser.add_argument(
        "--headway-dir",
        type=Path,
        default=DEFAULT_HEADWAY_DIR,
        help=f"Headway aggregate directory (default: {DEFAULT_HEADWAY_DIR})",
    )
    parser.add_argument(
        "--corridor-dir",
        type=Path,
        default=DEFAULT_CORRIDOR_DIR,
        help=f"Consolidated stop-pair directory (default: {DEFAULT_CORRIDOR_DIR})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Projection CSV (default: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--change-factor",
        type=float,
        default=DEFAULT_CHANGE_FACTOR,
        help=f"Ratio change per wait minute (default: {DEFAULT_CHANGE_FACTOR})",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    output_path = write_capital_investment_blue_projection(
        ratio_path=arguments.ratios,
        headway_dir=arguments.headway_dir,
        corridor_dir=arguments.corridor_dir,
        output_path=arguments.output,
        change_factor=arguments.change_factor,
    )
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
