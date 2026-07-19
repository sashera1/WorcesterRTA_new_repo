"""Analyze and project the near bus-trip ratio for 2024.

Each point represents one consolidated stop region and TomTom time period.
Expected waits come from the 2024 headway aggregate CSVs.  For regions made of
multiple physical stops, waits are averaged across the component stops; a
component with multiple applicable direction/corridor records is averaged
before the region average is calculated.  Blank headway estimates are not
treated as zero, and a region-period is omitted if any component stop has no
usable estimate.

By default the graph uses ``bus_ratio_near``.  Setting ``bus_far=True`` uses
the existing ``bus_ratio_all`` field, whose denominator contains all three car
trip distance buckets.

Run from the repository root with::

    python simplified_model/simple_model.py
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RATIO_PATH = Path(__file__).resolve().parent / "car_bus_ratios.csv"
DEFAULT_PROJECTION_PATH = (
    Path(__file__).resolve().parent / "projected_ridership.csv"
)
DEFAULT_HEADWAY_DIR = Path(__file__).resolve().parent / "2024_headway_aggregate"
DEFAULT_CORRIDOR_DIR = (
    PROJECT_ROOT / "data" / "processed" / "stops_consolidated_data_2024"
)

CORRIDORS = ("Orange", "Blue", "Green")
DIRECTIONS = ("inbound", "outbound")
RATIO_CORRIDORS = (*CORRIDORS, "all")
CORRIDOR_COLORS = {
    "Orange": "tab:orange",
    "Blue": "tab:blue",
    "Green": "tab:green",
    "all": "tab:purple",
}
TIME_MARKERS = {
    "04:00 - 06:00": "o",
    "06:00 - 09:00": "s",
    "09:00 - 15:00": "^",
    "15:00 - 18:00": "D",
    "18:00 - 22:00": "P",
    "22:00 - 00:00": "X",
}
RATIO_REQUIRED_COLUMNS = {
    "origin",
    "time",
    "corridor",
    "bus_ratio_near",
    "bus_ratio_all",
}
PROJECTION_REQUIRED_COLUMNS = {
    "time",
    "corridor",
    "onboardings",
    "car_trips_0_800m",
    "bus_ratio_near",
}
PROJECTION_COLUMNS = (
    "bus_ratio_near_projected",
    "projected_ridership",
    "ridership_increase",
)
CORRIDOR_REQUIRED_COLUMNS = {
    "stop_id",
    "inbound_stop_id",
    "outbound_stop_id",
    "direction",
    "extra_inbound",
    "extra_outbound",
}
HEADWAY_REQUIRED_COLUMNS = {
    "stop_id",
    "corridor",
    "direction",
    "time_period",
    "calculation_status",
    "expected_wait_minutes",
}


@dataclass(frozen=True)
class TimePeriod:
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
TIME_PERIOD_BY_DISPLAY = {
    time_period.display_range: time_period for time_period in TIME_PERIODS
}
TIME_PERIOD_BY_INPUT = {
    name: time_period
    for time_period in TIME_PERIODS
    for name in (time_period.filename_range, time_period.display_range)
}


@dataclass(frozen=True)
class WaitSource:
    corridor: str
    direction: str
    stop_id: str


@dataclass(frozen=True)
class PlotPoint:
    origin: str
    time: str
    corridor: str
    expected_wait_minutes: float
    bus_ratio_near: float
    bus_ratio_all: float


@dataclass(frozen=True)
class LinearFit:
    slope: float
    intercept: float
    pearson_r: float
    r_squared: float


def _split_stop_ids(value: str | None) -> list[str]:
    """Split an optional semicolon-delimited stop-ID field."""
    if value is None or not value.strip():
        return []
    stop_ids = [stop_id.strip() for stop_id in value.split(";")]
    if any(not stop_id for stop_id in stop_ids):
        raise ValueError(f"Invalid semicolon-delimited stop IDs: {value!r}")
    return stop_ids


def load_region_wait_sources(
    corridor_dir: str | Path = DEFAULT_CORRIDOR_DIR,
) -> dict[str, tuple[WaitSource, ...]]:
    """Load the direction-aware headway rows belonging to each stop region."""
    corridor_dir = Path(corridor_dir).resolve()
    sources_by_origin: dict[str, list[WaitSource]] = {}

    for corridor in CORRIDORS:
        input_path = corridor_dir / f"{corridor}_corridor_shared_stops.csv"
        if not input_path.is_file():
            raise FileNotFoundError(
                f"Consolidated corridor-stop file does not exist: {input_path}"
            )
        with input_path.open(encoding="utf-8-sig", newline="") as input_file:
            reader = csv.DictReader(input_file)
            missing_columns = CORRIDOR_REQUIRED_COLUMNS - set(
                reader.fieldnames or ()
            )
            if missing_columns:
                raise ValueError(
                    f"{input_path} is missing columns: {sorted(missing_columns)}"
                )

            seen_origins: set[str] = set()
            for row_number, row in enumerate(reader, start=2):
                origin = (row.get("stop_id") or "").strip()
                if not origin:
                    raise ValueError(
                        f"{input_path}, row {row_number} has a blank stop_id"
                    )
                if origin in seen_origins:
                    raise ValueError(
                        f"{input_path} contains duplicate region {origin!r}"
                    )
                seen_origins.add(origin)

                region_type = (row.get("direction") or "").strip().upper()
                if region_type not in {"PAIRED", "BOTH"}:
                    raise ValueError(
                        f"{input_path}, row {row_number} has unsupported "
                        f"direction type {region_type!r}"
                    )
                inbound_ids = [
                    *_split_stop_ids(row.get("inbound_stop_id")),
                    *_split_stop_ids(row.get("extra_inbound")),
                ]
                outbound_ids = [
                    *_split_stop_ids(row.get("outbound_stop_id")),
                    *_split_stop_ids(row.get("extra_outbound")),
                ]
                component_ids = _split_stop_ids(origin)
                if set(inbound_ids) | set(outbound_ids) != set(component_ids):
                    raise ValueError(
                        f"{input_path}, row {row_number} direction fields do "
                        f"not match region {origin!r}"
                    )

                region_sources = sources_by_origin.setdefault(origin, [])
                region_sources.extend(
                    WaitSource(corridor, "inbound", stop_id)
                    for stop_id in inbound_ids
                )
                region_sources.extend(
                    WaitSource(corridor, "outbound", stop_id)
                    for stop_id in outbound_ids
                )

    finalized_sources: dict[str, tuple[WaitSource, ...]] = {}
    for origin, sources in sources_by_origin.items():
        if len(sources) != len(set(sources)):
            raise ValueError(f"Region {origin!r} has duplicate wait sources")
        source_corridors = {source.corridor for source in sources}
        if origin == "1503":
            if source_corridors != set(CORRIDORS):
                raise ValueError(
                    "Hub Center region 1503 must have all three corridors"
                )
        elif len(source_corridors) != 1:
            raise ValueError(
                f"Non-center region {origin!r} has multiple corridors: "
                f"{sorted(source_corridors)}"
            )
        finalized_sources[origin] = tuple(sources)
    return finalized_sources


def load_expected_waits(
    headway_dir: str | Path = DEFAULT_HEADWAY_DIR,
) -> dict[tuple[str, str, str, str], float | None]:
    """Load every expected-wait value, retaining unavailable values as None."""
    headway_dir = Path(headway_dir).resolve()
    waits: dict[tuple[str, str, str, str], float | None] = {}

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

                        wait_text = (
                            row.get("expected_wait_minutes") or ""
                        ).strip()
                        if not wait_text:
                            expected_wait = None
                        else:
                            try:
                                expected_wait = float(wait_text)
                            except ValueError as error:
                                raise ValueError(
                                    f"{input_path}, row {row_number} has invalid "
                                    f"expected wait {wait_text!r}"
                                ) from error
                            if (
                                not math.isfinite(expected_wait)
                                or expected_wait < 0
                            ):
                                raise ValueError(
                                    f"{input_path}, row {row_number} has invalid "
                                    f"expected wait {wait_text!r}"
                                )
                            if (
                                row.get("calculation_status") or ""
                            ).strip() != "ok":
                                raise ValueError(
                                    f"{input_path}, row {row_number} has an "
                                    "expected wait despite a non-ok status"
                                )

                        key = (
                            time_period.display_range,
                            corridor,
                            direction,
                            stop_id,
                        )
                        if key in waits:
                            raise ValueError(f"Duplicate expected-wait key: {key}")
                        waits[key] = expected_wait

                    if not seen_stops:
                        raise ValueError(f"Headway file is empty: {input_path}")
    return waits


def _region_expected_wait(
    origin: str,
    time: str,
    sources: tuple[WaitSource, ...],
    waits: dict[tuple[str, str, str, str], float | None],
) -> float | None:
    """Average service rows within stops, then average all component stops."""
    component_ids = _split_stop_ids(origin)
    waits_by_stop = {stop_id: [] for stop_id in component_ids}
    for source in sources:
        key = (time, source.corridor, source.direction, source.stop_id)
        if key not in waits:
            raise ValueError(
                f"No headway row found for region {origin!r} and key {key}"
            )
        expected_wait = waits[key]
        if expected_wait is not None:
            waits_by_stop[source.stop_id].append(expected_wait)

    component_means: list[float] = []
    for stop_id in component_ids:
        stop_waits = waits_by_stop[stop_id]
        if not stop_waits:
            return None
        component_means.append(statistics.fmean(stop_waits))
    return statistics.fmean(component_means)


def load_points(
    ratio_path: str | Path = DEFAULT_RATIO_PATH,
    headway_dir: str | Path = DEFAULT_HEADWAY_DIR,
    corridor_dir: str | Path = DEFAULT_CORRIDOR_DIR,
) -> list[PlotPoint]:
    """Join ratios to averaged expected waits and return usable plot points."""
    ratio_path = Path(ratio_path).resolve()
    if not ratio_path.is_file():
        raise FileNotFoundError(f"Car/bus ratio file does not exist: {ratio_path}")
    sources_by_origin = load_region_wait_sources(corridor_dir)
    waits = load_expected_waits(headway_dir)

    points: list[PlotPoint] = []
    seen_keys: set[tuple[str, str]] = set()
    with ratio_path.open(encoding="utf-8-sig", newline="") as ratio_file:
        reader = csv.DictReader(ratio_file)
        missing_columns = RATIO_REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing_columns:
            raise ValueError(
                f"{ratio_path} is missing columns: {sorted(missing_columns)}"
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

            ratios: dict[str, float] = {}
            for ratio_column in ("bus_ratio_near", "bus_ratio_all"):
                ratio_text = (row.get(ratio_column) or "").strip()
                try:
                    ratio = float(ratio_text)
                except ValueError as error:
                    raise ValueError(
                        f"{ratio_path}, row {row_number} has invalid "
                        f"{ratio_column} value {ratio_text!r}"
                    ) from error
                if not math.isfinite(ratio) or not 0 <= ratio <= 1:
                    raise ValueError(
                        f"{ratio_path}, row {row_number} has invalid "
                        f"{ratio_column} value {ratio_text!r}"
                    )
                ratios[ratio_column] = ratio

            expected_wait = _region_expected_wait(
                origin,
                time,
                sources,
                waits,
            )
            if expected_wait is None:
                continue
            points.append(
                PlotPoint(
                    origin=origin,
                    time=time,
                    corridor=corridor,
                    expected_wait_minutes=expected_wait,
                    bus_ratio_near=ratios["bus_ratio_near"],
                    bus_ratio_all=ratios["bus_ratio_all"],
                )
            )

    if len(points) < 2:
        raise ValueError("At least two usable region-time points are required")
    return points


def _selected_bus_ratio(point: PlotPoint, bus_far: bool) -> float:
    """Select the all-distance ratio when the far-range toggle is enabled."""
    return point.bus_ratio_all if bus_far else point.bus_ratio_near


def _ratio_label(bus_far: bool) -> str:
    return "bus_ratio_all" if bus_far else "bus_ratio_near"


def _ratio_title(bus_far: bool) -> str:
    return "All-Trip Bus Ratio" if bus_far else "Near Bus Ratio"


def calculate_linear_fit(
    points: list[PlotPoint],
    bus_far: bool = False,
) -> LinearFit:
    """Calculate ordinary least squares and Pearson's correlation coefficient."""
    x_values = [point.expected_wait_minutes for point in points]
    y_values = [_selected_bus_ratio(point, bus_far) for point in points]
    x_mean = statistics.fmean(x_values)
    y_mean = statistics.fmean(y_values)
    x_deviations = [value - x_mean for value in x_values]
    y_deviations = [value - y_mean for value in y_values]
    sum_x_squared = math.fsum(value * value for value in x_deviations)
    sum_y_squared = math.fsum(value * value for value in y_deviations)
    sum_cross_products = math.fsum(
        x_deviation * y_deviation
        for x_deviation, y_deviation in zip(x_deviations, y_deviations)
    )
    if sum_x_squared == 0:
        raise ValueError("Expected wait time has no variation")
    if sum_y_squared == 0:
        raise ValueError(f"{_ratio_label(bus_far)} has no variation")

    slope = sum_cross_products / sum_x_squared
    intercept = y_mean - slope * x_mean
    pearson_r = sum_cross_products / math.sqrt(
        sum_x_squared * sum_y_squared
    )
    return LinearFit(
        slope=slope,
        intercept=intercept,
        pearson_r=pearson_r,
        r_squared=pearson_r**2,
    )


