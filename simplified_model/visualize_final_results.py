"""Visualize Sasha-schema ridership projections without modifying the CSV.

Four combination charts are generated: one each for the Blue, Orange, and
Green corridors, plus a black/gray chart for Hub Center (origin 1503).  Stacked
bars use the left axis for current and additional projected ridership.  Lines
use the right axis for the current and projected share of nearby trips made by
bus.

Run from the repository root with::

    python simplified_model/visualize_final_results.py
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patheffects as path_effects
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import PercentFormatter


DEFAULT_INPUT_PATH = (
    Path(__file__).resolve().parent / "projected-ridership_sasha_shema.csv"
)
DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parent / "final_results_chart_reformatted_1"
)
DATA_DATE_RANGE = "August 1–28, 2024"
REQUIRED_COLUMNS = {
    "origin",
    "time",
    "corridor",
    "onboardings",
    "car_trips_0_800m",
    "projected_ridership",
    "ridership_increase",
}
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


@dataclass(frozen=True)
class ProjectionRow:
    """Numeric fields needed from one projection CSV row."""

    origin: str
    time: str
    corridor: str
    onboardings: float
    nearby_car_trips: float
    projected_ridership: float
    ridership_increase: float


@dataclass(frozen=True)
class PeriodSummary:
    """Aggregated bar and line values for one chart period."""

    current_ridership: float
    additional_ridership: float
    current_bus_percent: float
    projected_bus_percent: float
    row_count: int


@dataclass(frozen=True)
class ChartGroup:
    """Selection, labels, and colors for one output chart."""

    name: str
    filename: str
    dark_color: str
    light_color: str
    corridor: str | None = None
    origin: str | None = None


CHART_GROUPS = (
    ChartGroup(
        name="Blue Corridor",
        filename="blue_corridor_combo.png",
        dark_color="#174A7E",
        light_color="#78AEDD",
        corridor="Blue",
    ),
    ChartGroup(
        name="Orange Corridor",
        filename="orange_corridor_combo.png",
        dark_color="#B84A00",
        light_color="#FDB77E",
        corridor="Orange",
    ),
    ChartGroup(
        name="Green Corridor",
        filename="green_corridor_combo.png",
        dark_color="#176D3A",
        light_color="#8DCEA0",
        corridor="Green",
    ),
    ChartGroup(
        name="Hub Center (Stop 1503)",
        filename="hub_center_1503_combo.png",
        dark_color="#1C1C1C",
        light_color="#A6A6A6",
        origin="1503",
    ),
)


def _parse_number(
    value: str | None,
    column: str,
    input_path: Path,
    row_number: int,
    *,
    allow_negative: bool = False,
) -> float:
    """Parse a finite number with file and row context."""
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


def load_projection_rows(
    input_path: str | Path = DEFAULT_INPUT_PATH,
) -> list[ProjectionRow]:
    """Read projection values without opening the source CSV for writing."""
    input_path = Path(input_path).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Projection CSV does not exist: {input_path}")

    rows: list[ProjectionRow] = []
    seen_keys: set[tuple[str, str]] = set()
    with input_path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing_columns:
            raise ValueError(
                f"{input_path} is missing columns: {sorted(missing_columns)}"
            )

        for row_number, row in enumerate(reader, start=2):
            origin = (row.get("origin") or "").strip()
            time = (row.get("time") or "").strip()
            corridor = (row.get("corridor") or "").strip()
            if not origin or not time or not corridor:
                raise ValueError(
                    f"{input_path}, row {row_number} has a blank origin, "
                    "time, or corridor"
                )
            if time not in TIME_PERIODS:
                raise ValueError(
                    f"{input_path}, row {row_number} has unknown time "
                    f"{time!r}"
                )
            key = (origin, time)
            if key in seen_keys:
                raise ValueError(f"{input_path} contains duplicate key {key}")
            seen_keys.add(key)

            rows.append(
                ProjectionRow(
                    origin=origin,
                    time=time,
                    corridor=corridor,
                    onboardings=_parse_number(
                        row.get("onboardings"),
                        "onboardings",
                        input_path,
                        row_number,
                    ),
                    nearby_car_trips=_parse_number(
                        row.get("car_trips_0_800m"),
                        "car_trips_0_800m",
                        input_path,
                        row_number,
                    ),
                    projected_ridership=_parse_number(
                        row.get("projected_ridership"),
                        "projected_ridership",
                        input_path,
                        row_number,
                    ),
                    ridership_increase=_parse_number(
                        row.get("ridership_increase"),
                        "ridership_increase",
                        input_path,
                        row_number,
                        allow_negative=True,
                    ),
                )
            )
    if not rows:
        raise ValueError(f"Projection CSV is empty: {input_path}")
    return rows


def _matches_group(row: ProjectionRow, group: ChartGroup) -> bool:
    """Return whether a projection row belongs in a chart."""
    if group.origin is not None:
        return row.origin == group.origin
    if group.corridor is not None:
        return row.corridor == group.corridor
    return True


def summarize_group(
    rows: list[ProjectionRow],
    group: ChartGroup,
) -> dict[str, PeriodSummary | None]:
    """Aggregate current/projected ridership and nearby bus percentages."""
    summaries: dict[str, PeriodSummary | None] = {}
    for time in TIME_PERIODS:
        period_rows = [
            row
            for row in rows
            if row.time == time and _matches_group(row, group)
        ]
        if not period_rows:
            summaries[time] = None
            continue

        current_ridership = math.fsum(
            row.onboardings for row in period_rows
        )
        additional_ridership = math.fsum(
            row.ridership_increase for row in period_rows
        )
        projected_ridership = math.fsum(
            row.projected_ridership for row in period_rows
        )
        nearby_trip_total = math.fsum(
            row.onboardings + row.nearby_car_trips for row in period_rows
        )
        if nearby_trip_total <= 0:
            raise ValueError(
                f"{group.name}, {time} has no nearby trips for percentages"
            )

        summaries[time] = PeriodSummary(
            current_ridership=current_ridership,
            additional_ridership=additional_ridership,
            current_bus_percent=100 * current_ridership / nearby_trip_total,
            projected_bus_percent=(
                100 * projected_ridership / nearby_trip_total
            ),
            row_count=len(period_rows),
        )
    return summaries


def _label_bars(
    axis: Axes,
    current_bars,
    additional_bars,
    summaries: list[PeriodSummary | None],
    dark_color: str,
    light_color: str,
) -> None:
    """Add readable current and incremental values to populated bars."""
    maximum_total = max(
        (
            summary.current_ridership + summary.additional_ridership
            for summary in summaries
            if summary is not None
        ),
        default=0,
    )
    for current_bar, additional_bar, summary in zip(
        current_bars,
        additional_bars,
        summaries,
    ):
        if summary is None:
            continue
        current_height = current_bar.get_height()
        additional_height = additional_bar.get_height()
        if current_height >= maximum_total * 0.025:
            axis.annotate(
                f"{current_height:,.0f}",
                xy=(
                    current_bar.get_x() + current_bar.get_width() / 2,
                    current_height * 0.35,
                ),
                ha="center",
                va="center",
                color="white",
                fontsize=8,
                fontweight="bold",
                zorder=6,
                bbox={
                    "boxstyle": "round,pad=0.12",
                    "facecolor": dark_color,
                    "edgecolor": "none",
                    "alpha": 0.9,
                },
            )
        if abs(additional_height) >= 0.5:
            is_large_segment = additional_height >= maximum_total * 0.025
            axis.annotate(
                f"+{additional_height:,.0f}",
                xy=(
                    additional_bar.get_x() + additional_bar.get_width() / 2,
                    (
                        current_height + additional_height / 2
                        if is_large_segment
                        else current_height + additional_height
                    ),
                ),
                xytext=(0, 0 if is_large_segment else 3),
                textcoords="offset points",
                ha="center",
                va="center" if is_large_segment else "bottom",
                color=dark_color if is_large_segment else "black",
                fontsize=8,
                fontweight="bold",
                zorder=6,
                bbox={
                    "boxstyle": "round,pad=0.12",
                    "facecolor": light_color if is_large_segment else "white",
                    "edgecolor": "none",
                    "alpha": 0.9,
                },
            )


def _label_percentages(
    axis: Axes,
    positions: list[int],
    values: list[float],
    color: str,
    horizontal_offset: int,
    vertical_offset: int,
    horizontal_alignment: str,
) -> None:
    """Label each available percentage marker."""
    for position, value in zip(positions, values):
        if math.isnan(value):
            continue
        axis.annotate(
            f"{value:.1f}%",
            xy=(position, value),
            xytext=(horizontal_offset, vertical_offset),
            textcoords="offset points",
            ha=horizontal_alignment,
            va="bottom" if vertical_offset >= 0 else "top",
            color=color,
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


def create_combo_chart(
    rows: list[ProjectionRow],
    group: ChartGroup,
) -> Figure:
    """Create one stacked-bar and two-line combination chart."""
    summary_by_time = summarize_group(rows, group)
    summaries = [summary_by_time[time] for time in TIME_PERIODS]
    positions = list(range(len(TIME_PERIODS)))
    current_values = [
        summary.current_ridership if summary is not None else 0
        for summary in summaries
    ]
    additional_values = [
        summary.additional_ridership if summary is not None else 0
        for summary in summaries
    ]
    current_percentages = [
        summary.current_bus_percent if summary is not None else math.nan
        for summary in summaries
    ]
    projected_percentages = [
        summary.projected_bus_percent if summary is not None else math.nan
        for summary in summaries
    ]

    figure, left_axis = plt.subplots(figsize=(13, 7.5))
    current_bars = left_axis.bar(
        positions,
        current_values,
        width=0.64,
        color=group.dark_color,
        label="Current ridership",
        zorder=2,
    )
    additional_bars = left_axis.bar(
        positions,
        additional_values,
        width=0.64,
        bottom=current_values,
        color=group.light_color,
        label="Additional projected ridership",
        zorder=2,
    )

    right_axis = left_axis.twinx()
    current_line = right_axis.plot(
        positions,
        current_percentages,
        color=group.dark_color,
        marker="o",
        markersize=7,
        markeredgecolor="white",
        markeredgewidth=1,
        linewidth=2.4,
        label="Current nearby-trip bus share",
        zorder=4,
    )[0]
    projected_line = right_axis.plot(
        positions,
        projected_percentages,
        color=group.light_color,
        marker="o",
        markersize=7,
        markeredgecolor="white",
        markeredgewidth=1,
        linewidth=2.4,
        label="Projected nearby-trip bus share",
        zorder=4,
    )[0]
    line_outline = [
        path_effects.Stroke(linewidth=4.2, foreground="white", alpha=0.8),
        path_effects.Normal(),
    ]
    current_line.set_path_effects(line_outline)
    projected_line.set_path_effects(line_outline)

    _label_bars(
        left_axis,
        current_bars,
        additional_bars,
        summaries,
        group.dark_color,
        group.light_color,
    )
    _label_percentages(
        right_axis,
        positions,
        current_percentages,
        group.dark_color,
        -24,
        -15,
        "right",
    )
    _label_percentages(
        right_axis,
        positions,
        projected_percentages,
        group.light_color,
        24,
        7,
        "left",
    )

    maximum_rows = max(
        summary.row_count for summary in summaries if summary is not None
    )
    tick_labels: list[str] = []
    for time, summary in zip(TIME_PERIODS, summaries):
        if summary is None:
            tick_labels.append(f"{TIME_LABELS[time]}\nno projection")
        elif summary.row_count < maximum_rows:
            tick_labels.append(
                f"{TIME_LABELS[time]}\nn={summary.row_count}/{maximum_rows}"
            )
        else:
            tick_labels.append(TIME_LABELS[time])

    left_axis.set_xticks(positions, tick_labels)
    left_axis.set_xlabel("Time period")
    left_axis.set_ylabel("Ridership")
    right_axis.set_ylabel("Nearby trips made by bus")
    right_axis.set_ylim(0, 100)
    right_axis.yaxis.set_major_formatter(PercentFormatter(xmax=100))
    left_axis.grid(axis="y", linestyle=":", alpha=0.45, zorder=0)
    left_axis.set_axisbelow(True)
    left_axis.spines["top"].set_visible(False)
    right_axis.spines["top"].set_visible(False)
    figure.suptitle(
        f"{group.name}: Ridership and Nearby-Trip Bus Share\n{DATA_DATE_RANGE}",
        y=0.98,
        fontsize=14,
        fontweight="bold",
    )

    handles = [
        current_bars,
        additional_bars,
        current_line,
        projected_line,
    ]
    labels = [handle.get_label() for handle in handles]
    figure.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.89),
        ncol=2,
        frameon=False,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.82))
    return figure


def write_charts(
    input_path: str | Path = DEFAULT_INPUT_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> list[Path]:
    """Read the projection CSV and save all four charts."""
    rows = load_projection_rows(input_path)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    written_paths: list[Path] = []
    for group in CHART_GROUPS:
        figure = create_combo_chart(rows, group)
        output_path = output_dir / group.filename
        figure.savefig(output_path, dpi=200, bbox_inches="tight")
        written_paths.append(output_path)
    return written_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"Projection CSV (default: {DEFAULT_INPUT_PATH})",
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
    written_paths = write_charts(arguments.input, arguments.output_dir)
    for output_path in written_paths:
        print(f"Wrote {output_path}")
    if arguments.no_show:
        plt.close("all")
    else:
        plt.show()


if __name__ == "__main__":
    main()
