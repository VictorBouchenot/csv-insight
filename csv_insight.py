"""Inspect numeric CSV columns using only the Python standard library."""

import argparse
import csv
from dataclasses import dataclass, field
import json
import math
import re
from pathlib import Path
import statistics
import sys
from typing import Iterable, TypedDict


class CSVError(ValueError):
    """An input file cannot be interpreted safely."""


class ColumnSummary(TypedDict):
    count: int
    missing: int
    invalid: int
    mean: float | None
    median: float | None
    stddev: float | None
    min: float | None
    max: float | None
    outliers_iqr: int | None
    interpretation: list[str]


class _RequiredReport(TypedDict):
    rows: int
    stddev_mode: str
    columns: dict[str, ColumnSummary]


class Report(_RequiredReport, total=False):
    input_note: str


@dataclass
class _Column:
    """Keep parsing counts separate from the numeric sample."""

    values: list[float] = field(default_factory=list)
    missing: int = 0
    invalid: int = 0

    def add(self, cell: str) -> None:
        cell = cell.strip()
        if not cell:
            self.missing += 1
            return
        try:
            value = float(cell)
        except ValueError:
            self.invalid += 1
            return
        if math.isfinite(value):
            self.values.append(value)
        else:
            self.invalid += 1

    def summary(self, name: str, sample: bool) -> ColumnSummary:
        count = len(self.values)
        minimum_count = 2 if sample else 1
        deviation = statistics.stdev if sample else statistics.pstdev
        try:
            metrics = {
                "mean": statistics.mean(self.values) if count else None,
                "median": statistics.median(self.values) if count else None,
                "stddev": deviation(self.values) if count >= minimum_count else None,
                "min": min(self.values) if count else None,
                "max": max(self.values) if count else None,
            }
        except (OverflowError, ValueError) as exc:
            raise CSVError(f"column {name!r}: values are too large to summarize") from exc
        if any(value is not None and not math.isfinite(value) for value in metrics.values()):
            raise CSVError(f"column {name!r}: statistics exceed the finite float range")
        outliers = None
        if count >= 4:
            # Inclusive quartiles keep the end observations within the sample.
            q1, _, q3 = statistics.quantiles(self.values, n=4, method="inclusive")
            iqr = q3 - q1
            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            if all(math.isfinite(x) for x in (iqr, lower, upper)):
                outliers = sum(value < lower or value > upper for value in self.values)
        summary = {
            "count": count,
            "missing": self.missing,
            "invalid": self.invalid,
            **metrics,
            "outliers_iqr": outliers,
        }
        summary["interpretation"] = interpret(summary)
        return summary


def interpret(stats: dict) -> list[str]:
    """Describe visible patterns, not causes or statistical significance."""
    notes = []
    missing, invalid, count = stats["missing"], stats["invalid"], stats["count"]
    if missing or invalid:
        notes.append(
            f"Excluded {missing} missing and {invalid} invalid cells; "
            f"statistics use {count} numeric values."
        )
    if count == 0:
        return notes + ["No numeric values to interpret."]
    if count == 1:
        return notes + ["Only one numeric value; it cannot describe a distribution."]
    if stats["min"] == stats["max"]:
        notes.append("All numeric values are identical; no observed spread.")
    else:
        deviation = stats["stddev"]
        if deviation is not None:
            notes.append(
                f"Standard deviation is {deviation:.6g} in the data's units; "
                f"values range from {stats['min']:.6g} to {stats['max']:.6g}."
            )
        mean, median = stats["mean"], stats["median"]
        gap = mean - median
        # A descriptive threshold, not a hypothesis test.
        reference = max(abs(mean), abs(median), 1e-300)
        if deviation and abs(gap) > max(0.2 * deviation, 1e-12 * reference):
            direction = "above" if gap > 0 else "below"
            tail = "high" if gap > 0 else "low"
            notes.append(
                f"Mean is {direction} the median by {abs(gap):.6g}; "
                f"this may reflect an asymmetric distribution or {tail} extreme values. "
                "It does not prove either."
            )
        else:
            notes.append("Mean and median are close by this rule; this does not prove symmetry.")
    outliers = stats["outliers_iqr"]
    if outliers is None:
        notes.append("IQR outlier screening unavailable (needs at least 4 values and finite bounds).")
    else:
        notes.append(
            f"IQR rule flags {outliers} potential outlier(s). "
            "A flag is not evidence of an error; inspect the original values."
        )
    if count < 10:
        notes.append("Small dataset: patterns may change noticeably with more observations.")
    return notes


