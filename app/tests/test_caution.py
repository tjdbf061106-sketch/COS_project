import csv
import io
import unittest

from desktop.service import caution, caution_for_report, caution_options, export_csv
from desktop.identity import local_references


class CautionTest(unittest.TestCase):
    def test_options_list_conditions_and_medications(self):
        options = caution_options()
        self.assertEqual(len(options["conditions"]), 6)
        self.assertEqual(len(options["medications"]), 7)

    def test_no_selection_has_not_selected_status(self):
        self.assertEqual(caution({"components": []}, [])["status"], "not_selected")

    def test_unregistered_ingredients_are_reported_without_selection(self):
        active = [
            {"component_id": "known", "name": "에탄올", "canonical_smiles": "CCO", "amount_pct": 15},
            {"component_id": "unknown", "name": "글리세린", "canonical_smiles": "OCC(O)CO", "amount_pct": 5},
        ]
        result = caution({}, active)
        self.assertEqual(result["status"], "not_selected")
        self.assertEqual(result["recognized_component_count"], 1)
        self.assertEqual([c["component_id"] for c in result["unmatched_components"]], ["unknown"])
        self.assertEqual(result["unmatched_components"][0]["display_name"], "글리세린")

    def test_dictionary_coverage_does_not_depend_on_threshold_or_selected_rule(self):
        active = [{"name": "에탄올", "canonical_smiles": "CCO", "amount_pct": 15}]
        for condition in ("atopic_dermatitis", "dry_eye_disease"):
            with self.subTest(condition=condition):
                result = caution({"caution": {"conditions": [condition]}}, active)
                self.assertTrue(result["results"][condition]["no_findings"])
                self.assertEqual(result["unmatched_components"], [])
                self.assertEqual(result["recognized_component_count"], 1)

    def test_registered_structure_and_original_query_count_as_recognized(self):
        active = [
            {"name": "직접 입력 원료", "canonical_smiles": "CCO", "amount_pct": 5},
            {"name": "Resolved title", "query": "메틸이소티아졸리논", "canonical_smiles": "", "amount_pct": 0.01},
            {"name": "  RETINOL  ", "canonical_smiles": "", "amount_pct": 1},
        ]
        result = caution({}, active)
        self.assertEqual(result["unmatched_components"], [])
        self.assertEqual(result["recognized_component_count"], 3)

    def test_zero_percent_is_excluded_and_direct_smiles_stays_identifiable(self):
        data = {"input": {"scope": "partial", "components": [
            {"component_id": "zero", "name": "not registered", "canonical_smiles": "CCC", "amount_pct": 0},
            {"component_id": "direct", "name": "직접 입력 원료", "query": "CCCO", "canonical_smiles": "CCCO", "amount_pct": 1},
        ]}}
        result = caution_for_report(data)
        self.assertEqual(result["recognized_component_count"], 0)
        self.assertEqual([c["component_id"] for c in result["unmatched_components"]], ["direct"])
        self.assertEqual(result["unmatched_components"][0]["display_name"], "CCCO")

    def test_csv_preserves_unregistered_ingredients_without_selection(self):
        active = [{"component_id": "a", "name": "=unknown, ingredient", "canonical_smiles": "CCC", "amount_pct": 2}]
        report = {"input": {"components": active}, "results": {}, "validation": {"total": 2, "unlisted": 98},
                  "input_hash": "h", "created_at": "t", "caution": caution({}, active)}
        rows = list(csv.DictReader(io.StringIO(export_csv(report))))
        unmatched = [r for r in rows if r["kind"] == "caution_unmatched"]
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(unmatched[0]["name_or_endpoint"], "'=unknown, ingredient")
        self.assertEqual(unmatched[0]["smiles_or_label"], "CCC")
        self.assertEqual(unmatched[0]["details"], "사전에 없어서 확인하지 못한 원료")

    def test_matches_name_then_falls_back_to_user_query(self):
        active = [
            {"name": "에탄올", "canonical_smiles": "CCO", "amount_pct": 20.0, "query": "에탄올"},
            {"name": "직접 입력 원료", "canonical_smiles": "Cn1sccc1=O", "amount_pct": 0.01, "query": "MIT"},
            {"name": "2-Methyl-4-isothiazolin-3-one", "canonical_smiles": "", "amount_pct": 0.01, "query": "x"},
            {"name": "Cetyl alcohol", "canonical_smiles": "", "amount_pct": 2.0, "query": "cetyl alcohol"},
        ]
        result = caution({"caution": {"conditions": ["atopic_dermatitis"], "medications": []}}, active)
        tags = {c["tag"]: c for c in result["results"]["atopic_dermatitis"]["cautions"]}
        self.assertIn("alcohol_high_conc", tags)
        self.assertIn("isothiazolinone_preservative", tags)
        self.assertNotIn("Cetyl alcohol", [m["name"] for m in tags["alcohol_high_conc"]["matched_components"]])

    def test_unknown_id_is_rejected(self):
        with self.assertRaises(ValueError):
            caution({"caution": {"conditions": ["nope"]}}, [])

    def test_csv_contains_caution_rows(self):
        active = [{"name": "Retinol", "canonical_smiles": "", "amount_pct": 1.0, "query": "Retinol"}]
        report = {
            "input": {"components": []}, "results": {}, "validation": {"total": 1, "unlisted": 99},
            "input_hash": "h", "created_at": "t",
            "caution": caution({"caution": {"medications": ["isotretinoin_oral"]}}, active),
        }
        text = export_csv(report)
        self.assertIn("caution_medication", text)
        self.assertIn("topical_retinoid_cosmetic", text)

    def test_report_page_refresh_uses_saved_input(self):
        data = {"input": {"scope": "partial", "components": [
                    {"component_id": "a", "name": "Retinol", "query": "Retinol", "canonical_smiles": local_references("Retinol")[0]["smiles"], "amount_pct": 1.0}]},
                "caution": {"conditions": [], "medications": ["benzoyl_peroxide_rx"]}}
        result = caution_for_report(data)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["medication_results"]["benzoyl_peroxide_rx"]["interactions"][0]["tag"],
                         "topical_retinoid_cosmetic")


if __name__ == "__main__":
    unittest.main()