def equation_text(fit: LinearFit) -> str:
    sign = "+" if fit.intercept >= 0 else "-"
    return f"y = {fit.slope:.5f}x {sign} {abs(fit.intercept):.5f}"


def _projection_number(
    row: dict[str, str],
    column: str,
    ratio_path: Path,
    row_number: int,
) -> float:
    """Read one finite, nonnegative numeric projection input."""
    value = (row.get(column) or "").strip()
    try:
        number = float(value)
    except ValueError as error:
        raise ValueError(
            f"{ratio_path}, row {row_number} has invalid {column} "
            f"value {value!r}"
        ) from error
    if not math.isfinite(number) or number < 0:
        raise ValueError(
            f"{ratio_path}, row {row_number} has invalid {column} "
            f"value {value!r}"
        )
    return number


def _selected_projection_times(time_ranges: list[str]) -> set[str]:
    """Normalize filename-style and display-style time ranges."""
    if not time_ranges:
        raise ValueError("At least one time range is required")

    selected_times: set[str] = set()
    for time_range in time_ranges:
        normalized_range = time_range.strip()
        time_period = TIME_PERIOD_BY_INPUT.get(normalized_range)
        if time_period is None:
            raise ValueError(
                f"Unknown time range {time_range!r}; expected one of "
                f"{sorted(TIME_PERIOD_BY_INPUT)}"
            )
        selected_times.add(time_period.display_range)
    return selected_times


