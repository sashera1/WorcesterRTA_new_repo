"""Project ridership after making scheduled headways evenly spaced.

For each stop-pair origin and time period, the current expected wait and mean
headway are loaded from the same 2024 headway-aggregate rows.  The ideal wait
is half the mean headway, which represents the wait under evenly spaced service
with the same average frequency.  Direction/corridor records are averaged
within each physical stop, followed by an average across the component stops
in the origin pair, matching ``simple_model.py``.

The projection uses only nearby car trips::

    headway_change_min = current_expected_wait - ideal_headway / 2
    bus_ratio_near_projected = bus_ratio_near + change_factor * headway_change_min
    projected_ridership = (car_trips_0_800m + onboardings) * bus_ratio_near_projected
    ridership_increase = projected_ridership - onboardings

Run from the repository root with::

    python simplified_model/project_ridership.py
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from .simple_model import (
        CORRIDORS,
        DIRECTIONS,
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
    from simple_model import (
        CORRIDORS,
        DIRECTIONS,
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


DEFAULT_CHANGE_FACTOR = 0.01418
DEFAULT_OUTPUT_PATH = (
    Path(__file__).resolve().parent / "projected-ridership_sasha_shema.csv"
)
HEADWAY_REQUIRED_COLUMNS = {
    "stop_id",
    "corridor",
    "direction",
    "time_period",
    "calculation_status",
    "expected_wait_minutes",
    "mean_headway_minutes",
}


@dataclass(frozen=True)
class WaitMetric:
    """Observed and evenly spaced waits for one headway-aggregate row."""

    current_expected_wait: float
    ideal_expected_wait: float


def _parse_nonnegative_number(
    value: str | None,
    column: str,
    path: Path,
    row_number: int,
) -> float:
    """Parse a required finite, nonnegative number with row context."""
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


def load_wait_metrics(
    headway_dir: str | Path = DEFAULT_HEADWAY_DIR,
) -> dict[tuple[str, str, str, str], WaitMetric | None]:
    """Load observed and ideal waits keyed by time/corridor/direction/stop."""
    headway_dir = Path(headway_dir).resolve()
    metrics: dict[tuple[str, str, str, str], WaitMetric | None] = {}

    for time_period in TIME_PERIODS:
        for corridor in CORRIDORS:
            for direction in DIRECTIONS:
                input_path = headway_dir / (
                    f"{corridor}_{direction}_"
                    f"{time_period.headway_slug}_headways.csv"
                )
                if not input_path.is_file():
                    raise FileNotFoundError(
                        f"Headway file does not exist: {input_path}"
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

                        key = (
                            time_period.display_range,
                            corridor,
                            direction,
                            stop_id,
                        )
                        if key in metrics:
                            raise ValueError(f"Duplicate wait-metric key: {key}")

                        expected_wait_text = (
                            row.get("expected_wait_minutes") or ""
                        ).strip()
                        mean_headway_text = (
                            row.get("mean_headway_minutes") or ""
                        ).strip()
                        if not expected_wait_text and not mean_headway_text:
                            metrics[key] = None
                            continue
                        if not expected_wait_text or not mean_headway_text:
                            raise ValueError(
                                f"{input_path}, row {row_number} must have both "
                                "expected_wait_minutes and mean_headway_minutes"
                            )
                        if (
                            row.get("calculation_status") or ""
                        ).strip() != "ok":
                            raise ValueError(
                                f"{input_path}, row {row_number} has wait "
                                "metrics despite a non-ok calculation status"
                            )

                        current_wait = _parse_nonnegative_number(
                            expected_wait_text,
                            "expected_wait_minutes",
                            input_path,
                            row_number,
                        )
                        mean_headway = _parse_nonnegative_number(
                            mean_headway_text,
                            "mean_headway_minutes",
                            input_path,
                            row_number,
                        )
                        ideal_wait = mean_headway / 2
                        if current_wait + 1e-9 < ideal_wait:
                            raise ValueError(
                                f"{input_path}, row {row_number} has expected "
                                "wait below half its mean headway"
                            )
                        metrics[key] = WaitMetric(
                            current_expected_wait=current_wait,
                            ideal_expected_wait=ideal_wait,
                        )

                    if not seen_stops:
                        raise ValueError(f"Headway file is empty: {input_path}")
    return metrics


def _split_origin(origin: str) -> list[str]:
    """Return the unique physical stop IDs represented by an origin."""
    stop_ids = [stop_id.strip() for stop_id in origin.split(";")]
    if (
        not stop_ids
        or any(not stop_id for stop_id in stop_ids)
        or len(stop_ids) != len(set(stop_ids))
    ):
        raise ValueError(f"Origin has invalid component stop IDs: {origin!r}")
    return stop_ids


def region_headway_change(
    origin: str,
    time: str,
    sources: tuple[WaitSource, ...],
    metrics: dict[tuple[str, str, str, str], WaitMetric | None],
) -> float | None:
    """Average matched current-minus-ideal waits for an origin and period."""
    changes_by_stop = {stop_id: [] for stop_id in _split_origin(origin)}
    for source in sources:
        key = (time, source.corridor, source.direction, source.stop_id)
        if key not in metrics:
            raise ValueError(
                f"No headway row found for origin {origin!r} and key {key}"
            )
        metric = metrics[key]
        if metric is not None:
            changes_by_stop[source.stop_id].append(
                metric.current_expected_wait - metric.ideal_expected_wait
            )

    component_changes: list[float] = []
    for stop_id, stop_changes in changes_by_stop.items():
        if not stop_changes:
            return None
        component_changes.append(statistics.fmean(stop_changes))
    return statistics.fmean(component_changes)


def write_sasha_projection(
    ratio_path: str | Path = DEFAULT_RATIO_PATH,
    headway_dir: str | Path = DEFAULT_HEADWAY_DIR,
    corridor_dir: str | Path = DEFAULT_CORRIDOR_DIR,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    change_factor: int | float = DEFAULT_CHANGE_FACTOR,
) -> Path:
    """Write nearby-trip ridership projections for every usable origin-period."""
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

    projected_rows: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str]] = set()
    with ratio_path.open(encoding="utf-8-sig", newline="") as ratio_file:
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

            headway_change = region_headway_change(
                origin,
                time,
                sources,
                metrics,
            )
            if headway_change is None:
                continue

            onboardings = _parse_nonnegative_number(
                row.get("onboardings"),
                "onboardings",
                ratio_path,
                row_number,
            )
            nearby_car_trips = _parse_nonnegative_number(
                row.get("car_trips_0_800m"),
                "car_trips_0_800m",
                ratio_path,
                row_number,
            )
            bus_ratio_near = _parse_nonnegative_number(
                row.get("bus_ratio_near"),
                "bus_ratio_near",
                ratio_path,
                row_number,
            )

            projected_ratio = bus_ratio_near + factor * headway_change
            projected_ridership = (
                nearby_car_trips + onboardings
            ) * projected_ratio
            ridership_increase = projected_ridership - onboardings
            projected_rows.append(
                {
                    **row,
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
    output_path = write_sasha_projection(
        ratio_path=arguments.ratios,
        headway_dir=arguments.headway_dir,
        corridor_dir=arguments.corridor_dir,
        output_path=arguments.output,
        change_factor=arguments.change_factor,
    )
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
