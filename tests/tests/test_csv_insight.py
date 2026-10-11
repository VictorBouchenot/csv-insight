import contextlib
import io
import json
import math
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

from csv_insight import CSVError, format_report, main, summarize, summarize_values


class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "data.csv"

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")
        return self.path

    def test_known_statistics(self):
        report = summarize(self.write("x\n1\n2\n3\n4\n"))
        stats = report["columns"]["x"]
        self.assertEqual(report["rows"], 4)
        self.assertEqual(stats["mean"], 2.5)
        self.assertEqual(stats["median"], 2.5)
        self.assertAlmostEqual(stats["stddev"], math.sqrt(1.25))
        self.assertEqual((stats["min"], stats["max"]), (1, 4))

    def test_sample_standard_deviation(self):
        stats = summarize(self.write("x\n1\n2\n3\n"), sample=True)["columns"]["x"]
        self.assertEqual(stats["stddev"], 1)

    def test_missing_invalid_and_nonfinite(self):
        stats = summarize(self.write("x,label\n,one\nNaN,two\ninf,three\nbad,four\n0,five\n"))["columns"]["x"]
        self.assertEqual((stats["count"], stats["missing"], stats["invalid"]), (1, 1, 3))
        self.assertEqual(stats["mean"], 0)

    def test_no_numeric_values(self):
        stats = summarize(self.write("x\nhello\n"))["columns"]["x"]
        self.assertIsNone(stats["mean"])
        self.assertIsNone(stats["stddev"])

    def test_header_only(self):
        report = summarize(self.write("x,y\n"))
        self.assertEqual(report["rows"], 0)
        self.assertIsNone(report["columns"]["x"]["mean"])

    def test_one_value(self):
        self.write("x\n42\n")
        self.assertEqual(summarize(self.path)["columns"]["x"]["stddev"], 0)
        self.assertIsNone(summarize(self.path, sample=True)["columns"]["x"]["stddev"])

    def test_column_selection(self):
        report = summarize(self.write("x,y\n1,2\n"), ["y"])
        self.assertEqual(list(report["columns"]), ["y"])

    def test_unknown_column(self):
        with self.assertRaises(CSVError):
            summarize(self.write("x\n1\n"), ["y"])

    def test_duplicate_and_empty_headers(self):
        for text in ("x,x\n1,2\n", "x,\n1,2\n"):
            with self.subTest(text=text), self.assertRaises(CSVError):
                summarize(self.write(text))

    def test_empty_file(self):
        with self.assertRaises(CSVError):
            summarize(self.write(""))

    def test_ragged_rows(self):
        for text in ("x,y\n1\n", "x,y\n1,2,3\n"):
            with self.subTest(text=text), self.assertRaises(CSVError):
                summarize(self.write(text))

    def test_semicolon_delimiter(self):
        report = summarize(self.write("x;y\n1;2\n"), delimiter=";")
        self.assertEqual(report["columns"]["y"]["mean"], 2)

    def test_invalid_delimiter(self):
        with self.assertRaises(CSVError):
            summarize(self.write("x\n1\n"), delimiter="::")

    def test_bom_quoted_cell_and_negative_decimal(self):
        report = summarize(self.write('\ufeffx,label\n-1.5,"hello, world"\n2.5,text\n'))
        self.assertEqual(report["columns"]["x"]["mean"], 0.5)

    def test_blank_lines_skipped(self):
        self.assertEqual(summarize(self.write("x\n\n1\n\n"))["rows"], 1)

    def test_malformed_csv(self):
        with self.assertRaises(CSVError):
            summarize(self.write('x\n"unterminated\n'))

    def test_extreme_values_fail_cleanly(self):
        with self.assertRaises(CSVError):
            summarize(self.write("x\n1e308\n-1e308\n"))

    def test_invalid_utf8_cli(self):
        self.path.write_bytes(b"x\n\xff\n")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([str(self.path)]), 1)

    def test_column_order_and_duplicates(self):
        report = summarize(self.write("x,y\n1,2\n"), ["y", "x", "y"])
        self.assertEqual(list(report["columns"]), ["y", "x"])

    def test_empty_selection(self):
        with self.assertRaises(CSVError):
            summarize(self.write("x\n1\n"), [])

    def test_header_whitespace(self):
        report = summarize(self.write(" x , y \n 1 , 2 \n"), ["x"])
        self.assertEqual(report["columns"]["x"]["mean"], 1)

    def test_newline_and_nul_delimiters(self):
        for delimiter in ("\n", "\r", "\0"):
            with self.subTest(delimiter=delimiter), self.assertRaises(CSVError):
                summarize(self.write("x\n1\n"), delimiter=delimiter)

    def test_scientific_notation(self):
        stats = summarize(self.write("x\n1e2\n2e2\n"))["columns"]["x"]
        self.assertEqual(stats["mean"], 150)

    def test_multiline_quoted_text(self):
        report = summarize(self.write('x,label\n1,"first\nsecond"\n'))
        self.assertEqual(report["rows"], 1)
        self.assertEqual(report["columns"]["label"]["invalid"], 1)

    def test_cell_accounting(self):
        report = summarize(self.write("x,y\n1,\n,hello\nNaN,2\n"))
        for stats in report["columns"].values():
            self.assertEqual(stats["count"] + stats["missing"] + stats["invalid"], report["rows"])

    def test_text_format(self):
        report = summarize(self.write("x\nhello\n"))
        output = format_report(report)
        self.assertIn("Rows: 1", output)
        self.assertIn("mean: n/a", output)

    def test_invalid_cli_writes_stderr_only(self):
        self.write("x,y\n1\n")
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.assertEqual(main([str(self.path), "--json"]), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("line 2", errors.getvalue())

    def test_process_exit_status_and_input_unchanged(self):
        self.write("x\n1\n3\n")
        before = self.path.read_bytes()
        script = Path(__file__).resolve().parents[1] / "csv_insight.py"
        result = subprocess.run([sys.executable, str(script), str(self.path), "--json"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["columns"]["x"]["mean"], 2)
        self.assertEqual(self.path.read_bytes(), before)
        self.path.unlink()
        result = subprocess.run([sys.executable, str(script), str(self.path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("error:", result.stderr)

    def test_json_cli(self):
        self.write("x\n1\n3\n")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main([str(self.path), "--json"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["columns"]["x"]["mean"], 2)

    def test_missing_file_returns_nonzero(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([str(self.path)]), 1)


class InterpretationAndPasteTests(unittest.TestCase):
    def stats(self, text, **kwargs):
        return summarize_values(text, **kwargs)["columns"]["values"]

    def test_grade_normalization(self):
        stats = self.stats("5/10 12/20 8/10 18/20 20/20")
        self.assertAlmostEqual(stats["mean"], 15.2)
        self.assertEqual(stats["median"], 16)

    def test_custom_scale(self):
        self.assertEqual(self.stats("1/2 3/4", scale=100)["mean"], 62.5)

    def test_bare_values_and_separators(self):
        stats = self.stats("1;2\n3\t4")
        self.assertEqual(stats["count"], 4)
        self.assertEqual(stats["mean"], 2.5)

    def test_mixed_numbers_and_grades(self):
        self.assertEqual(self.stats("10 5/10")["mean"], 10)

    def test_invalid_grade_tokens(self):
        for text in ("1/0", "-1/20", "21/20", "1/2/3", "nan", "inf", "oops", "1/inf", "1,5"):
            with self.subTest(text=text), self.assertRaises(CSVError):
                self.stats(text)

    def test_empty_values(self):
        with self.assertRaises(CSVError):
            self.stats("  ")

    def test_invalid_scale(self):
        for scale in (0, -1, float("nan"), float("inf")):
            with self.subTest(scale=scale), self.assertRaises(CSVError):
                self.stats("1/2", scale=scale)

    def test_iqr_outlier(self):
        stats = self.stats("1 2 3 4 100")
        self.assertEqual(stats["outliers_iqr"], 1)
        self.assertTrue(any("above the median" in note for note in stats["interpretation"]))

    def test_low_tail(self):
        notes = self.stats("-100 1 2 3 4")["interpretation"]
        self.assertTrue(any("below the median" in note for note in notes))

    def test_constant_values(self):
        stats = self.stats("7 7 7 7")
        self.assertEqual(stats["outliers_iqr"], 0)
        self.assertTrue(any("identical" in note for note in stats["interpretation"]))

    def test_symmetric_values(self):
        notes = self.stats("1 2 3 4 5")["interpretation"]
        self.assertTrue(any("does not prove symmetry" in note for note in notes))

    def test_small_sample_no_outlier_claim(self):
        stats = self.stats("1 2 100")
        self.assertIsNone(stats["outliers_iqr"])
        self.assertTrue(any("Small dataset" in note for note in stats["interpretation"]))

    def test_paste_cli_json(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--values", "5/10 10/20", "--json"]), 0)
        report = json.loads(output.getvalue())
        self.assertIn("equal weight", report["input_note"])
        self.assertIsInstance(report["columns"]["values"]["interpretation"], list)

    def test_conflicting_cli_inputs(self):
        for argv in ([], ["file.csv", "--values", "1"], ["--values", "1", "--columns", "x"], ["file.csv", "--scale", "100"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exc:
                    main(argv)
                self.assertEqual(exc.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
