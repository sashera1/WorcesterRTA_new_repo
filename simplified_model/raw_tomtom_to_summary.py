"""Summarize TomTom OD trips by origin and destination distance tier.

For every time range in ``simplified_report.csv``, this module writes one CSV
containing each regular corridor region's total trips to all 0-400 m regions
and all 400-800 m regions.  The corridor-wide Orange, Blue, and Green regions
are included as destinations, but are not emitted as origins.  ``External`` is
excluded from both destination totals and output origins.

A second set of files combines each origin's 0-400 m and 400-800 m rows.  Its
three trip columns represent the inner/inner combination, the sum of the two
mismatched combinations, and the outer/outer combination.

Run from the repository root with::

    python simplified_model/raw_tomtom_to_summary.py
"""

from __future__ import annotations

import argparse
import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


DEFAULT_REPORT_PATH = Path(__file__).resolve().parent / "simplified_report.csv"
ORIGIN_COLUMN = "Origin"
DESTINATION_COLUMN = "Destination"
OUTPUT_FIELDNAMES = (
    ORIGIN_COLUMN,
    "Trips to 0-400m regions",
    "Trips to 400-800m regions",
)
COMBINED_OUTPUT_FIELDNAMES = (
    ORIGIN_COLUMN,
    "0-800m Trips",
    "0-1600m Trips",
    "800-1600m Trips",
)
OUTSIDE_CORRIDOR_ORIGIN_PREFIXES = ("Orange_", "Blue_", "Green_")
DESTINATION_SUFFIX_TO_INDEX = {
    "_0-400m": 0,
    "_400-800m": 1,
}
SUMMED_REPORT_FILENAME_PATTERN = re.compile(
    r"^summed_by_origin_(?P<time_range>.+)\.csv$",
    re.IGNORECASE,
)
TRIP_COLUMN_PATTERN = re.compile(
    r"Time range:\s*"
    r"(?P<start>\d{1,2}:\d{2})\s*-\s*"
    r"(?P<end>\d{1,2}:\d{2})\s+Trips\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TripColumn:
    """One report column containing trip counts for a single time range."""

    header: str
    time_range: str
    filename_slug: str


def _normalize_clock(value: str, header: str) -> str:
    """Validate a report-header clock and return it as zero-padded HH:MM."""
    hour_text, minute_text = value.split(":", maxsplit=1)
    hour = int(hour_text)
    minute = int(minute_text)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"Invalid clock time {value!r} in column {header!r}")
    return f"{hour:02d}:{minute:02d}"


def _find_trip_columns(fieldnames: list[str]) -> list[TripColumn]:
    """Find and validate the time-range ``Trips`` columns in report order."""
    trip_headers = [
        header
        for header in fieldnames
        if header.strip().casefold().endswith(" trips")
    ]
    if not trip_headers:
        raise ValueError("The report contains no time-range Trips columns")

    trip_columns: list[TripColumn] = []
    seen_time_ranges: set[str] = set()
    for header in trip_headers:
        match = TRIP_COLUMN_PATTERN.search(header)
        if match is None:
            raise ValueError(
                f"Could not read a time range from Trips column {header!r}"
            )
        start = _normalize_clock(match.group("start"), header)
        end = _normalize_clock(match.group("end"), header)
        time_range = f"{start} - {end}"
        if time_range in seen_time_ranges:
            raise ValueError(f"Duplicate Trips time range: {time_range}")
        seen_time_ranges.add(time_range)
        filename_slug = (
            f"{start.replace(':', '-')}_to_{end.replace(':', '-')}"
        )
        trip_columns.append(
            TripColumn(
                header=header,
                time_range=time_range,
                filename_slug=filename_slug,
            )
        )
    return trip_columns


def _is_excluded_origin(region: str) -> bool:
    """Return whether a region must not appear as an output origin."""
    normalized_region = region.casefold()
    return normalized_region == "external" or normalized_region.startswith(
        tuple(prefix.casefold() for prefix in OUTSIDE_CORRIDOR_ORIGIN_PREFIXES)
    )


def _destination_tier_index(region: str, row_number: int) -> int | None:
    """Map a destination to its output tier; ``External`` maps to ``None``."""
    normalized_region = region.casefold()
    if normalized_region == "external":
        return None
    for suffix, tier_index in DESTINATION_SUFFIX_TO_INDEX.items():
        if normalized_region.endswith(suffix.casefold()):
            return tier_index
    raise ValueError(
        f"Row {row_number} has an unrecognized destination region {region!r}; "
        "expected External or a region ending in _0-400m or _400-800m"
    )


def _parse_trip_count(value: str | None, row_number: int, column: str) -> Decimal:
    """Parse one finite, nonnegative trip count with row-aware errors."""
    if value is None or not value.strip():
        raise ValueError(
            f"Row {row_number}, column {column!r} has a blank trip count"
        )
    try:
        trip_count = Decimal(value.strip())
    except InvalidOperation as error:
        raise ValueError(
            f"Row {row_number}, column {column!r} has invalid trip count "
            f"{value!r}"
        ) from error
    if not trip_count.is_finite() or trip_count < 0:
        raise ValueError(
            f"Row {row_number}, column {column!r} has invalid trip count "
            f"{value!r}"
        )
    return trip_count


