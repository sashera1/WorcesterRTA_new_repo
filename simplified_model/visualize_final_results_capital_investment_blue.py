"""Visualize the Blue capital-investment ridership projection.

This script reads the capital-investment projection CSV without modifying it.
It writes the four corridor/Hub Center charts and the all-corridors aggregate
chart using the same formatting as ``visualize_final_results.py``.

Run from the repository root with::

    python simplified_model/visualize_final_results_capital_investment_blue.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

if __package__:
    from .project_ridership_capital_investment_blue import DEFAULT_OUTPUT_PATH
    from .visualize_final_results import (
        ChartGroup,
        create_combo_chart,
        load_projection_rows,
    )
else:
    from project_ridership_capital_investment_blue import DEFAULT_OUTPUT_PATH
    from visualize_final_results import (
        ChartGroup,
        create_combo_chart,
        load_projection_rows,
    )


DEFAULT_INDIVIDUAL_OUTPUT_DIR = (
    Path(__file__).resolve().parent
    / "final_results_chart_reformatted_1_capital_investment_blue"
)
DEFAULT_AGGREGATE_OUTPUT_DIR = (
    Path(__file__).resolve().parent
    / "final_results_chart_aggregate_capital_investment_blue"
)
CAPITAL_INVESTMENT_BLUE_GROUPS = (
    ChartGroup(
        name="Blue Corridor — Capital Investment Blue",
        filename="blue_corridor_combo_capital_investment_blue.png",
        dark_color="#174A7E",
        light_color="#78AEDD",
        corridor="Blue",
    ),
    ChartGroup(
        name="Orange Corridor — Capital Investment Blue",
        filename="orange_corridor_combo_capital_investment_blue.png",
        dark_color="#B84A00",
        light_color="#FDB77E",
        corridor="Orange",
    ),
    ChartGroup(
        name="Green Corridor — Capital Investment Blue",
        filename="green_corridor_combo_capital_investment_blue.png",
        dark_color="#176D3A",
        light_color="#8DCEA0",
        corridor="Green",
    ),
    ChartGroup(
        name="Hub Center (Stop 1503) — Capital Investment Blue",
        filename="hub_center_1503_combo_capital_investment_blue.png",
        dark_color="#1C1C1C",
        light_color="#A6A6A6",
        origin="1503",
    ),
)
CAPITAL_INVESTMENT_BLUE_AGGREGATE_GROUP = ChartGroup(
    name="All Corridors and Hub Center — Capital Investment Blue",
    filename="all_corridors_combined_combo_capital_investment_blue.png",
    dark_color="#252525",
    light_color="#A9A9A9",
)


def write_capital_investment_blue_charts(
    input_path: str | Path = DEFAULT_OUTPUT_PATH,
    individual_output_dir: str | Path = DEFAULT_INDIVIDUAL_OUTPUT_DIR,
    aggregate_output_dir: str | Path = DEFAULT_AGGREGATE_OUTPUT_DIR,
) -> list[Path]:
    """Save four individual charts and one all-corridors aggregate chart."""
    rows = load_projection_rows(input_path)
    individual_output_dir = Path(individual_output_dir).resolve()
    aggregate_output_dir = Path(aggregate_output_dir).resolve()
    individual_output_dir.mkdir(parents=True, exist_ok=True)
    aggregate_output_dir.mkdir(parents=True, exist_ok=True)

    output_paths: list[Path] = []
    for group in CAPITAL_INVESTMENT_BLUE_GROUPS:
        figure = create_combo_chart(
            rows,
            group,
            additional_labels_above=True,
        )
        output_path = individual_output_dir / group.filename
        figure.savefig(output_path, dpi=200, bbox_inches="tight")
        output_paths.append(output_path)

    aggregate_figure = create_combo_chart(
        rows,
        CAPITAL_INVESTMENT_BLUE_AGGREGATE_GROUP,
        additional_labels_above=True,
    )
    aggregate_path = (
        aggregate_output_dir
        / CAPITAL_INVESTMENT_BLUE_AGGREGATE_GROUP.filename
    )
    aggregate_figure.savefig(aggregate_path, dpi=200, bbox_inches="tight")
    output_paths.append(aggregate_path)
    return output_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Capital-investment projection CSV (default: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--individual-output-dir",
        type=Path,
        default=DEFAULT_INDIVIDUAL_OUTPUT_DIR,
        help=(
            "Four-chart output directory "
            f"(default: {DEFAULT_INDIVIDUAL_OUTPUT_DIR})"
        ),
    )
    parser.add_argument(
        "--aggregate-output-dir",
        type=Path,
        default=DEFAULT_AGGREGATE_OUTPUT_DIR,
        help=(
            "Aggregate-chart output directory "
            f"(default: {DEFAULT_AGGREGATE_OUTPUT_DIR})"
        ),
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save charts without opening interactive windows",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    output_paths = write_capital_investment_blue_charts(
        input_path=arguments.input,
        individual_output_dir=arguments.individual_output_dir,
        aggregate_output_dir=arguments.aggregate_output_dir,
    )
    for output_path in output_paths:
        print(f"Wrote {output_path}")
    if arguments.no_show:
        plt.close("all")
    else:
        plt.show()


if __name__ == "__main__":
    main()
