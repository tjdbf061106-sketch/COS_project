import copy
import json
import unittest
from unittest.mock import patch

from desktop.validation import validate, digest
from desktop.service import parse_csv, analyze, export_csv


def example():
    return {"name": "검증 배합", "scope": "complete", "components": [
        {"component_id": "a", "name": "A", "canonical_smiles": "CCO", "amount_pct": 20.0},
        {"component_id": "b", "name": "B", "canonical_smiles": "O", "amount_pct": 80.0}]}


class InputTests(unittest.TestCase):
    def test_missing_values_never_fallback(self):
        for value in (None, "", True, float("inf"), float("nan"), -1, 101):
            with self.subTest(value=value):
                payload = example()
                payload["components"][0]["amount_pct"] = value
                self.assertFalse(validate(payload)["valid"])

    def test_no_silent_normalization(self):
        payload = example()
        payload["components"][1]["amount_pct"] = 81
        self.assertFalse(validate(payload)["valid"])
        payload["components"][1]["amount_pct"] = 79
        self.assertFalse(validate(payload)["valid"])
        payload["scope"] = "partial"
        self.assertTrue(validate(payload)["valid"])
        self.assertEqual(validate(payload)["unlisted"], 1)
        self.assertEqual(payload["components"][1]["amount_pct"], 79)

    def test_unresolved_positive_rows_block(self):
        payload = example()
        payload["components"][0]["canonical_smiles"] = ""
        self.assertFalse(validate(payload)["valid"])
        payload["components"][0]["amount_pct"] = 0
        payload["scope"] = "partial"
        checked = validate(payload)
        self.assertTrue(checked["valid"])
        self.assertEqual(len(checked["active"]), 1)
        self.assertTrue(checked["warnings"])
        payload["components"][1]["amount_pct"] = 0
        self.assertFalse(validate(payload)["valid"])

    def test_csv_missing_amount_and_untrusted_text(self):
        rows = parse_csv('성분명,SMILES,함량(%)\n정제수,O,80\n=cmd,CCO,q.s.\n')
        self.assertIsNone(rows[1]["amount_pct"])
        self.assertEqual(rows[1]["amount_text"], "q.s.")
        self.assertEqual(rows[1]["name"], "=cmd")

    def test_partial_coverage_not_complete(self):
        payload = example()
        payload["scope"] = "partial"
        payload["components"][0]["amount_pct"] = 10
        payload["components"][1]["amount_pct"] = 5
        checked = validate(payload)
        self.assertEqual(checked["unlisted"], 85)
        self.assertEqual([r["amount_pct"] for r in checked["active"]], [10, 5])

    def test_csv_nonfinite_and_truncated_rows_remain_editable(self):
        rows = parse_csv('name,smiles,amount_pct\nA,O,NaN\nB,CCO,Inf\nC,O\n')
        self.assertEqual([r["amount_pct"] for r in rows], [None, None, None])
        self.assertEqual(rows[0]["amount_text"], "NaN")
        self.assertEqual(rows[1]["amount_text"], "Inf")
        json.dumps(rows, allow_nan=False)

    def test_one_engine_failure_preserves_other_result(self):
        def worker(endpoint, request):
            if endpoint == "eye":
                raise ValueError("test eye unavailable")
            return {"status": "complete", "score": 0.4, "threshold": 0.33,
                    "predicted_class": 1, "label_text": "EPA I·II·III", "model_id": "test"}
        original = example()
        snapshot = copy.deepcopy(original)
        with patch("desktop.service.call_worker", side_effect=worker), patch("desktop.service.validate_ingredients", side_effect=validate):
            report = analyze(original)
        self.assertEqual(original, snapshot)
        self.assertEqual(report["results"]["skin"]["status"], "complete")
        self.assertEqual(report["results"]["eye"]["status"], "held")
        self.assertIsNone(report["results"]["eye"]["score"])
        self.assertEqual(report["input_hash"], digest(original))
        self.assertEqual([w["relative_weight"] for w in report["weights"]], [.2, .8])
        restored = json.loads(json.dumps(report, ensure_ascii=False))
        self.assertEqual(restored["input"], original)
        original["components"][0]["name"] = "=UNTRUSTED()"
        report["input"] = original
        self.assertIn("'=UNTRUSTED()", export_csv(report))
        self.assertNotEqual(digest(original), report["input_hash"])


if __name__ == "__main__":
    unittest.main()
