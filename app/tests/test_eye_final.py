"""Pin the app adapter to the approved all673 Eye package and its decision cutoff."""
import json
import unittest

from desktop.engine import run
from desktop.paths import resources


class FinalEyeModelTests(unittest.TestCase):
    def test_app_adapter_matches_upstream_regression_cases(self):
        root = resources() / "eye"
        fixtures = json.loads((root / "smoke_test_cases.json").read_text(encoding="utf-8"))
        for case in fixtures["cases"]:
            with self.subTest(case=case["name"]):
                amounts = case["amounts"] or [100 / len(case["smiles"])] * len(case["smiles"])
                rows = [{"component_id": str(i), "canonical_smiles": smiles, "amount_pct": amount}
                        for i, (smiles, amount) in enumerate(zip(case["smiles"], amounts))]
                result = run({"action": "predict", "endpoint": "eye", "payload": {"scope": "complete", "components": rows}})
                self.assertAlmostEqual(result["score"], case["expected_score"], places=12)
                self.assertEqual(result["threshold"], 0.48345327423625106)
                self.assertEqual(result["predicted_class"], case["expected_prediction"])
                self.assertEqual(result["model_sha256"], "5d5c0532cd12fd00927c9564ee28dc9c95a8bb396a049c705c77dcafaf5b28e5")
                self.assertEqual(result["model_id"], "eye-5d5c0532cd12")


if __name__ == "__main__":
    unittest.main()