def summarize_values(text: str, scale: float = 20, sample: bool = False) -> Report:
    """Parse pasted numbers or score/total grades, separated by whitespace or ;.

    Fractions are grades, not arbitrary expressions. Bare numbers are already
    on the target scale. Invalid tokens fail rather than silently disappearing.
    """
    if not math.isfinite(scale) or scale <= 0:
        raise CSVError("scale must be a positive finite number")
    tokens = re.split(r"[;\s]+", text.strip()) if text.strip() else []
    if not tokens:
        raise CSVError("paste at least one value")
    column = _Column()
    for token in tokens:
        try:
            if "/" in token:
                numerator, denominator = token.split("/")
                score, total = float(numerator), float(denominator)
                if not all(math.isfinite(x) for x in (score, total)):
                    raise ValueError
                if total <= 0 or not 0 <= score <= total:
                    raise ValueError
                value = (score / total) * scale
            else:
                value = float(token)
            if not math.isfinite(value):
                raise ValueError
        except (ValueError, OverflowError) as exc:
            raise CSVError(f"invalid pasted value {token!r}") from exc
        column.values.append(value)
    return {
        "rows": len(tokens),
        "stddev_mode": "sample" if sample else "population",
        "columns": {"values": column.summary("values", sample)},
        "input_note": (
            f"Fractions normalized to {scale:g}; bare numbers treated as already "
            "on that scale. Each entry has equal weight."
        ),
    }


def summarize(
    path: str | Path,
    columns: Iterable[str] | None = None,
    delimiter: str = ",",
    sample: bool = False,
) -> Report:
    """Summarize a header-based UTF-8 CSV without changing it.

    Missing and invalid cells are counted, never replaced by zero. Duplicate
    selected column names are deduplicated while preserving their order.
    Raises CSVError for malformed input and OSError for file access failures.
    """
    if len(delimiter) != 1 or delimiter in "\r\n\0":
        raise CSVError("delimiter must be one character other than a newline or NUL")
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        reader = csv.reader(source, delimiter=delimiter, strict=True)
        try:
            header = next(reader, None)
            if not header:
                raise CSVError("CSV must contain a header")
            header = [name.strip() for name in header]
            if any(not name for name in header) or len(set(header)) != len(header):
                raise CSVError("column names must be nonempty and unique")
            selected = header if columns is None else list(dict.fromkeys(columns))
            if not selected:
                raise CSVError("select at least one column")
            unknown = [name for name in selected if name not in header]
            if unknown:
                raise CSVError(f"unknown columns: {', '.join(unknown)}")
            data = {name: _Column() for name in selected}
            indexes = {name: header.index(name) for name in selected}
            row_count = 0
            for row in reader:
                if not row:
                    continue
                if len(row) != len(header):
                    raise CSVError(
                        f"line {reader.line_num}: expected {len(header)} fields, "
                        f"got {len(row)}"
                    )
                row_count += 1
                for name, index in indexes.items():
                    data[name].add(row[index])
        except csv.Error as exc:
            raise CSVError(f"invalid CSV near line {reader.line_num}: {exc}") from exc
    return {
        "rows": row_count,
        "stddev_mode": "sample" if sample else "population",
        "columns": {name: column.summary(name, sample) for name, column in data.items()},
    }


def format_report(report: Report) -> str:
    """Render a readable report; JSON output retains greater precision."""
    lines = [f"Rows: {report['rows']} | Standard deviation: {report['stddev_mode']}"]
    if "input_note" in report:
        lines.append(report["input_note"])
    for name, stats in report["columns"].items():
        lines.extend(["", name])
        for key, value in stats.items():
            if key == "interpretation":
                continue
            formatted = "n/a" if value is None else format(value, ".6g")
            lines.append(f"  {key}: {formatted}")
        lines.append("  Interpretation (descriptive rules, not AI):")
        lines.extend(f"    - {note}" for note in stats["interpretation"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, nargs="?")
    parser.add_argument("--values", help="quoted numbers or grades, separated by spaces/newlines/semicolons")
    parser.add_argument("--scale", type=float, help="normalize pasted fractions to this scale (default: 20)")
    parser.add_argument("--columns", nargs="+", help="column names (default: all)")
    parser.add_argument("--delimiter", default=",", help="one-character separator")
    parser.add_argument(
        "--sample", action="store_true",
        help="sample instead of population standard deviation",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")
    args = parser.parse_args(argv)
    if (args.file is None) == (args.values is None):
        parser.error("provide exactly one CSV file or --values")
    if args.values is not None and (args.columns is not None or args.delimiter != ","):
        parser.error("--columns and --delimiter apply only to CSV files")
    if args.file is not None and args.scale is not None:
        parser.error("--scale applies only to --values")
    try:
        report = (
            summarize_values(args.values, 20 if args.scale is None else args.scale, args.sample)
            if args.values is not None
            else summarize(args.file, args.columns, args.delimiter, args.sample)
        )
    except (CSVError, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, allow_nan=False) if args.json else format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