def _projection_headway_change(
    corridor: str,
    headway_change_min: dict[str, int | float],
) -> float:
    """Return a corridor change, averaging named corridors for ``all``."""
    if corridor in headway_change_min:
        value = float(headway_change_min[corridor])
    elif corridor == "all" and all(
        named_corridor in headway_change_min for named_corridor in CORRIDORS
    ):
        value = statistics.fmean(
            float(headway_change_min[named_corridor])
            for named_corridor in CORRIDORS
        )
    else:
        raise ValueError(
            f"No headway change was provided for corridor {corridor!r}"
        )
    if not math.isfinite(value):
        raise ValueError(
            f"Headway change for corridor {corridor!r} must be finite"
        )
    return value


def project_ridership(
    car_bus_ratios_path: str | Path,
    time_ranges: list[str],
    change_factor: int | float,
    headway_change_min: dict[str, int | float],
    output_path: str | Path = DEFAULT_PROJECTION_PATH,
) -> Path:
    """Write projected ridership rows for the selected time ranges.

    The input columns are retained in their original order, followed by
    ``bus_ratio_near_projected``, ``projected_ridership``, and
    ``ridership_increase``.  A Hub Center row whose corridor is ``all`` uses
    the mean of the Orange, Blue, and Green changes unless an explicit ``all``
    value is supplied.
    """
    ratio_path = Path(car_bus_ratios_path).resolve()
    output_path = Path(output_path).resolve()
    if not ratio_path.is_file():
        raise FileNotFoundError(
            f"Car/bus ratio file does not exist: {ratio_path}"
        )
    if ratio_path == output_path:
        raise ValueError("Projection output must be a new CSV path")

    factor = float(change_factor)
    if not math.isfinite(factor):
        raise ValueError("change_factor must be finite")
    selected_times = _selected_projection_times(time_ranges)

    projected_rows: list[dict[str, str]] = []
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
            if (row.get("time") or "").strip() not in selected_times:
                continue

            corridor = (row.get("corridor") or "").strip()
            headway_change = _projection_headway_change(
                corridor,
                headway_change_min,
            )
            onboardings = _projection_number(
                row, "onboardings", ratio_path, row_number
            )
            near_car_trips = _projection_number(
                row, "car_trips_0_800m", ratio_path, row_number
            )
            bus_ratio_near = _projection_number(
                row, "bus_ratio_near", ratio_path, row_number
            )

            projected_bus_ratio = (
                bus_ratio_near + factor * headway_change
            )
            projected_ridership = (
                near_car_trips + onboardings
            ) * projected_bus_ratio
            ridership_increase = projected_ridership - onboardings

            projected_rows.append(
                {
                    **row,
                    "bus_ratio_near_projected": f"{projected_bus_ratio:.6f}",
                    "projected_ridership": f"{projected_ridership:.6f}",
                    "ridership_increase": f"{ridership_increase:.6f}",
                }
            )

    if not projected_rows:
        raise ValueError(
            f"No rows in {ratio_path} matched the selected time ranges"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=[*input_columns, *PROJECTION_COLUMNS],
        )
        writer.writeheader()
        writer.writerows(projected_rows)
    return output_path


