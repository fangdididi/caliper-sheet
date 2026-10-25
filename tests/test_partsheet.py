import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import partsheet as ps  # noqa: E402

BRACKET = os.path.join(ROOT, "examples", "shelf-bracket.json")
KNOB = os.path.join(ROOT, "examples", "knob-insert.json")


def dim(code, readings=None, **kw):
    d = {"code": code}
    if readings is not None:
        d["readings"] = readings
    d.update(kw)
    return d


def run(dims, **extra):
    data = {"dims": dims}
    data.update(extra)
    return ps.analyse(data)


def row(res, code):
    return next(r for r in res["rows"] if r["code"] == code)


class Formulas(unittest.TestCase):
    def test_basic_math(self):
        self.assertAlmostEqual(ps.eval_formula("A + 2*B - C/4", {"A": 1, "B": 2, "C": 8}), 3)

    def test_unary_minus(self):
        self.assertEqual(ps.eval_formula("-A + 10", {"A": 4}), 6)

    def test_none_propagates(self):
        self.assertIsNone(ps.eval_formula("A + B", {"A": 1, "B": None}))

    def test_rejects_calls(self):
        with self.assertRaises(ps.PartError):
            ps.eval_formula("__import__('os')", {})

    def test_rejects_power(self):
        with self.assertRaises(ps.PartError):
            ps.eval_formula("A ** 2", {"A": 2})

    def test_rejects_strings(self):
        with self.assertRaises(ps.PartError):
            ps.eval_formula("'x'", {})

    def test_divide_by_zero(self):
        with self.assertRaises(ps.PartError):
            ps.eval_formula("A / 0", {"A": 1})

    def test_names(self):
        self.assertEqual(ps.formula_names("L1 - 2*S1 + S1"), ["L1", "S1"])


class Hints(unittest.TestCase):
    def test_quarter_inch(self):
        self.assertEqual(ps.imperial_hint(6.35), "1/4 in")

    def test_one_and_a_half(self):
        self.assertEqual(ps.imperial_hint(38.1), "1 1/2 in")

    def test_metric_round_number_not_flagged(self):
        self.assertIsNone(ps.imperial_hint(25.0))

    def test_half_mm_not_flagged(self):
        self.assertIsNone(ps.imperial_hint(12.5))

    def test_random_value_not_flagged(self):
        self.assertIsNone(ps.imperial_hint(7.3))

    def test_m3_clearance(self):
        self.assertIn("M3 clearance (normal)", ps.hole_hint(3.42))

    def test_m4_tap(self):
        self.assertIn("M4 tap drill", ps.hole_hint(3.3))

    def test_no_hole_match(self):
        self.assertIsNone(ps.hole_hint(7.7))


class Measured(unittest.TestCase):
    def test_median_and_spread(self):
        r = row(run([dim("L1", [10.0, 10.04, 10.02])]), "L1")
        self.assertEqual(r["value"], 10.02)
        self.assertEqual(r["spread"], 0.04)

    def test_remeasure_on_wide_spread(self):
        r = row(run([dim("L1", [10.0, 10.3, 10.1])]), "L1")
        self.assertTrue(any(f.startswith("REMEASURE") for f in r["flags"]))

    def test_tight_spread_clean(self):
        r = row(run([dim("L1", [10.0, 10.02, 10.04], role="mating")]), "L1")
        self.assertEqual(r["flags"], [])

    def test_tool_too_coarse(self):
        r = row(run([dim("L1", [10, 10, 10], tool="ruler", role="mating")]), "L1")
        self.assertTrue(any(f.startswith("TOOL_TOO_COARSE") for f in r["flags"]))

    def test_few_readings_on_mating(self):
        r = row(run([dim("L1", [10.0], role="mating")]), "L1")
        self.assertTrue(any(f.startswith("FEW_READINGS") for f in r["flags"]))

    def test_few_readings_ok_on_free(self):
        r = row(run([dim("L1", [10.0])]), "L1")
        self.assertEqual(r["flags"], [])

    def test_custom_tool(self):
        r = row(run([dim("L1", [10, 10, 10], tool="laser")], tools={"laser": 0.01}), "L1")
        self.assertEqual(r["tool"], "laser")

    def test_unknown_tool(self):
        with self.assertRaises(ps.PartError):
            run([dim("L1", [10], tool="eyeball")])

    def test_negative_reading(self):
        with self.assertRaises(ps.PartError):
            run([dim("L1", [-1])])

    def test_custom_tolerance(self):
        r = row(run([dim("L1", [10, 10, 10], tol=0.02, role="mating")]), "L1")
        self.assertTrue(any(f.startswith("TOOL_TOO_COARSE") for f in r["flags"]))


class Validation(unittest.TestCase):
    def test_needs_dims(self):
        with self.assertRaises(ps.PartError):
            ps.analyse({})

    def test_duplicate_code(self):
        with self.assertRaises(ps.PartError):
            run([dim("A", [1]), dim("A", [2])])

    def test_bad_code(self):
        with self.assertRaises(ps.PartError):
            run([dim("1 A", [1])])

    def test_two_sources(self):
        with self.assertRaises(ps.PartError):
            run([dim("A", [1], formula="2")])

    def test_bad_role(self):
        with self.assertRaises(ps.PartError):
            run([dim("A", [1], role="vital")])


