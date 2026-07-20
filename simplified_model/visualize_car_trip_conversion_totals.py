"""Calculate and visualize car-trip conversion totals by time period.

The raw TomTom matrix is opened read-only.  The corridor chart uses only the
``Region 1`` to ``Region 1`` row, while the Worcester municipal chart uses
only the ``Region 2`` to ``Region 2`` row.  Converted trips are the summed
``ridership_increase`` values for the Orange, Blue, Green, and Hub Center rows
in ``projected-ridership_sasha_shema.csv``.

Each chart stacks converted trips on top of remaining trips (total minus
converted), overlays the percentage converted, and displays overall totals in
a text box.

Run from the repository root with::

    python simplified_model/visualize_car_trip_conversion_totals.py
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.ticker import PercentFormatter


MODEL_DIR = Path(__file__).resolve().parent
DEFAULT_RAW_TOTALS_PATH = (
    MODEL_DIR / "worcester_and_corridor_totals_aggregate_raw.csv"
)
DEFAULT_PROJECTION_PATH = MODEL_DIR / "projected-ridership_sasha_shema.csv"
DEFAULT_OUTPUT_DIR = MODEL_DIR / "car_trip_conversion_charts"
TIME_PERIODS = (
    "04:00 - 06:00",
    "06:00 - 09:00",
    "09:00 - 15:00",
    "15:00 - 18:00",
    "18:00 - 22:00",
    "22:00 - 00:00",
)
TIME_LABELS = {
    "04:00 - 06:00": "04:00–06:00",
    "06:00 - 09:00": "06:00–09:00",
    "09:00 - 15:00": "09:00–15:00",
    "15:00 - 18:00": "15:00–18:00",
    "18:00 - 22:00": "18:00–22:00",
    "22:00 - 00:00": "22:00–00:00",
}
TRIP_COLUMN_PATTERN = re.compile(
    r"Date range: (?P<start>\d{4}-\d{2}-\d{2}) - "
    r"(?P<end>\d{4}-\d{2}-\d{2}) Time range: "
    r"(?P<time>\d{2}:\d{2} - \d{2}:\d{2}) Trips"
)
PROJECTION_REQUIRED_COLUMNS = {
    "origin",
    "time",
    "corridor",
    "ridership_increase",
}
EXPECTED_PROJECTION_CORRIDORS = {"Orange", "Blue", "Green", "all"}


@dataclass(frozen=True)
class RawTripMatrix:
    """Trip totals and metadata loaded from the raw OD matrix."""

    start_date: date
    end_date: date
    rows: dict[tuple[str, str], dict[str, float]]


@dataclass(frozen=True)
class ConversionTotals:
    """Converted-trip totals and projection coverage by period."""

    converted_by_time: dict[str, float]
    row_count_by_time: dict[str, int]


@dataclass(frozen=True)
class ChartSpec:
    """Region selection and visual styling for one chart."""

    title: str
    origin: str
    destination: str
    filename: str
    dark_color: str
    light_color: str
    line_color: str


CHART_SPECS = (
    ChartSpec(
        title="Corridor-to-Corridor Car Trips",
        origin="Region 1",
        destination="Region 1",
        filename="corridor_car_trip_conversion.png",
        dark_color="#264A60",
        light_color="#8FC1DC",
        line_color="#B5521D",
    ),
    ChartSpec(
        title="Worcester Municipal Car Trips",
        origin="Region 2",
        destination="Region 2",
        filename="worcester_municipal_car_trip_conversion.png",
        dark_color="#303030",
        light_color="#A9A9A9",
        line_color="#A14B2A",
    ),
)


def _parse_nonnegative_number(
    value: str | None,
    column: str,
    input_path: Path,
    row_number: int,
    *,
    allow_negative: bool = False,
) -> float:
    """Parse a finite CSV value with row context."""
    text = (value or "").strip()
    try:
        number = float(text)
    except ValueError as error:
        raise ValueError(
            f"{input_path}, row {row_number}, column {column!r} has "
            f"invalid value {text!r}"
        ) from error
    if not math.isfinite(number) or (number < 0 and not allow_negative):
        raise ValueError(
            f"{input_path}, row {row_number}, column {column!r} has "
            f"invalid value {text!r}"
        )
    return number


def load_raw_trip_matrix(
    input_path: str | Path = DEFAULT_RAW_TOTALS_PATH,
) -> RawTripMatrix:
    """Load time-period trip totals from every raw origin/destination row."""
    input_path = Path(input_path).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Raw trip-total CSV does not exist: {input_path}")

    with input_path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        fieldnames = list(reader.fieldnames or ())
        if "Origin" not in fieldnames or "Destination" not in fieldnames:
            raise ValueError(
                f"{input_path} must contain Origin and Destination columns"
            )

        trip_columns: dict[str, str] = {}
        date_ranges: set[tuple[date, date]] = set()
        for column in fieldnames:
            match = TRIP_COLUMN_PATTERN.fullmatch(column)
            if match is None:
                continue
            time = match.group("time")
            if time in trip_columns:
                raise ValueError(
                    f"{input_path} contains duplicate trip period {time!r}"
                )
            trip_columns[time] = column
            date_ranges.add(
                (
                    date.fromisoformat(match.group("start")),
                    date.fromisoformat(match.group("end")),
                )
            )

        missing_times = set(TIME_PERIODS) - set(trip_columns)
        extra_times = set(trip_columns) - set(TIME_PERIODS)
        if missing_times or extra_times:
            raise ValueError(
                f"{input_path} has unexpected trip periods; missing "
                f"{sorted(missing_times)}, extra {sorted(extra_times)}"
            )
        if len(date_ranges) != 1:
            raise ValueError(
                f"{input_path} must use one common date range; found "
                f"{sorted(date_ranges)}"
            )
        start_date, end_date = next(iter(date_ranges))

        rows: dict[tuple[str, str], dict[str, float]] = {}
        for row_number, row in enumerate(reader, start=2):
            origin = (row.get("Origin") or "").strip()
            destination = (row.get("Destination") or "").strip()
            if not origin or not destination:
                raise ValueError(
                    f"{input_path}, row {row_number} has a blank region"
                )
            key = (origin, destination)
            if key in rows:
                raise ValueError(f"{input_path} contains duplicate OD row {key}")
            rows[key] = {
                time: _parse_nonnegative_number(
                    row.get(trip_columns[time]),
                    trip_columns[time],
                    input_path,
                    row_number,
                )
                for time in TIME_PERIODS
            }

    return RawTripMatrix(
        start_date=start_date,
        end_date=end_date,
        rows=rows,
    )


def load_conversion_totals(
    input_path: str | Path = DEFAULT_PROJECTION_PATH,
) -> ConversionTotals:
    """Sum converted trips across all corridors and Hub Center by period."""
    input_path = Path(input_path).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Projection CSV does not exist: {input_path}")

    converted_by_time = {time: 0.0 for time in TIME_PERIODS}
    row_count_by_time = {time: 0 for time in TIME_PERIODS}
    seen_keys: set[tuple[str, str]] = set()
    with input_path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        missing_columns = PROJECTION_REQUIRED_COLUMNS - set(
            reader.fieldnames or ()
        )
        if missing_columns:
            raise ValueError(
                f"{input_path} is missing columns: {sorted(missing_columns)}"
            )

        for row_number, row in enumerate(reader, start=2):
            origin = (row.get("origin") or "").strip()
            time = (row.get("time") or "").strip()
            corridor = (row.get("corridor") or "").strip()
            if not origin or time not in converted_by_time:
                raise ValueError(
                    f"{input_path}, row {row_number} has invalid origin or time"
                )
            if corridor not in EXPECTED_PROJECTION_CORRIDORS:
                raise ValueError(
                    f"{input_path}, row {row_number} has unknown corridor "
                    f"{corridor!r}"
                )
            if corridor == "all" and origin != "1503":
                raise ValueError(
                    f"{input_path}, row {row_number} has a non-Hub Center "
                    "row labelled 'all'"
                )
            key = (origin, time)
            if key in seen_keys:
                raise ValueError(f"{input_path} contains duplicate key {key}")
            seen_keys.add(key)

            converted_by_time[time] += _parse_nonnegative_number(
                row.get("ridership_increase"),
                "ridership_increase",
                input_path,
                row_number,
                allow_negative=True,
            )
            row_count_by_time[time] += 1

    if not seen_keys:
        raise ValueError(f"Projection CSV is empty: {input_path}")
    return ConversionTotals(
        converted_by_time=converted_by_time,
        row_count_by_time=row_count_by_time,
    )


def _date_range_label(start_date: date, end_date: date) -> str:
    """Format the shared raw-data date range for chart titles."""
    if start_date.year == end_date.year and start_date.month == end_date.month:
        return (
            f"{start_date.strftime('%B')} {start_date.day}–{end_date.day}, "
            f"{start_date.year}"
        )
    return f"{start_date:%B %d, %Y}–{end_date:%B %d, %Y}"


def _percentage_axis_limit(percentages: list[float]) -> float:
    """Choose a readable percentage ceiling without forcing a 0–100 scale."""
    maximum = max(percentages, default=0)
    if maximum <= 5:
        step = 1
    elif maximum <= 20:
        step = 5
    else:
        step = 10
    return max(step, math.ceil(maximum * 1.22 / step) * step)


def create_conversion_chart(
    total_trips_by_time: dict[str, float],
    conversions: ConversionTotals,
    spec: ChartSpec,
    date_range_label: str,
) -> Figure:
    """Create one stacked-bar and conversion-percentage combination chart."""
    positions = list(range(len(TIME_PERIODS)))
    total_values = [total_trips_by_time[time] for time in TIME_PERIODS]
    converted_values = [
        conversions.converted_by_time[time] for time in TIME_PERIODS
    ]
    remaining_values: list[float] = []
    percentages: list[float] = []
    for time, total, converted in zip(
        TIME_PERIODS,
        total_values,
        converted_values,
    ):
        if converted > total + 1e-6:
            raise ValueError(
                f"{spec.title}, {time} has {converted} converted trips but "
                f"only {total} total trips"
            )
        remaining_values.append(max(total - converted, 0))
        percentages.append(100 * converted / total if total else 0)

    figure, left_axis = plt.subplots(figsize=(13, 7.5))
    remaining_bars = left_axis.bar(
        positions,
        remaining_values,
        width=0.64,
        color=spec.dark_color,
        label="Remaining car trips",
        zorder=2,
    )
    converted_bars = left_axis.bar(
        positions,
        converted_values,
        width=0.64,
        bottom=remaining_values,
        color=spec.light_color,
        label="Trips converted to bus",
        zorder=2,
    )

    right_axis = left_axis.twinx()
    percentage_line = right_axis.plot(
        positions,
        percentages,
        color=spec.line_color,
        marker="o",
        markersize=7,
        markeredgecolor="white",
        markeredgewidth=1,
        linewidth=2.5,
        label="Percent of trips converted",
        zorder=4,
    )[0]
    percentage_line.set_path_effects(
        [
            path_effects.Stroke(
                linewidth=4.2,
                foreground="white",
                alpha=0.85,
            ),
            path_effects.Normal(),
        ]
    )

    maximum_total = max(total_values)
    for remaining_bar, converted_bar, remaining, converted in zip(
        remaining_bars,
        converted_bars,
        remaining_values,
        converted_values,
    ):
        center_x = remaining_bar.get_x() + remaining_bar.get_width() / 2
        if remaining >= maximum_total * 0.02:
            left_axis.annotate(
                f"{remaining:,.0f}",
                xy=(center_x, remaining * 0.35),
                ha="center",
                va="center",
                color="white",
                fontsize=8,
                fontweight="bold",
                zorder=6,
                bbox={
                    "boxstyle": "round,pad=0.12",
                    "facecolor": spec.dark_color,
                    "edgecolor": "none",
                    "alpha": 0.9,
                },
            )
        if converted >= 0.5:
            large_segment = converted >= maximum_total * 0.02
            left_axis.annotate(
                f"+{converted:,.0f}",
                xy=(
                    center_x,
                    remaining + converted / 2
                    if large_segment
                    else remaining + converted,
                ),
                xytext=(0, 0 if large_segment else 3),
                textcoords="offset points",
                ha="center",
                va="center" if large_segment else "bottom",
                color=spec.dark_color if large_segment else "black",
                fontsize=8,
                fontweight="bold",
                zorder=6,
                bbox={
                    "boxstyle": "round,pad=0.12",
                    "facecolor": spec.light_color if large_segment else "white",
                    "edgecolor": "none",
                    "alpha": 0.92,
                },
            )

    for position, percentage in zip(positions, percentages):
        right_axis.annotate(
            f"{percentage:.2f}%",
            xy=(position, percentage),
            xytext=(22, 8),
            textcoords="offset points",
            ha="left",
            va="bottom",
            color=spec.line_color,
            fontsize=8,
            fontweight="bold",
            zorder=7,
            bbox={
                "boxstyle": "round,pad=0.12",
                "facecolor": "white",
                "edgecolor": "none",
                "alpha": 0.92,
            },
        )

    maximum_rows = max(conversions.row_count_by_time.values())
    tick_labels: list[str] = []
    for time in TIME_PERIODS:
        row_count = conversions.row_count_by_time[time]
        if row_count < maximum_rows:
            tick_labels.append(
                f"{TIME_LABELS[time]}\nprojection n={row_count}/{maximum_rows}"
            )
        else:
            tick_labels.append(TIME_LABELS[time])
    left_axis.set_xticks(positions, tick_labels)
    left_axis.set_xlabel("Time period")
    left_axis.set_ylabel("Car trips")
    right_axis.set_ylabel("Trips converted to bus (%)")
    right_axis.set_ylim(0, _percentage_axis_limit(percentages))
    right_axis.yaxis.set_major_formatter(PercentFormatter(xmax=100))
    left_axis.grid(axis="y", linestyle=":", alpha=0.45, zorder=0)
    left_axis.set_axisbelow(True)
    left_axis.spines["top"].set_visible(False)
    right_axis.spines["top"].set_visible(False)

    total_trips = math.fsum(total_values)
    total_converted = math.fsum(converted_values)
    total_percentage = 100 * total_converted / total_trips
    left_axis.text(
        0.98,
        0.96,
        (
            f"Total car trips: {total_trips:,.0f}\n"
            f"Total converted: {total_converted:,.0f}\n"
            f"Overall converted: {total_percentage:.2f}%"
        ),
        transform=left_axis.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        bbox={
            "boxstyle": "round,pad=0.45",
            "facecolor": "white",
            "edgecolor": "#777777",
            "alpha": 0.94,
        },
        zorder=8,
    )

    figure.suptitle(
        f"{spec.title}: Converted versus Remaining\n{date_range_label}",
        y=0.98,
        fontsize=14,
        fontweight="bold",
    )
    handles = [remaining_bars, converted_bars, percentage_line]
    figure.legend(
        handles,
        [handle.get_label() for handle in handles],
        loc="upper center",
        bbox_to_anchor=(0.5, 0.89),
        ncol=3,
        frameon=False,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.82))
    return figure


def write_conversion_charts(
    raw_totals_path: str | Path = DEFAULT_RAW_TOTALS_PATH,
    projection_path: str | Path = DEFAULT_PROJECTION_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> list[Path]:
    """Calculate the requested totals and save both combo charts."""
    matrix = load_raw_trip_matrix(raw_totals_path)
    conversions = load_conversion_totals(projection_path)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    date_range_label = _date_range_label(matrix.start_date, matrix.end_date)

    output_paths: list[Path] = []
    for spec in CHART_SPECS:
        key = (spec.origin, spec.destination)
        if key not in matrix.rows:
            raise ValueError(
                f"Raw trip matrix does not contain requested OD row {key}"
            )
        figure = create_conversion_chart(
            total_trips_by_time=matrix.rows[key],
            conversions=conversions,
            spec=spec,
            date_range_label=date_range_label,
        )
        output_path = output_dir / spec.filename
        figure.savefig(output_path, dpi=200, bbox_inches="tight")
        output_paths.append(output_path)
    return output_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-totals",
        type=Path,
        default=DEFAULT_RAW_TOTALS_PATH,
        help=f"Raw OD trip matrix (default: {DEFAULT_RAW_TOTALS_PATH})",
    )
    parser.add_argument(
        "--projections",
        type=Path,
        default=DEFAULT_PROJECTION_PATH,
        help=f"Projection CSV (default: {DEFAULT_PROJECTION_PATH})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Chart output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save charts without opening interactive windows",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    output_paths = write_conversion_charts(
        raw_totals_path=arguments.raw_totals,
        projection_path=arguments.projections,
        output_dir=arguments.output_dir,
    )
    for output_path in output_paths:
        print(f"Wrote {output_path}")
    if arguments.no_show:
        plt.close("all")
    else:
        plt.show()


if __name__ == "__main__":
    main()