def _create_by_time_plot(points: list[PlotPoint], bus_far: bool):
    """Create six comparable panels with one fit per time period."""
    figure, axes = plt.subplots(
        2,
        3,
        figsize=(17, 10),
        sharex=True,
        sharey=True,
    )
    flat_axes = axes.flat

    for axis, time_period in zip(flat_axes, TIME_PERIODS):
        period_points = [
            point
            for point in points
            if point.time == time_period.display_range
        ]
        for corridor in RATIO_CORRIDORS:
            corridor_points = [
                point
                for point in period_points
                if point.corridor == corridor
            ]
            if not corridor_points:
                continue
            axis.scatter(
                [point.expected_wait_minutes for point in corridor_points],
                [
                    _selected_bus_ratio(point, bus_far)
                    for point in corridor_points
                ],
                color=CORRIDOR_COLORS[corridor],
                marker="o",
                s=45,
                alpha=0.72,
                edgecolors="white",
                linewidths=0.4,
            )

        fit: LinearFit | None = None
        fit_error: str | None = None
        if len(period_points) < 2:
            fit_error = "fewer than two observations"
        else:
            try:
                fit = calculate_linear_fit(period_points, bus_far=bus_far)
            except ValueError as error:
                fit_error = str(error).lower()

        if fit is not None:
            minimum_wait = min(
                point.expected_wait_minutes for point in period_points
            )
            maximum_wait = max(
                point.expected_wait_minutes for point in period_points
            )
            fit_x = [minimum_wait, maximum_wait]
            fit_y = [fit.slope * value + fit.intercept for value in fit_x]
            axis.plot(
                fit_x,
                fit_y,
                color="black",
                linestyle="--",
                linewidth=1.7,
            )
            statistics_text = (
                f"{equation_text(fit)}\n"
                f"r = {fit.pearson_r:.4f}\n"
                f"R² = {fit.r_squared:.4f}\n"
                f"n = {len(period_points)}"
            )
        else:
            statistics_text = (
                "Fit unavailable\n"
                f"{fit_error}\n"
                "r = N/A\n"
                "R² = N/A\n"
                f"n = {len(period_points)}"
            )

        axis.text(
            0.97,
            0.96,
            statistics_text,
            transform=axis.transAxes,
            ha="right",
            va="top",
            fontsize=8.5,
            bbox={
                "boxstyle": "round,pad=0.35",
                "facecolor": "white",
                "alpha": 0.88,
            },
        )
        axis.set_title(time_period.display_range)
        axis.grid(True, linestyle=":", alpha=0.4)

    minimum_wait = min(point.expected_wait_minutes for point in points)
    maximum_wait = max(point.expected_wait_minutes for point in points)
    wait_padding = max((maximum_wait - minimum_wait) * 0.035, 0.5)
    axes[0, 0].set_xlim(
        minimum_wait - wait_padding,
        maximum_wait + wait_padding,
    )
    axes[0, 0].set_ylim(-0.02, 1.02)

    legend_handles = [
        Line2D(
            [],
            [],
            color=CORRIDOR_COLORS[corridor],
            marker="o",
            linestyle="None",
            markersize=8,
            label=corridor,
        )
        for corridor in RATIO_CORRIDORS
    ]
    legend_handles.append(
        Line2D(
            [],
            [],
            color="black",
            linestyle="--",
            linewidth=2,
            label="Best fit",
        )
    )
    figure.legend(
        handles=legend_handles,
        title="Corridor",
        loc="center right",
        bbox_to_anchor=(0.995, 0.5),
    )
    figure.suptitle(
        f"2024 Expected Wait Time vs. {_ratio_title(bus_far)} by Time Period"
    )
    figure.supxlabel("Expected wait time (minutes)")
    figure.supylabel(_ratio_label(bus_far))
    figure.tight_layout(rect=(0.035, 0.035, 0.88, 0.95))
    return figure, axes


