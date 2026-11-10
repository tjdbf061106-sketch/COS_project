import copy
import csv
import io
import unittest
from unittest.mock import patch

from desktop.engine import run
from desktop.identity import check_components, local_references
from desktop.service import analyze, canonicalize, caution_for_report, export_csv, validate_ingredients


def normalize(values):
    return run({"action": "canonicalize", "smiles": list(values)})


def payload(name="에탄올", smiles="CCO", **extra):
    return {"scope": "partial", "components": [{"component_id": "a", "name": name,
             "canonical_smiles": smiles, "amount_pct": 20, **extra}]}


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.normalizer = patch("desktop.service.canonicalize", side_effect=normalize)
        self.normalizer.start()
        self.addCleanup(self.normalizer.stop)

    def test_mismatch_blocks_prediction_and_caution(self):
        data = payload(smiles="O")
        with patch("desktop.service.call_worker") as worker:
            result = analyze(data)
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["validation"]["issues"][0]["code"], "name_structure_mismatch")
        worker.assert_not_called()
        with self.assertRaisesRegex(ValueError, "일치하지"):
            caution_for_report({"input": data})

    def test_equivalent_names_cas_and_structures_preserve_input(self):
        for name, smiles in [("에탄올", "OCC"), (" ETHANOL ", "C(C)O"), ("64-17-5", "CCO"),
                             ("SLS", "[Na+].CCCCCCCCCCCCOS([O-])(=O)=O")]:
            with self.subTest(name=name):
                data = payload(name, smiles)
                original = copy.deepcopy(data)
                checked = validate_ingredients(data)
                self.assertTrue(checked["valid"], checked["issues"])
                self.assertEqual(data, original)
                self.assertEqual(caution_for_report({"input": data})["recognized_component_count"], 1)

    def test_direct_structure_gets_registered_aliases(self):
        result = caution_for_report({"input": payload("직접 입력 원료", "OCC", mode="smiles", query="OCC")})
        self.assertEqual(result["recognized_component_count"], 1)
        self.assertFalse(result["unmatched_components"])

    def test_conflicting_query_and_cas_cannot_override_structure(self):
        for extra in ({"query": "정제수", "mode": "name"}, {"cas": "7732-18-5"}):
            with self.subTest(extra=extra):
                result = validate_ingredients(payload(**extra))
                self.assertFalse(result["valid"])
                self.assertEqual(result["issues"][0]["code"], "name_structure_mismatch")

    def test_salts_isotopes_and_stereochemistry_are_not_collapsed(self):
        for name, smiles in [("에탄올", "[13CH3]CO"), ("에탄올", "CCO.[Na+]"),
                             ("젖산", "C[C@H](O)C(=O)O")]:
            with self.subTest(smiles=smiles):
                self.assertFalse(validate_ingredients(payload(name, smiles))["valid"])

    def test_unknown_or_offline_name_requires_resolution_but_smiles_only_works(self):
        with patch("desktop.identity.references", side_effect=ValueError("연결 실패")):
            result = validate_ingredients(payload("unregistered label", "CCC"))
            self.assertFalse(result["valid"])
            self.assertEqual(result["issues"][0]["code"], "identity_unverified")
            self.assertTrue(validate_ingredients(payload("", "CCC", mode="smiles"))["valid"])

    def test_invalid_smiles_and_zero_percent(self):
        self.assertFalse(validate_ingredients(payload("", "not-a-smiles", mode="smiles"))["valid"])
        data = payload()
        data["components"].append({"component_id": "zero", "name": "unresolvable", "canonical_smiles": "?", "amount_pct": 0})
        with patch("desktop.identity.urllib.request.urlopen", side_effect=AssertionError("Unexpected request")):
            checked = validate_ingredients(data)
        self.assertTrue(checked["valid"])
        self.assertEqual(len(checked["identities"]), 1)

    def test_forged_identity_metadata_does_not_bypass_checks(self):
        result = validate_ingredients(payload(smiles="O", identity_aliases=["에탄올"], confirmed=True,
                                              identity={"status": "verified"}))
        self.assertFalse(result["valid"])

    def test_coverage_counts_and_csv(self):
        data = payload()
        data["components"].append({"component_id": "b", "name": "글리세린", "canonical_smiles": "OCC(O)CO", "amount_pct": 5})
        result = caution_for_report({"input": data})
        self.assertEqual(result["recognized_component_count"], 1)
        self.assertEqual(len(result["unmatched_components"]), 1)
        report = {"input": data, "results": {}, "caution": result, "validation": validate_ingredients(data),
                  "input_hash": "test", "created_at": "test"}
        rows = list(csv.DictReader(io.StringIO(export_csv(report))))
        coverage = {r["name_or_endpoint"]: r["amount_pct_or_score"] for r in rows if r["kind"] == "caution_coverage"}
        self.assertEqual(coverage, {"recognized": "1", "unmatched": "1"})
        identities = [r for r in rows if r["kind"] == "identity"]
        self.assertEqual(len(identities), 2)
        self.assertTrue(all(row["amount_pct_or_score"] == "verified" for row in identities))
        self.assertEqual(identities[0]["smiles_or_label"], "CCO")
        self.assertIn("pubchem.ncbi.nlm.nih.gov/compound/702", identities[0]["details"])

    def test_same_caution_category_does_not_make_compounds_identical(self):
        reference = local_references("리날룰")[0]
        self.assertFalse(validate_ingredients(payload("리모넨", reference["smiles"]))["valid"])


class IdentityWorkerFallbackTests(unittest.TestCase):
    def test_missing_eye_engine_can_use_skin_for_identity(self):
        canonicalize.cache_clear()
        def worker(endpoint, request):
            if endpoint == "eye":
                raise RuntimeError("Missing eye runtime")
            return normalize(request["smiles"])
        with patch("desktop.service.call_worker", side_effect=worker):
            self.assertEqual(canonicalize(("OCC",))[0]["canonical_smiles"], "CCO")
        canonicalize.cache_clear()
