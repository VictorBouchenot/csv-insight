# CSV Insight

A small Python command-line tool for checking numeric columns in a CSV file. Get the mean, median, standard deviation, range, and missing-value counts before plotting or modelling a dataset.

Includes short, rule-based descriptions of data quality, spread, mean/median differences, and possible outliers. This is not AI-generated analysis.

No third-party dependencies. Requires Python 3.10 or later.

## Quick start

Download or clone this repository, open a terminal in its folder, then run:

```bash
python3 csv_insight.py examples/study_sessions.csv --columns minutes exercises
```

On Windows, use `py` instead of `python3` if that is your Python launcher.

The included dataset is synthetic, not personal study data. For the `minutes` column, the result is:

```text
count: 4
missing: 1
invalid: 0
mean: 52.5
median: 52.5
stddev: 16.7705
min: 30
max: 75
```

## Paste numbers or grades directly

No CSV needed for a quick calculation:

```bash
python3 csv_insight.py --values "5/10 12/20 8/10 18/20 20/20"
python3 csv_insight.py --values "1; 2; 3; 4" --json
python3 csv_insight.py --values "1/2 3/4" --scale 100
```

Use spaces, newlines, or semicolons between entries. Quote the whole input.
Fractions such as `5/10` are grades: they are converted to a common scale
(default 20), with **equal weight per entry**. Bare numbers are treated as
already on that scale. Thus `10 5/10` means two values of 10 on the default
scale, not a weighted score of 15/30. Fraction scores must be between zero
and their positive total. Invalid tokens stop the calculation with an error.
Use decimal points, not decimal commas. Spaces inside a fraction are not supported.

The first command normalizes to `10, 12, 16, 18, 20`, with mean 15.2 and
median 16. The output states the scale assumption explicitly.

## What the interpretation means

Every column includes an `interpretation` list in JSON and a short text section:

- Missing and invalid cells: counts of excluded entries.
- Spread: standard deviation and range in the original units, without an arbitrary "good" or "bad" rating.
- Mean vs median: a gap larger than 0.2 standard deviations is described as a possible asymmetry or extreme-value effect. A tiny-gap tolerance avoids floating-point noise. This threshold is a chosen descriptive rule, not a significance test. A small gap does not prove symmetry.
- Potential outliers: the 1.5 × IQR rule, with Python's inclusive quartiles, for at least four numeric values. It counts values strictly outside Q1 - 1.5 × IQR and Q3 + 1.5 × IQR. A flag does not mean a value is wrong. Fewer than four values, or nonfinite computed bounds, produce `null`, not a claim of no outliers.
- Small datasets (fewer than ten numeric values) get a caution.

These comments do not identify causes, prove a distribution, rank pupils,
or make predictions. Inspect the original data before drawing conclusions.
They are deterministic rules, not a trained model or an external AI service.

## Options

```bash
# All columns, including counts of text cells that are not numeric
python3 csv_insight.py examples/study_sessions.csv

# Machine-readable output (full numeric precision)
python3 csv_insight.py examples/study_sessions.csv --columns minutes --json

# Sample standard deviation, dividing by n - 1
python3 csv_insight.py examples/study_sessions.csv --columns minutes --sample

# Semicolon-separated CSV
python3 csv_insight.py your_data.csv --delimiter ';'
```

Column names containing spaces must be quoted, for example `--columns "study minutes"`.

## A data-quality example

```bash
python3 csv_insight.py examples/messy_data.csv --columns price --json
```

This reports 2 numeric prices, 1 missing price, and 1 invalid price. The mean
is 14.2, calculated only from 3.50 and 24.90. It does not pretend the missing
or invalid entries are zero. Both included files are synthetic examples.

## Use it from Python

```python
from csv_insight import summarize

report = summarize("examples/study_sessions.csv", columns=["minutes"])
print(report["columns"]["minutes"]["mean"])  # 52.5
```

The JSON and Python results share the same structure: `rows`, `stddev_mode`,
and a `columns` mapping. Each column has `count`, `missing`, `invalid`, `mean`,
`median`, `stddev`, `min`, and `max`, plus `outliers_iqr` and `interpretation`. Pasted input also adds
an `input_note` stating the normalization assumption. For every column,
`count + missing + invalid == rows`.

## How the statistics work

For finite numeric values x₁, ..., xₙ:

- Mean: the sum divided by n.
- Median: the middle value after sorting, or the average of the two middle values.
- Population standard deviation (default): the square root of the mean squared distance from the mean.
- Sample standard deviation (`--sample`): uses n - 1 instead of n. It is undefined with fewer than two numeric values.

## Input rules and limits

- The file must have a nonempty header with unique column names. Outer spaces in headers are trimmed.
- UTF-8 and UTF-8 with a byte-order mark are supported.
- Blank lines are skipped. Every other row must have the same number of fields as the header.
- Empty or whitespace-only cells count as missing. Missing values are never replaced by zero.
- Text, NaN, and infinity count as invalid, not as numeric values. Invalid cells are excluded from statistics and counted visibly.
- Numeric parsing uses Python's `float`: decimal points, negative numbers, and scientific notation work. Decimal commas and thousands separators are not parsed as numbers.
- Columns with no numeric values show `n/a` (JSON `null`). One value has population standard deviation 0.
- Text output rounds to six significant digits. JSON preserves the stored float precision.
- Values are held in memory to compute the median. This is for modest CSV files, not large-scale data processing.
- Floating-point arithmetic is approximate. Extreme magnitudes may exceed its range and produce a clear error.
- Input/file errors return exit status 1; command-line usage errors return 2; success returns 0. No input files are modified and no data is sent over the network.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests cover known statistics, sample vs population spread, missing and invalid values, malformed rows, column selection, delimiters, UTF-8 BOM, JSON output, CLI errors, pasted-grade normalization, input conflicts,
and interpretation rules.

## Project structure

```text
csv_insight.py                 CLI and statistics logic
examples/study_sessions.csv   Clean synthetic example
examples/messy_data.csv       Missing/invalid-cell example
tests/test_csv_insight.py      Standard-library unit tests
```

## Troubleshooting

| Message | What to check |
| --- | --- |
| `unknown columns` | Names are case-sensitive. Check the first line of the file. |
| `expected ... fields` | Check for missing separators or unquoted commas in cells. |
| `column names must be nonempty and unique` | Give every column a different, nonempty header. |
| `n/a` in a report | There are no numeric values, or fewer than two for sample spread. |
| File access error | Check the path and permissions. Quote paths that contain spaces. |

## Learning focus

This project connects descriptive statistics with practical data validation. It is a useful first step before a machine-learning workflow, but does not train a model or make predictions.