def create_plot(
    points: list[PlotPoint],
    by_time: bool = False,
    bus_far: bool = False,
):
    """Create either the pooled plot or six time-specific plot panels."""
    if by_time:
        return _create_by_time_plot(points, bus_far=bus_far)

    fit = calculate_linear_fit(points, bus_far=bus_far)
    figure, axis = plt.subplots(figsize=(13.5, 8))

    for corridor in RATIO_CORRIDORS:
        for time in TIME_MARKERS:
            matching_points = [
                point
                for point in points
                if point.corridor == corridor and point.time == time
            ]
            if not matching_points:
                continue
            axis.scatter(
                [point.expected_wait_minutes for point in matching_points],
                [
                    _selected_bus_ratio(point, bus_far)
                    for point in matching_points
                ],
                color=CORRIDOR_COLORS[corridor],
                marker=TIME_MARKERS[time],
                s=58,
                alpha=0.7,
                edgecolors="white",
                linewidths=0.45,
            )

    minimum_wait = min(point.expected_wait_minutes for point in points)
    maximum_wait = max(point.expected_wait_minutes for point in points)
    fit_x = [minimum_wait, maximum_wait]
    fit_y = [fit.slope * value + fit.intercept for value in fit_x]
    axis.plot(
        fit_x,
        fit_y,
        color="black",
        linestyle="--",
        linewidth=2,
        label="Overall best fit",
    )

    statistics_text = (
        f"Best fit: {equation_text(fit)}\n"
        f"Pearson r = {fit.pearson_r:.4f}\n"
        f"R² = {fit.r_squared:.4f}\n"
        f"n = {len(points)}"
    )
    axis.text(
        0.98,
        0.98,
        statistics_text,
        transform=axis.transAxes,
        ha="right",
        va="top",
        bbox={"boxstyle": "round,pad=0.45", "facecolor": "white", "alpha": 0.9},
    )

    corridor_handles = [
        Line2D(
            [],
            [],
            color=CORRIDOR_COLORS[corridor],
            marker="o",
            linestyle="None",
            markersize=8,
            label=corridor,
        )
        for corridor in RATIO_CORRIDORS
    ]
    corridor_legend = axis.legend(
        handles=corridor_handles,
        title="Corridor",
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
    )
    axis.add_artist(corridor_legend)
    time_handles = [
        Line2D(
            [],
            [],
            color="black",
            marker=marker,
            linestyle="None",
            markersize=7,
            label=time,
        )
        for time, marker in TIME_MARKERS.items()
    ]
    time_handles.append(
        Line2D(
            [],
            [],
            color="black",
            linestyle="--",
            linewidth=2,
            label="Overall best fit",
        )
    )
    axis.legend(
        handles=time_handles,
        title="Time period",
        loc="upper left",
        bbox_to_anchor=(1.01, 0.64),
    )

    axis.set_xlabel("Expected wait time (minutes)")
    axis.set_ylabel(_ratio_label(bus_far))
    axis.set_title(f"2024 Expected Wait Time vs. {_ratio_title(bus_far)}")
    axis.set_ylim(-0.02, 1.02)
    axis.grid(True, linestyle=":", alpha=0.4)
    figure.tight_layout(rect=(0, 0, 0.81, 1))
    return figure, axis


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
        help=f"2024 headway CSV directory (default: {DEFAULT_HEADWAY_DIR})",
    )
    parser.add_argument(
        "--corridor-dir",
        type=Path,
        default=DEFAULT_CORRIDOR_DIR,
        help=f"Consolidated stop-region directory (default: {DEFAULT_CORRIDOR_DIR})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path at which to save the plotted figure",
    )
    parser.add_argument(
        "--by-time",
        action="store_true",
        help="Plot a separate regression panel for each time period",
    )
    parser.add_argument(
        "--bus-far",
        action="store_true",
        help="Use bus_ratio_all instead of bus_ratio_near",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Do not open an interactive plot window",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    points = load_points(
        ratio_path=arguments.ratios,
        headway_dir=arguments.headway_dir,
        corridor_dir=arguments.corridor_dir,
    )
    figure, _ = create_plot(
        points,
        by_time=arguments.by_time,
        bus_far=arguments.bus_far,
    )
    if arguments.output is not None:
        output_path = arguments.output.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_path, dpi=200, bbox_inches="tight")
        print(f"Saved plot to {output_path}")
    print(f"Plotted {len(points)} region-time observations")
    if not arguments.no_show:
        plt.show()


if __name__ == "__main__":
    main()
