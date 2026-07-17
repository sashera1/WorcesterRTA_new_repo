"""Display 2024 expected wait time against time-period stop ridership.

Each point represents one stop, direction, and time period from the 2024
aggregate CSVs.  Ridership is the corresponding ``total_boardings`` value.  The
source CSVs are opened read-only, and this script only displays a Matplotlib
figure; it does not write an image or change data.

Run from the repository root with::

    python simplified_model/headway_ridership_correlation.py
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


DEFAULT_INPUT_DIR = Path(__file__).resolve().parent / "2024_headway_aggregate"
CORRIDOR_COLORS = {
    "Orange": "tab:orange",
    "Blue": "tab:blue",
    "Green": "tab:green",
}
DIRECTION_MARKERS = {
    "inbound": r"$\mathrm{i}$",
    "outbound": r"$\mathrm{o}$",
}
REQUIRED_COLUMNS = {
    "corridor",
    "direction",
    "time_period",
    "ridership_calculation_status",
    "total_boardings",
    "expected_wait_minutes",
}


@dataclass(frozen=True)
class PlotPoint:
    expected_wait_minutes: float
    total_boardings: float
    corridor: str
    direction: str


@dataclass(frozen=True)
class LinearFit:
    slope: float
    intercept: float
    pearson_r: float
    r_squared: float


def load_points(input_dir: str | Path = DEFAULT_INPUT_DIR) -> list[PlotPoint]:
    """Read valid plotting points without modifying the aggregate CSVs."""
    input_dir = Path(input_dir).resolve()
    input_paths = sorted(input_dir.glob("*_headways.csv"))
    if not input_paths:
        raise FileNotFoundError(f"No aggregate headway CSVs found in {input_dir}")

    points: list[PlotPoint] = []
    for input_path in input_paths:
        with input_path.open("r", encoding="utf-8-sig", newline="") as input_file:
            reader = csv.DictReader(input_file)
            missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames or ())
            if missing_columns:
                raise ValueError(
                    f"{input_path} is missing columns: {sorted(missing_columns)}"
                )

            for row in reader:
                # A point needs both a raw-sum ridership observation and a
                # usable within-period expected-wait estimate.
                if row["ridership_calculation_status"] != "ok":
                    continue
                if not row["expected_wait_minutes"] or not row["total_boardings"]:
                    continue

                corridor = row["corridor"].strip()
                direction = row["direction"].strip().lower()
                if corridor not in CORRIDOR_COLORS:
                    raise ValueError(
                        f"Unknown corridor {corridor!r} in {input_path}"
                    )
                if direction not in DIRECTION_MARKERS:
                    raise ValueError(
                        f"Unknown direction {direction!r} in {input_path}"
                    )

                try:
                    expected_wait = float(row["expected_wait_minutes"])
                    total_boardings = float(row["total_boardings"])
                except ValueError as error:
                    raise ValueError(
                        f"Invalid numeric plotting value in {input_path}: {row}"
                    ) from error

                if not math.isfinite(expected_wait) or not math.isfinite(
                    total_boardings
                ):
                    raise ValueError(f"Non-finite plotting value in {input_path}")

                points.append(
                    PlotPoint(
                        expected_wait_minutes=expected_wait,
                        total_boardings=total_boardings,
                        corridor=corridor,
                        direction=direction,
                    )
                )

    if len(points) < 2:
        raise ValueError("At least two valid points are required for a best-fit line")
    return points


def calculate_linear_fit(points: list[PlotPoint]) -> LinearFit:
    """Calculate ordinary least squares and Pearson's correlation coefficient."""
    x_values = [point.expected_wait_minutes for point in points]
    y_values = [point.total_boardings for point in points]
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)

    x_deviations = [value - x_mean for value in x_values]
    y_deviations = [value - y_mean for value in y_values]
    sum_x_squared = sum(value * value for value in x_deviations)
    sum_y_squared = sum(value * value for value in y_deviations)
    sum_cross_products = sum(
        x_deviation * y_deviation
        for x_deviation, y_deviation in zip(x_deviations, y_deviations)
    )

    if sum_x_squared == 0:
        raise ValueError("Expected wait time has no variation; line fit is undefined")
    if sum_y_squared == 0:
        raise ValueError("Ridership has no variation; correlation is undefined")

    slope = sum_cross_products / sum_x_squared
    intercept = y_mean - slope * x_mean
    pearson_r = sum_cross_products / math.sqrt(sum_x_squared * sum_y_squared)
    return LinearFit(
        slope=slope,
        intercept=intercept,
        pearson_r=pearson_r,
        r_squared=pearson_r**2,
    )


def equation_text(fit: LinearFit) -> str:
    sign = "+" if fit.intercept >= 0 else "-"
    return f"y = {fit.slope:.3f}x {sign} {abs(fit.intercept):.3f}"


def create_plot(points: list[PlotPoint]):
    """Create and return the figure; callers decide when to display it."""
    fit = calculate_linear_fit(points)
    figure, axis = plt.subplots(figsize=(11, 7.5))

    for corridor, color in CORRIDOR_COLORS.items():
        for direction, marker in DIRECTION_MARKERS.items():
            matching_points = [
                point
                for point in points
                if point.corridor == corridor and point.direction == direction
            ]
            if not matching_points:
                continue
            axis.scatter(
                [point.expected_wait_minutes for point in matching_points],
                [point.total_boardings for point in matching_points],
                color=color,
                marker=marker,
                s=75,
                alpha=0.72,
                linewidths=0.5,
            )

    minimum_wait = min(point.expected_wait_minutes for point in points)
    maximum_wait = max(point.expected_wait_minutes for point in points)
    fit_x = [minimum_wait, maximum_wait]
    fit_y = [fit.slope * value + fit.intercept for value in fit_x]
    axis.plot(fit_x, fit_y, color="black", linestyle="--", linewidth=2)

    statistics_text = (
        f"Best fit: {equation_text(fit)}\n"
        f"Pearson r = {fit.pearson_r:.3f}\n"
        f"R^2 = {fit.r_squared:.3f}\n"
        f"n = {len(points)}"
    )
    axis.text(
        0.02,
        0.98,
        statistics_text,
        transform=axis.transAxes,
        ha="left",
        va="top",
        bbox={"boxstyle": "round,pad=0.45", "facecolor": "white", "alpha": 0.9},
    )

    legend_handles = [
        Line2D(
            [],
            [],
            color=color,
            marker="o",
            linestyle="None",
            markersize=8,
            label=f"{corridor} corridor",
        )
        for corridor, color in CORRIDOR_COLORS.items()
    ]
    legend_handles.extend(
        [
            Line2D(
                [],
                [],
                color="black",
                marker=marker,
                linestyle="None",
                markersize=9,
                label=direction.capitalize(),
            )
            for direction, marker in DIRECTION_MARKERS.items()
        ]
    )
    legend_handles.append(
        Line2D(
            [],
            [],
            color="black",
            linestyle="--",
            linewidth=2,
            label="Overall best fit",
        )
    )
    axis.legend(handles=legend_handles, loc="upper right")

    axis.set_xlabel("Expected wait time (minutes)")
    axis.set_ylabel("Total boardings")
    axis.set_title("2024 Expected Wait Time vs. Ridership")
    axis.grid(True, linestyle=":", alpha=0.4)
    figure.tight_layout()
    return figure, axis


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Aggregate CSV directory (default: {DEFAULT_INPUT_DIR})",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    points = load_points(arguments.input_dir)
    create_plot(points)
    plt.show()


if __name__ == "__main__":
    main()
