"""Visualize the combined projection for all corridors and Hub Center.

The source projection CSV is opened read-only.  All Orange, Blue, Green, and
Hub Center rows are aggregated within each time period, then shown in one
combination chart.  Dark and light stacked bars represent current and
additional projected ridership; matching lines represent current and
projected nearby-trip bus shares.

Run from the repository root with::

    python simplified_model/visualize_final_results_aggreggate.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt

if __package__:
    from .visualize_final_results import (
        DEFAULT_INPUT_PATH,
        ChartGroup,
        create_combo_chart,
        load_projection_rows,
    )
else:
    from visualize_final_results import (
        DEFAULT_INPUT_PATH,
        ChartGroup,
        create_combo_chart,
        load_projection_rows,
    )


DEFAULT_OUTPUT_PATH = (
    Path(__file__).resolve().parent
    / "final_results_chart_aggregate"
    / "all_corridors_combined_combo.png"
)
AGGREGATE_GROUP = ChartGroup(
    name="All Corridors and Hub Center",
    filename=DEFAULT_OUTPUT_PATH.name,
    dark_color="#252525",
    light_color="#A9A9A9",
)


def write_aggregate_chart(
    input_path: str | Path = DEFAULT_INPUT_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
) -> Path:
    """Read every projection row and save the combined neutral-color chart."""
    rows = load_projection_rows(input_path)
    figure = create_combo_chart(rows, AGGREGATE_GROUP)
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=200, bbox_inches="tight")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"Projection CSV (default: {DEFAULT_INPUT_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Chart output path (default: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save the chart without opening an interactive window",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    output_path = write_aggregate_chart(arguments.input, arguments.output)
    print(f"Wrote {output_path}")
    if arguments.no_show:
        plt.close("all")
    else:
        plt.show()


if __name__ == "__main__":
    main()
