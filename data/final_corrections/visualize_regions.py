"""Render the corrected 2024 one-tier corridor regions.

Run from any directory with::

    python data/final_corrections/visualize_regions.py

By default the plot is saved beside this script.  Pass ``--show`` to display
the interactive Matplotlib window as well.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from shapely.geometry import shape
from shapely.plotting import plot_polygon


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_PATH = (
    SCRIPT_DIR / "full_routes_for_tomtom_2024_0_400m.geojson"
)
DEFAULT_OUTPUT_PATH = (
    SCRIPT_DIR / "full_routes_for_tomtom_2024_0_400m.png"
)

CORRIDOR_COLORS = {
    "Orange": "#f28e2b",
    "Blue": "#4e79a7",
    "Green": "#59a14f",
}
EXISTING_REGION_COLOR = "#a6a6a6"


def load_geojson(path: str | Path) -> dict:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"GeoJSON does not exist: {path}")

    with path.open(encoding="utf-8") as input_file:
        geojson = json.load(input_file)

    if geojson.get("type") != "FeatureCollection":
        raise ValueError(f"Expected a GeoJSON FeatureCollection: {path}")
    if not geojson.get("features"):
        raise ValueError(f"GeoJSON has no features: {path}")
    return geojson


def visualize_regions(
    input_path: str | Path = DEFAULT_INPUT_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    show: bool = False,
):
    """Render corridor stop regions and corridor-wide supplemental areas."""
    geojson = load_geojson(input_path)
    figure, axis = plt.subplots(figsize=(14, 6.4))
    found_existing = False
    found_corridors = set()

    for feature_index, feature in enumerate(geojson["features"]):
        geometry_data = feature.get("geometry")
        if geometry_data is None:
            continue

        geometry = shape(geometry_data)
        if geometry.is_empty:
            continue
        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(
                f"Feature {feature_index} is not polygonal: "
                f"{geometry.geom_type}"
            )
        if not geometry.is_valid:
            raise ValueError(f"Feature {feature_index} has invalid geometry")

        properties = feature.get("properties", {})
        if properties.get("region_type") == "non_corridor_route_area":
            corridor = properties.get("corridor")
            if corridor not in CORRIDOR_COLORS:
                raise ValueError(
                    f"Feature {feature_index} has unknown corridor: {corridor!r}"
                )
            found_corridors.add(corridor)
            face_color = CORRIDOR_COLORS[corridor]
            edge_color = "#202020"
            line_width = 0.35
            alpha = 0.8
        else:
            found_existing = True
            face_color = EXISTING_REGION_COLOR
            edge_color = "#666666"
            line_width = 0.15
            alpha = 0.72

        plot_polygon(
            geometry,
            ax=axis,
            add_points=False,
            facecolor=face_color,
            edgecolor=edge_color,
            linewidth=line_width,
            alpha=alpha,
        )

    legend_handles = []
    if found_existing:
        legend_handles.append(
            Patch(
                facecolor=EXISTING_REGION_COLOR,
                edgecolor="#666666",
                label="Existing 0-400m",
            )
        )
    legend_handles.extend(
        Patch(
            facecolor=CORRIDOR_COLORS[corridor],
            edgecolor="#202020",
            label=f"{corridor} 0-400m",
        )
        for corridor in CORRIDOR_COLORS
        if corridor in found_corridors
    )

    axis.autoscale_view()
    axis.set_aspect(1.35)
    axis.set_xlabel("Longitude")
    axis.set_ylabel("Latitude")
    axis.set_title("2024 Full-Route Corridor Regions for TomTom (0-400m)")
    axis.grid(True, linestyle="--", alpha=0.25)
    if legend_handles:
        axis.legend(handles=legend_handles, loc="upper left", ncols=2)

    figure.tight_layout()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=160, bbox_inches="tight")
    if show:
        plt.show()
    else:
        plt.close(figure)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Visualize the corrected one-tier 2024 corridor GeoJSON."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"Input GeoJSON (default: {DEFAULT_INPUT_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Output image (default: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Also display the interactive Matplotlib window.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = visualize_regions(
        input_path=args.input,
        output_path=args.output,
        show=args.show,
    )
    print(f"Wrote corridor-region visualization to {output_path}")


if __name__ == "__main__":
    main()