class Derived(unittest.TestCase):
    def test_out_of_order_dependency(self):
        res = run([dim("C", formula="B * 2"), dim("B", formula="A + 1"), dim("A", [4, 4, 4])])
        self.assertEqual(res["values"]["C"], 10)

    def test_loop(self):
        with self.assertRaises(ps.PartError):
            run([dim("A", formula="B + 1"), dim("B", formula="A + 1")])

    def test_self_reference(self):
        with self.assertRaises(ps.PartError):
            run([dim("A", formula="A + 1")])

    def test_unknown_code(self):
        with self.assertRaises(ps.PartError):
            run([dim("A", formula="Z + 1")])

    def test_derived_tbd(self):
        res = run([dim("A", tbd=True), dim("B", formula="A + 1", role="mating")])
        self.assertIsNone(res["values"]["B"])
        self.assertEqual(res["verdict"], "DRAFT_ONLY")

    def test_non_positive(self):
        r = row(run([dim("A", [5, 5, 5]), dim("B", [8, 8, 8]), dim("C", formula="A - B")]), "C")
        self.assertTrue(any(f.startswith("NON_POSITIVE") for f in r["flags"]))


class Chains(unittest.TestCase):
    def base(self, overall):
        return [dim("A", [10, 10, 10], role="mating"), dim("B", [20, 20, 20], role="mating"),
                dim("L", [overall] * 3, role="mating")]

    def status(self, overall):
        res = run(self.base(overall), chains=[{"name": "x", "parts": ["A", "B"], "overall": "L"}])
        return res["chains"][0]["status"], res["verdict"]

    def test_closes(self):
        self.assertEqual(self.status(30.05), ("CLOSES", "READY"))

    def test_loose(self):
        self.assertEqual(self.status(30.25)[0], "LOOSE")

    def test_fail_blocks(self):
        self.assertEqual(self.status(31.0), ("CLOSURE_FAIL", "MEASURE_AGAIN"))

    def test_open_chain(self):
        res = run(self.base(30) + [dim("C", tbd=True)], chains=[{"parts": ["A", "C"], "overall": "L"}])
        self.assertEqual(res["chains"][0]["status"], "OPEN")

    def test_unknown_chain_code(self):
        with self.assertRaises(ps.PartError):
            run(self.base(30), chains=[{"parts": ["A", "Q"], "overall": "L"}])


class Examples(unittest.TestCase):
    def test_bracket_ready(self):
        res = ps.analyse(ps.load(BRACKET))
        self.assertEqual(res["verdict"], "READY")
        self.assertEqual(res["values"]["X2"], 70)

    def test_knob_measure_again_with_imperial_hint(self):
        res = ps.analyse(ps.load(KNOB))
        self.assertEqual(res["verdict"], "MEASURE_AGAIN")
        self.assertTrue(any("1/2 in" in h for h in row(res, "W1")["hints"]))

    def test_table(self):
        md = ps.table_md(ps.analyse(ps.load(BRACKET)))
        self.assertIn("| X2 | hole 2 from datum A | 70 |", md)


class Svg(unittest.TestCase):
    def test_true_scale_units(self):
        data = ps.load(BRACKET)
        svg = ps.render_svg(data, ps.analyse(data))
        self.assertIn('width="297.0mm"', svg)
        self.assertIn("SCALE 1:1", svg)
        self.assertEqual(svg.count("<circle"), 2)

    def test_big_part_scales_down(self):
        data = ps.load(BRACKET)
        data = copy.deepcopy(data)
        data["dims"][0]["readings"] = [400, 400, 400]
        data["chains"] = []
        self.assertIn("SCALE 1:5", ps.render_svg(data, ps.analyse(data)))

    def test_small_part_scales_up(self):
        data = {"dims": [dim("L", [8, 8, 8]), dim("W", [5, 5, 5]), dim("T", [2, 2, 2])],
                "body": {"L": "L", "W": "W", "T": "T"}}
        self.assertIn("SCALE 2:1", ps.render_svg(data, ps.analyse(data)))

    def test_medium_part_stays_true_scale(self):
        data = {"dims": [dim("L", [20, 20, 20]), dim("W", [10, 10, 10]), dim("T", [3, 3, 3])],
                "body": {"L": "L", "W": "W", "T": "T"}}
        self.assertIn("SCALE 1:1", ps.render_svg(data, ps.analyse(data)))

    def test_tbd_body_refused(self):
        data = {"dims": [dim("L", tbd=True), dim("W", [1]), dim("T", [1])], "body": {"L": "L", "W": "W", "T": "T"}}
        with self.assertRaises(ps.PartError):
            ps.render_svg(data, ps.analyse(data))

    def test_text_is_escaped(self):
        data = {"part": {"name": "<b>&"}, "dims": [dim("L", [20] * 3), dim("W", [10] * 3), dim("T", [3] * 3)],
                "body": {"L": "L", "W": "W", "T": "T"}}
        svg = ps.render_svg(data, ps.analyse(data))
        self.assertIn("&lt;b&gt;&amp;", svg)


class Cli(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "partsheet.py"), *args],
                              capture_output=True, text=True)

    def test_exit_codes(self):
        self.assertEqual(self.cli("check", BRACKET).returncode, 0)
        self.assertEqual(self.cli("check", KNOB).returncode, 2)
        self.assertEqual(self.cli("check", "/nope.json").returncode, 1)

    def test_json_output(self):
        out = json.loads(self.cli("check", BRACKET, "--json").stdout)
        self.assertEqual(out["verdict"], "READY")

    def test_svg_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.svg")
            self.assertEqual(self.cli("svg", BRACKET, "-o", p).returncode, 0)
            self.assertTrue(open(p).read().startswith("<svg"))


if __name__ == "__main__":
    unittest.main()