def _format_trip_total(value: Decimal) -> str:
    """Write integral totals without a decimal point and retain exact fractions."""
    if value == value.to_integral_value():
        return str(int(value))
    return format(value, "f").rstrip("0").rstrip(".")


def _split_origin_tier(origin: str, row_number: int) -> tuple[str, int]:
    """Split ``<origin>_<distance tier>`` into its base and tier index."""
    normalized_origin = origin.casefold()
    for suffix, tier_index in DESTINATION_SUFFIX_TO_INDEX.items():
        if normalized_origin.endswith(suffix.casefold()):
            origin_base = origin[: -len(suffix)].strip()
            if not origin_base:
                break
            return origin_base, tier_index
    raise ValueError(
        f"Row {row_number} has an unrecognized origin region {origin!r}; "
        "expected a region ending in _0-400m or _400-800m"
    )


def write_summed_by_origin_reports(
    report_path: str | Path = DEFAULT_REPORT_PATH,
    output_dir: str | Path | None = None,
) -> list[Path]:
    """Read a simplified TomTom report and write one origin summary per period.

    Output files are named, for example,
    ``summed_by_origin_04-00_to_06-00.csv``.  Origin order follows the first
    appearance of each eligible origin in the input report.

    Returns:
        Paths to the output files, in the report's time-period order.
    """
    report_path = Path(report_path).resolve()
    if not report_path.is_file():
        raise FileNotFoundError(f"Simplified report does not exist: {report_path}")
    resolved_output_dir = (
        report_path.parent if output_dir is None else Path(output_dir).resolve()
    )

    with report_path.open(encoding="utf-8-sig", newline="") as report_file:
        reader = csv.DictReader(report_file)
        if reader.fieldnames is None:
            raise ValueError(f"Simplified report has no header: {report_path}")
        missing_columns = {
            ORIGIN_COLUMN,
            DESTINATION_COLUMN,
        } - set(reader.fieldnames)
        if missing_columns:
            raise ValueError(
                "Simplified report is missing required columns: "
                f"{sorted(missing_columns)}"
            )
        trip_columns = _find_trip_columns(reader.fieldnames)

        origin_order: list[str] = []
        totals_by_period: dict[str, dict[str, list[Decimal]]] = {
            trip_column.header: {} for trip_column in trip_columns
        }

        for row_number, row in enumerate(reader, start=2):
            origin = (row.get(ORIGIN_COLUMN) or "").strip()
            destination = (row.get(DESTINATION_COLUMN) or "").strip()
            if not origin:
                raise ValueError(f"Row {row_number} has a blank origin")
            if not destination:
                raise ValueError(f"Row {row_number} has a blank destination")
            if _is_excluded_origin(origin):
                continue

            first_period_totals = totals_by_period[trip_columns[0].header]
            if origin not in first_period_totals:
                origin_order.append(origin)
                for period_totals in totals_by_period.values():
                    period_totals[origin] = [Decimal(0), Decimal(0)]

            tier_index = _destination_tier_index(destination, row_number)
            if tier_index is None:
                continue
            for trip_column in trip_columns:
                trip_count = _parse_trip_count(
                    row.get(trip_column.header), row_number, trip_column.header
                )
                totals_by_period[trip_column.header][origin][tier_index] += trip_count

    if not origin_order:
        raise ValueError("The report contains no eligible origin regions")

    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[Path] = []
    for trip_column in trip_columns:
        output_path = resolved_output_dir / (
            f"summed_by_origin_{trip_column.filename_slug}.csv"
        )
        with output_path.open("w", encoding="utf-8", newline="") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=OUTPUT_FIELDNAMES)
            writer.writeheader()
            for origin in origin_order:
                near_total, far_total = totals_by_period[trip_column.header][origin]
                writer.writerow(
                    {
                        ORIGIN_COLUMN: origin,
                        OUTPUT_FIELDNAMES[1]: _format_trip_total(near_total),
                        OUTPUT_FIELDNAMES[2]: _format_trip_total(far_total),
                    }
                )
        output_paths.append(output_path)
    return output_paths


