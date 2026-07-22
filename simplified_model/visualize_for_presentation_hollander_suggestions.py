"""Create presentation charts comparing the two WRTA projections.

The charts compare the existing August 2024 WRTA ridership total with the
``rescheduling only`` and ``rescheduling and Blue corridor investment``
projections.  The projected ridership increases are also treated as car trips
converted to transit, consistent with ``visualize_car_trip_conversion_totals``.

The Worcester car-trip baseline is the Region 2 to Region 2 total in the raw
TomTom matrix.  That source covers August 1-28, 2024; no extrapolation through
August 31 is performed.

Run from the repository root with::

    python simplified_model/visualize_for_presentation_hollander_suggestions.py

Use ``--no-show`` to write the PNG files without opening a chart window.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter

if __package__:
    from .last_min_ridership_aggregates import (
        DEFAULT_CORRIDOR_DIR,
        DEFAULT_RIDERSHIP_PATH,
        calculate_ridership_aggregates,
    )
    from .visualize_car_trip_conversion_totals import (
        DEFAULT_RAW_TOTALS_PATH,
        load_raw_trip_matrix,
    )
else:
    from last_min_ridership_aggregates import (
        DEFAULT_CORRIDOR_DIR,
        DEFAULT_RIDERSHIP_PATH,
        calculate_ridership_aggregates,
    )
    from visualize_car_trip_conversion_totals import (
        DEFAULT_RAW_TOTALS_PATH,
        load_raw_trip_matrix,
    )


MODEL_DIR = Path(__file__).resolve().parent
DEFAULT_RESCHEDULING_PATH = MODEL_DIR / "projected-ridership_sasha_shema.csv"
DEFAULT_INVESTMENT_PATH = (
    MODEL_DIR / "projected-ridership_sasha_shema_capital_investment_blue.csv"
)
DEFAULT_OUTPUT_DIR = MODEL_DIR / "hollander_suggestions_presentation_graphs"
WORCESTER_OD_KEY = ("Region 2", "Region 2")
REQUIRED_PROJECTION_COLUMNS = {
    "origin",
    "time",
    "corridor",
    "onboardings",
    "car_trips_0_800m",
    "car_trips_0_1600m",
    "car_trips_800_1600m",
    "projected_ridership",
    "ridership_increase",
}
EXPECTED_CORRIDORS = {"Blue", "Orange", "Green", "all"}
COMPARISON_TOLERANCE = Decimal("0.00001")

# A single dark/light pair keeps the meaning of the stacked areas consistent
# across scenarios and across all three figures.
DARK_COLOR = "#244A64"
LIGHT_COLOR = "#86BEDA"
ACCENT_COLOR = "#0D6E9C"
TEXT_COLOR = "#17242D"
GRID_COLOR = "#CAD4DA"
BACKGROUND_COLOR = "#F7F9FA"


@dataclass(frozen=True)
class BaselineProjectionRow:
    """Fields that must agree between the two projection inputs."""

    corridor: str
    onboardings: Decimal
    car_trips_0_800m: Decimal
    car_trips_0_1600m: Decimal
    car_trips_800_1600m: Decimal


@dataclass(frozen=True)
class ProjectionData:
    """Validated totals and baseline rows from one projection file."""

    input_path: Path
    rows_by_key: dict[tuple[str, str], BaselineProjectionRow]
    current_modeled_ridership: Decimal
    projected_modeled_ridership: Decimal
    ridership_increase: Decimal


@dataclass(frozen=True)
class ScenarioMetrics:
    """Presentation values calculated for one improvement scenario."""

    label: str
    short_label: str
    ridership_increase: Decimal
    existing_ridership: Decimal
    projected_ridership: Decimal
    original_car_trips: Decimal
    reduced_car_trips: Decimal
    ridership_growth_percent: Decimal
    car_conversion_percent: Decimal


@dataclass(frozen=True)
class PresentationData:
    """All values and source coverage needed by the three charts."""

    scenarios: tuple[ScenarioMetrics, ScenarioMetrics]
    car_start_date: date
    car_end_date: date


def _parse_decimal(
    value: str | None,
    column: str,
    input_path: Path,
    row_number: int,
    *,
    allow_negative: bool = False,
) -> Decimal:
    """Parse a finite CSV number and report its exact source on failure."""
    text = (value or "").strip()
    try:
        number = Decimal(text)
    except InvalidOperation as error:
        raise ValueError(
            f"{input_path}, row {row_number}, column {column!r} has "
            f"invalid value {text!r}"
        ) from error
    if not number.is_finite() or (number < 0 and not allow_negative):
        raise ValueError(
            f"{input_path}, row {row_number}, column {column!r} has "
            f"invalid value {text!r}"
        )
    return number


def load_projection_data(input_path: str | Path) -> ProjectionData:
    """Load one projection and calculate its modeled ridership totals."""
    input_path = Path(input_path).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Projection CSV does not exist: {input_path}")

    rows_by_key: dict[tuple[str, str], BaselineProjectionRow] = {}
    current_total = Decimal(0)
    projected_total = Decimal(0)
    increase_total = Decimal(0)

    with input_path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        missing_columns = REQUIRED_PROJECTION_COLUMNS - set(
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
            if not origin or not time:
                raise ValueError(
                    f"{input_path}, row {row_number} has a blank origin or time"
                )
            if corridor not in EXPECTED_CORRIDORS:
                raise ValueError(
                    f"{input_path}, row {row_number} has unknown corridor "
                    f"{corridor!r}"
                )
            key = (origin, time)
            if key in rows_by_key:
                raise ValueError(f"{input_path} contains duplicate key {key}")

            onboardings = _parse_decimal(
                row.get("onboardings"),
                "onboardings",
                input_path,
                row_number,
            )
            projected = _parse_decimal(
                row.get("projected_ridership"),
                "projected_ridership",
                input_path,
                row_number,
            )
            increase = _parse_decimal(
                row.get("ridership_increase"),
                "ridership_increase",
                input_path,
                row_number,
                allow_negative=True,
            )
            if abs(projected - onboardings - increase) > COMPARISON_TOLERANCE:
                raise ValueError(
                    f"{input_path}, row {row_number} does not satisfy "
                    "projected_ridership = onboardings + ridership_increase"
                )

            rows_by_key[key] = BaselineProjectionRow(
                corridor=corridor,
                onboardings=onboardings,
                car_trips_0_800m=_parse_decimal(
                    row.get("car_trips_0_800m"),
                    "car_trips_0_800m",
                    input_path,
                    row_number,
                ),
                car_trips_0_1600m=_parse_decimal(
                    row.get("car_trips_0_1600m"),
                    "car_trips_0_1600m",
                    input_path,
                    row_number,
                ),
                car_trips_800_1600m=_parse_decimal(
                    row.get("car_trips_800_1600m"),
                    "car_trips_800_1600m",
                    input_path,
                    row_number,
                ),
            )
            current_total += onboardings
            projected_total += projected
            increase_total += increase

    if not rows_by_key:
        raise ValueError(f"Projection CSV is empty: {input_path}")
    if increase_total <= 0:
        raise ValueError(
            f"Projection must have a positive aggregate increase: {input_path}"
        )
    if (
        abs(projected_total - current_total - increase_total)
        > COMPARISON_TOLERANCE * len(rows_by_key)
    ):
        raise ValueError(f"Projection totals do not reconcile: {input_path}")

    return ProjectionData(
        input_path=input_path,
        rows_by_key=rows_by_key,
        current_modeled_ridership=current_total,
        projected_modeled_ridership=projected_total,
        ridership_increase=increase_total,
    )


def _validate_comparable_projections(
    rescheduling: ProjectionData,
    investment: ProjectionData,
) -> None:
    """Ensure both scenarios use identical rows and baseline observations."""
    rescheduling_keys = set(rescheduling.rows_by_key)
    investment_keys = set(investment.rows_by_key)
    if rescheduling_keys != investment_keys:
        raise ValueError(
            "Projection inputs do not contain the same origin/time keys; "
            f"only in {rescheduling.input_path.name}: "
            f"{sorted(rescheduling_keys - investment_keys)}, only in "
            f"{investment.input_path.name}: "
            f"{sorted(investment_keys - rescheduling_keys)}"
        )

    mismatched_keys = [
        key
        for key in sorted(rescheduling_keys)
        if rescheduling.rows_by_key[key] != investment.rows_by_key[key]
    ]
    if mismatched_keys:
        raise ValueError(
            "Projection inputs have different baseline data for keys: "
            f"{mismatched_keys[:10]}"
        )


def load_presentation_data(
    ridership_path: str | Path = DEFAULT_RIDERSHIP_PATH,
    corridor_dir: str | Path = DEFAULT_CORRIDOR_DIR,
    rescheduling_path: str | Path = DEFAULT_RESCHEDULING_PATH,
    investment_path: str | Path = DEFAULT_INVESTMENT_PATH,
    raw_car_totals_path: str | Path = DEFAULT_RAW_TOTALS_PATH,
) -> PresentationData:
    """Load source files and calculate the two scenario-level comparisons."""
    existing_ridership = calculate_ridership_aggregates(
        ridership_path=ridership_path,
        corridor_dir=corridor_dir,
    ).all_lines
    if existing_ridership <= 0:
        raise ValueError("Existing WRTA ridership total must be positive")

    rescheduling = load_projection_data(rescheduling_path)
    investment = load_projection_data(investment_path)
    _validate_comparable_projections(rescheduling, investment)

    car_matrix = load_raw_trip_matrix(raw_car_totals_path)
    if WORCESTER_OD_KEY not in car_matrix.rows:
        raise ValueError(
            f"Raw car-trip matrix has no Worcester OD row {WORCESTER_OD_KEY}"
        )
    original_car_trips = sum(
        (
            Decimal(str(value))
            for value in car_matrix.rows[WORCESTER_OD_KEY].values()
        ),
        start=Decimal(0),
    )
    if original_car_trips <= 0:
        raise ValueError("Worcester car-trip total must be positive")

    scenario_inputs = (
        (
            "Rescheduling only",
            "Rescheduling\nonly",
            rescheduling.ridership_increase,
        ),
        (
            "Rescheduling and Blue corridor investment",
            "Rescheduling and\nBlue corridor investment",
            investment.ridership_increase,
        ),
    )
    scenarios = []
    for label, short_label, increase in scenario_inputs:
        if increase > original_car_trips:
            raise ValueError(
                f"{label} converts more car trips than the Worcester total"
            )
        scenarios.append(
            ScenarioMetrics(
                label=label,
                short_label=short_label,
                ridership_increase=increase,
                existing_ridership=existing_ridership,
                projected_ridership=existing_ridership + increase,
                original_car_trips=original_car_trips,
                reduced_car_trips=original_car_trips - increase,
                ridership_growth_percent=(
                    Decimal(100) * increase / existing_ridership
                ),
                car_conversion_percent=(
                    Decimal(100) * increase / original_car_trips
                ),
            )
        )

    return PresentationData(
        scenarios=(scenarios[0], scenarios[1]),
        car_start_date=car_matrix.start_date,
        car_end_date=car_matrix.end_date,
    )


def _count(value: Decimal) -> str:
    return f"{float(value):,.0f}"


def _percent(value: Decimal) -> str:
    return f"{float(value):.2f}%"


def _style_axis(axis) -> None:
    axis.set_facecolor(BACKGROUND_COLOR)
    axis.grid(axis="y", color=GRID_COLOR, linestyle=":", linewidth=1, zorder=0)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color("#8A9AA4")
    axis.spines["bottom"].set_color("#8A9AA4")
    axis.tick_params(colors=TEXT_COLOR)
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))


def _add_figure_note(figure: Figure, text: str) -> None:
    figure.text(
        0.5,
        0.018,
        text,
        ha="center",
        va="bottom",
        color="#4C5B64",
        fontsize=8.5,
    )


def create_ridership_bar_chart(data: PresentationData) -> Figure:
    """Create stacked bars for existing and additional WRTA ridership."""
    scenarios = data.scenarios
    positions = list(range(len(scenarios)))
    existing_values = [float(item.existing_ridership) for item in scenarios]
    increase_values = [float(item.ridership_increase) for item in scenarios]
    projected_values = [float(item.projected_ridership) for item in scenarios]

    figure, axis = plt.subplots(figsize=(12, 7.5), facecolor=BACKGROUND_COLOR)
    _style_axis(axis)
    existing_bars = axis.bar(
        positions,
        existing_values,
        width=0.58,
        color=DARK_COLOR,
        edgecolor="white",
        linewidth=0.8,
        label="Existing WRTA ridership",
        zorder=2,
    )
    increase_bars = axis.bar(
        positions,
        increase_values,
        width=0.58,
        bottom=existing_values,
        color=LIGHT_COLOR,
        edgecolor="white",
        linewidth=0.8,
        label="Projected ridership increase",
        zorder=2,
    )

    maximum_total = max(projected_values)
    for position, existing_bar, increase_bar, scenario in zip(
        positions,
        existing_bars,
        increase_bars,
        scenarios,
    ):
        center = existing_bar.get_x() + existing_bar.get_width() / 2
        axis.text(
            center,
            existing_bar.get_height() * 0.48,
            f"Existing WRTA ridership\n{_count(scenario.existing_ridership)}",
            ha="center",
            va="center",
            color="white",
            fontsize=11,
            fontweight="bold",
        )
        axis.text(
            center,
            existing_bar.get_height() + increase_bar.get_height() / 2,
            f"+{_count(scenario.ridership_increase)}",
            ha="center",
            va="center",
            color=TEXT_COLOR,
            fontsize=10,
            fontweight="bold",
        )
        axis.annotate(
            (
                f"Projected total: {_count(scenario.projected_ridership)}\n"
                f"Ridership growth: {_percent(scenario.ridership_growth_percent)}"
            ),
            xy=(position, float(scenario.projected_ridership)),
            xytext=(0, 14),
            textcoords="offset points",
            ha="center",
            va="bottom",
            color=TEXT_COLOR,
            fontsize=9.5,
            fontweight="bold",
            bbox={
                "boxstyle": "round,pad=0.35",
                "facecolor": "white",
                "edgecolor": LIGHT_COLOR,
                "linewidth": 1.2,
            },
        )

    axis.set_xticks(positions, [item.short_label for item in scenarios])
    axis.tick_params(axis="x", labelsize=10, pad=8)
    axis.set_ylabel("Monthly passenger boardings", color=TEXT_COLOR)
    axis.set_ylim(0, maximum_total * 1.25)
    axis.set_title(
        "Total Monthly WRTA Ridership With Proposed Improvements",
        color=TEXT_COLOR,
        fontsize=17,
        fontweight="bold",
        pad=42,
    )
    axis.text(
        0.5,
        1.025,
        "August 2024 actual ridership plus projected new riders",
        transform=axis.transAxes,
        ha="center",
        va="bottom",
        color="#52636D",
        fontsize=10.5,
    )
    axis.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 0.995),
        ncol=2,
        frameon=False,
    )
    _add_figure_note(
        figure,
        "Projected totals add each scenario's modeled ridership increase to the "
        "August 2024 systemwide WRTA total.",
    )
    figure.tight_layout(rect=(0.03, 0.06, 0.97, 0.94))
    return figure


def create_ridership_pie_charts(data: PresentationData) -> Figure:
    """Create one ridership pie for each projection scenario."""
    figure, axes = plt.subplots(
        1,
        2,
        figsize=(14, 7.8),
        facecolor=BACKGROUND_COLOR,
    )
    figure.suptitle(
        "Total Monthly WRTA Ridership With Proposed Improvements",
        color=TEXT_COLOR,
        fontsize=17,
        fontweight="bold",
        y=0.965,
    )
    figure.text(
        0.5,
        0.915,
        "August 2024 actual ridership and projected new riders",
        ha="center",
        color="#52636D",
        fontsize=10.5,
    )

    for axis, scenario in zip(axes, data.scenarios):
        axis.set_facecolor(BACKGROUND_COLOR)
        values = [
            float(scenario.existing_ridership),
            float(scenario.ridership_increase),
        ]
        labels = [
            f"Existing ridership\n{_count(scenario.existing_ridership)}",
            f"Projected increase\n+{_count(scenario.ridership_increase)}",
        ]
        _wedges, label_texts = axis.pie(
            values,
            labels=labels,
            colors=(DARK_COLOR, LIGHT_COLOR),
            explode=(0, 0.055),
            radius=0.86,
            startangle=90,
            counterclock=False,
            labeldistance=1.08,
            wedgeprops={"edgecolor": "white", "linewidth": 1.5},
            textprops={"color": TEXT_COLOR, "fontsize": 9.5},
        )
        for label_text in label_texts:
            label_text.set_fontweight("bold")

        axis.set_title(
            scenario.label,
            color=TEXT_COLOR,
            fontsize=12,
            fontweight="bold",
            pad=10,
        )

    for horizontal_position, scenario in zip((0.27, 0.73), data.scenarios):
        figure.text(
            horizontal_position,
            0.105,
            (
                f"Projected total: {_count(scenario.projected_ridership)}\n"
                f"Ridership growth: {_percent(scenario.ridership_growth_percent)}"
            ),
            ha="center",
            va="center",
            color=TEXT_COLOR,
            fontsize=9.5,
            fontweight="bold",
            bbox={
                "boxstyle": "round,pad=0.42",
                "facecolor": "white",
                "edgecolor": LIGHT_COLOR,
                "linewidth": 1.2,
            },
        )

    _add_figure_note(
        figure,
        "Each pie shows existing WRTA ridership and the projected increase; "
        "growth percentages are calculated against existing ridership.",
    )
    figure.tight_layout(rect=(0.02, 0.18, 0.98, 0.88), w_pad=4)
    return figure


def _format_date_range(start_date: date, end_date: date) -> str:
    if start_date.year == end_date.year and start_date.month == end_date.month:
        return (
            f"{start_date.strftime('%B')} {start_date.day}-{end_date.day}, "
            f"{start_date.year}"
        )
    return f"{start_date:%B %d, %Y} - {end_date:%B %d, %Y}"


def create_car_trip_bar_chart(data: PresentationData) -> Figure:
    """Create bars where converted trips are removed from the original total."""
    scenarios = data.scenarios
    positions = list(range(len(scenarios)))
    remaining_values = [float(item.reduced_car_trips) for item in scenarios]
    converted_values = [float(item.ridership_increase) for item in scenarios]
    original_values = [float(item.original_car_trips) for item in scenarios]

    figure, axis = plt.subplots(figsize=(12, 7.5), facecolor=BACKGROUND_COLOR)
    _style_axis(axis)
    remaining_bars = axis.bar(
        positions,
        remaining_values,
        width=0.58,
        color=DARK_COLOR,
        edgecolor="white",
        linewidth=0.8,
        label="Reduced car trips",
        zorder=2,
    )
    converted_bars = axis.bar(
        positions,
        converted_values,
        width=0.58,
        bottom=remaining_values,
        color=LIGHT_COLOR,
        edgecolor="white",
        linewidth=0.8,
        label="Trips converted to WRTA",
        zorder=2,
    )

    original_total = scenarios[0].original_car_trips
    axis.axhline(
        float(original_total),
        color=ACCENT_COLOR,
        linestyle="--",
        linewidth=1.3,
        alpha=0.8,
        zorder=1,
    )
    maximum_total = max(original_values)
    for position, remaining_bar, converted_bar, scenario in zip(
        positions,
        remaining_bars,
        converted_bars,
        scenarios,
    ):
        center = remaining_bar.get_x() + remaining_bar.get_width() / 2
        axis.text(
            center,
            remaining_bar.get_height() * 0.5,
            f"Remaining car trips\n{_count(scenario.reduced_car_trips)}",
            ha="center",
            va="center",
            color="white",
            fontsize=11,
            fontweight="bold",
        )
        axis.annotate(
            (
                f"Original: {_count(scenario.original_car_trips)}\n"
                f"Decrease: -{_count(scenario.ridership_increase)}\n"
                f"Converted: {_percent(scenario.car_conversion_percent)}"
            ),
            xy=(
                center,
                remaining_bar.get_height() + converted_bar.get_height() / 2,
            ),
            xytext=(0, 18),
            textcoords="offset points",
            ha="center",
            va="bottom",
            color=TEXT_COLOR,
            fontsize=9.5,
            fontweight="bold",
            arrowprops={
                "arrowstyle": "-|>",
                "color": ACCENT_COLOR,
                "linewidth": 1.1,
                "shrinkA": 2,
                "shrinkB": 2,
            },
            bbox={
                "boxstyle": "round,pad=0.35",
                "facecolor": "white",
                "edgecolor": LIGHT_COLOR,
                "linewidth": 1.2,
            },
        )

    axis.set_xticks(positions, [item.short_label for item in scenarios])
    axis.tick_params(axis="x", labelsize=10, pad=8)
    axis.set_ylabel("Worcester municipal car trips", color=TEXT_COLOR)
    axis.set_ylim(0, maximum_total * 1.22)
    date_range = _format_date_range(data.car_start_date, data.car_end_date)
    axis.set_title(
        "Total Worcester Car Trips With Proposed Improvements",
        color=TEXT_COLOR,
        fontsize=17,
        fontweight="bold",
        pad=42,
    )
    axis.text(
        0.5,
        1.025,
        date_range,
        transform=axis.transAxes,
        ha="center",
        va="bottom",
        color="#52636D",
        fontsize=10.5,
    )
    axis.legend(
        handles=(
            Patch(facecolor=DARK_COLOR, label="Car trips after improvement"),
            Patch(
                facecolor=LIGHT_COLOR,
                label="Trips converted to WRTA",
            ),
        ),
        loc="upper center",
        bbox_to_anchor=(0.5, 1.015),
        ncol=2,
        frameon=False,
    )
    _add_figure_note(
        figure,
        "Each bar starts from the same original total. The light segment is the "
        "share removed by assuming one new WRTA boarding replaces one car trip.",
    )
    figure.tight_layout(rect=(0.03, 0.06, 0.97, 0.94))
    return figure


def write_presentation_graphs(
    ridership_path: str | Path = DEFAULT_RIDERSHIP_PATH,
    corridor_dir: str | Path = DEFAULT_CORRIDOR_DIR,
    rescheduling_path: str | Path = DEFAULT_RESCHEDULING_PATH,
    investment_path: str | Path = DEFAULT_INVESTMENT_PATH,
    raw_car_totals_path: str | Path = DEFAULT_RAW_TOTALS_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> tuple[list[Path], PresentationData]:
    """Calculate presentation totals and write all three requested PNGs."""
    data = load_presentation_data(
        ridership_path=ridership_path,
        corridor_dir=corridor_dir,
        rescheduling_path=rescheduling_path,
        investment_path=investment_path,
        raw_car_totals_path=raw_car_totals_path,
    )
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    charts = (
        (
            "01_total_monthly_wrta_ridership_bars.png",
            create_ridership_bar_chart(data),
        ),
        (
            "02_total_monthly_wrta_ridership_pies.png",
            create_ridership_pie_charts(data),
        ),
        (
            "03_total_worcester_car_trips_bars.png",
            create_car_trip_bar_chart(data),
        ),
    )
    output_paths = []
    for filename, figure in charts:
        output_path = output_dir / filename
        figure.savefig(
            output_path,
            dpi=300,
            bbox_inches="tight",
            facecolor=figure.get_facecolor(),
        )
        output_paths.append(output_path)
    return output_paths, data


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
    parser.add_argument(
        "--rescheduling-projection",
        type=Path,
        default=DEFAULT_RESCHEDULING_PATH,
        help=(
            "Rescheduling-only projection CSV "
            f"(default: {DEFAULT_RESCHEDULING_PATH})"
        ),
    )
    parser.add_argument(
        "--investment-projection",
        type=Path,
        default=DEFAULT_INVESTMENT_PATH,
        help=(
            "Rescheduling plus Blue-investment projection CSV "
            f"(default: {DEFAULT_INVESTMENT_PATH})"
        ),
    )
    parser.add_argument(
        "--raw-car-totals",
        type=Path,
        default=DEFAULT_RAW_TOTALS_PATH,
        help=f"Raw Worcester OD totals CSV (default: {DEFAULT_RAW_TOTALS_PATH})",
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
        help="Write charts without opening an interactive window",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    output_paths, data = write_presentation_graphs(
        ridership_path=arguments.ridership_path,
        corridor_dir=arguments.corridor_dir,
        rescheduling_path=arguments.rescheduling_projection,
        investment_path=arguments.investment_projection,
        raw_car_totals_path=arguments.raw_car_totals,
        output_dir=arguments.output_dir,
    )
    for output_path in output_paths:
        print(f"Wrote {output_path}")
    for scenario in data.scenarios:
        print(
            f"{scenario.label}: +{_count(scenario.ridership_increase)} riders "
            f"({_percent(scenario.ridership_growth_percent)} growth), "
            f"{_percent(scenario.car_conversion_percent)} of car trips converted"
        )

    if arguments.no_show:
        plt.close("all")
    else:
        plt.show()


if __name__ == "__main__":
    main()