def _write_combined_origin_pair_report(
    summary_path: Path,
    output_path: Path,
) -> None:
    """Combine the two origin-tier rows in one summed-by-origin report."""
    with summary_path.open(encoding="utf-8-sig", newline="") as summary_file:
        reader = csv.DictReader(summary_file)
        if reader.fieldnames is None:
            raise ValueError(f"Summed report has no header: {summary_path}")
        missing_columns = set(OUTPUT_FIELDNAMES) - set(reader.fieldnames)
        if missing_columns:
            raise ValueError(
                f"Summed report {summary_path} is missing required columns: "
                f"{sorted(missing_columns)}"
            )

        origin_order: list[str] = []
        rows_by_origin: dict[
            str,
            list[tuple[Decimal, Decimal] | None],
        ] = {}
        for row_number, row in enumerate(reader, start=2):
            origin = (row.get(ORIGIN_COLUMN) or "").strip()
            if not origin:
                raise ValueError(
                    f"Row {row_number} in {summary_path} has a blank origin"
                )
            origin_base, origin_tier_index = _split_origin_tier(
                origin, row_number
            )
            if origin_base not in rows_by_origin:
                origin_order.append(origin_base)
                rows_by_origin[origin_base] = [None, None]
            if rows_by_origin[origin_base][origin_tier_index] is not None:
                raise ValueError(
                    f"Summed report {summary_path} has a duplicate "
                    f"{origin!r} origin row"
                )
            rows_by_origin[origin_base][origin_tier_index] = (
                _parse_trip_count(
                    row.get(OUTPUT_FIELDNAMES[1]),
                    row_number,
                    OUTPUT_FIELDNAMES[1],
                ),
                _parse_trip_count(
                    row.get(OUTPUT_FIELDNAMES[2]),
                    row_number,
                    OUTPUT_FIELDNAMES[2],
                ),
            )

    if not origin_order:
        raise ValueError(f"Summed report contains no origin rows: {summary_path}")
    incomplete_origins = [
        origin_base
        for origin_base in origin_order
        if any(row is None for row in rows_by_origin[origin_base])
    ]
    if incomplete_origins:
        raise ValueError(
            f"Summed report {summary_path} is missing an origin distance tier "
            f"for: {', '.join(incomplete_origins)}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=COMBINED_OUTPUT_FIELDNAMES,
        )
        writer.writeheader()
        for origin_base in origin_order:
            inner_row, outer_row = rows_by_origin[origin_base]
            # The completeness check above proves both rows are present.
            assert inner_row is not None and outer_row is not None
            inner_to_inner, inner_to_outer = inner_row
            outer_to_inner, outer_to_outer = outer_row
            writer.writerow(
                {
                    ORIGIN_COLUMN: origin_base,
                    COMBINED_OUTPUT_FIELDNAMES[1]: _format_trip_total(
                        inner_to_inner
                    ),
                    COMBINED_OUTPUT_FIELDNAMES[2]: _format_trip_total(
                        inner_to_outer + outer_to_inner
                    ),
                    COMBINED_OUTPUT_FIELDNAMES[3]: _format_trip_total(
                        outer_to_outer
                    ),
                }
            )


def write_combined_origin_pair_reports(
    summary_paths: Iterable[str | Path] | None = None,
    output_dir: str | Path | None = None,
) -> list[Path]:
    """Combine origin distance-tier pairs in each summed-by-origin CSV.

    For an origin with inner row ``(a, b)`` and outer row ``(c, d)``, the new
    row contains ``0-800m = a``, ``0-1600m = b + c``, and
    ``800-1600m = d``.  If ``summary_paths`` is omitted, every
    ``summed_by_origin_*.csv`` beside this script is processed.

    Returns:
        Paths to the combined output files, in input order.
    """
    if summary_paths is None:
        resolved_summary_paths = sorted(
            DEFAULT_REPORT_PATH.parent.glob("summed_by_origin_*.csv")
        )
    else:
        resolved_summary_paths = [
            Path(summary_path).resolve() for summary_path in summary_paths
        ]
    if not resolved_summary_paths:
        raise FileNotFoundError("No summed_by_origin_*.csv reports were found")

    resolved_output_dir = (
        None if output_dir is None else Path(output_dir).resolve()
    )
    output_paths: list[Path] = []
    seen_output_paths: set[Path] = set()
    for summary_path in resolved_summary_paths:
        if not summary_path.is_file():
            raise FileNotFoundError(
                f"Summed-by-origin report does not exist: {summary_path}"
            )
        filename_match = SUMMED_REPORT_FILENAME_PATTERN.fullmatch(
            summary_path.name
        )
        if filename_match is None:
            raise ValueError(
                "Summed report filename must match "
                f"summed_by_origin_[timerange].csv: {summary_path.name}"
            )
        destination_dir = resolved_output_dir or summary_path.parent
        output_path = destination_dir / (
            "combined_by_origin_"
            f"{filename_match.group('time_range')}.csv"
        )
        if output_path in seen_output_paths:
            raise ValueError(f"Multiple inputs would write {output_path}")
        seen_output_paths.add(output_path)
        _write_combined_origin_pair_report(summary_path, output_path)
        output_paths.append(output_path)
    return output_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=f"Simplified TomTom report (default: {DEFAULT_REPORT_PATH})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory (default: the input report's directory)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    summed_paths = write_summed_by_origin_reports(
        report_path=arguments.input,
        output_dir=arguments.output_dir,
    )
    combined_paths = write_combined_origin_pair_reports(
        summary_paths=summed_paths,
        output_dir=arguments.output_dir,
    )
    written_paths = [*summed_paths, *combined_paths]
    print(
        f"Wrote {len(summed_paths)} summed files and "
        f"{len(combined_paths)} combined files:"
    )
    for written_path in written_paths:
        print(f"  {written_path}")
