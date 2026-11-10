import csv
import io
import json
import unittest
from unittest.mock import patch

from desktop.evidence import describe_evidence, LABELS
from desktop.annotations import fetch_annotations, summarize_record
from desktop.service import export_csv


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.glycerin = describe_evidence("OCC(O)CO")
        cls.sls = describe_evidence("CCCCCCCCCCCCOS(=O)(=O)[O-].[Na+]")

    def test_only_two_local_scores_and_known_fragrance_similarity(self):
        result = self.glycerin
        self.assertEqual([s["model_id"] for s in result["scores"]], list(LABELS))
        self.assertEqual(len(result["scores"]), 2)
        self.assertEqual(result["properties"]["formula"], "C3H8O3")
        self.assertTrue(result["preview"].startswith("data:image/png;base64,"))
        self.assertAlmostEqual(result["scores"][0]["score"], 2 / 13)
        self.assertEqual(result["scores"][0]["nearest"]["name"], "Citronellol")
        self.assertEqual(result["scores"][0]["reference_set_size"], 20)
        self.assertEqual(result["scores"][1]["score"], 0)
        limonene = describe_evidence("CC1=CCC(CC1)C(=C)C")
        self.assertEqual(limonene["scores"][0]["score"], 1)
        self.assertEqual(limonene["scores"][0]["nearest"]["name"], "Limonene")
        self.assertEqual(limonene["scores"][1]["score"], .3)
        for score in result["scores"]:
            self.assertNotIn("threshold", score)
            self.assertNotIn("property_score", score)
            self.assertNotIn("structure_score", score)
            self.assertEqual(len(score["source_sha256"]), 64)

    def test_head_patterns_are_real_and_all_rule_levels_preserved(self):
        result = self.sls
        self.assertEqual(result["scores"][1]["score"], 1)
        self.assertEqual(result["scores"][1]["longest_aliphatic_chain"], 12)
        self.assertEqual([p["pattern_id"] for p in result["patterns"]], ["anionic_sulfate_ester"])
        self.assertTrue(result["patterns"][0]["preview"].startswith("data:image/png;base64,"))
        for smiles, expected in [("COS(=O)(=O)[O-].[Na+]", .5), ("CCCCCCCCCCCCCCCCO", .3), ("O", 0)]:
            self.assertEqual(describe_evidence(smiles)["scores"][1]["score"], expected)
        water = describe_evidence("O")
        self.assertEqual(water["patterns"], [])
        self.assertTrue(any("안전성의 근거가 아닙니다" in note for note in water["notes"]))
        with self.assertRaises(ValueError):
            describe_evidence("not-a-smiles")

    def test_unevaluated_large_carbon_structure_is_not_shown_as_zero(self):
        score = describe_evidence("C" * 61)["scores"][1]
        self.assertEqual(score["status"], "held")
        self.assertIsNone(score["score"])
        self.assertFalse(score["chain_evaluated"])
        self.assertEqual(score["raw_result"]["score"], 0)
        self.assertIn("60", score["reason"])

    def test_exports_keep_local_methods_matches_and_provenance(self):
        report = {"input": {"components": []}, "results": {}, "validation": {"total": 100, "unlisted": 0},
                  "input_hash": "test", "created_at": "test", "evidence": {"sls": self.sls}}
        text = export_csv(report)
        rows = list(csv.reader(io.StringIO(text)))
        scores = [row for row in rows if row[0] == "auxiliary"]
        self.assertEqual(len(scores), 2)
        self.assertEqual([row[5] for row in scores], list(LABELS))
        self.assertTrue(all(row[4] == "" for row in scores))
        self.assertIn("top_matches", scores[0][6])
        self.assertIn("matched_head_groups", scores[1][6])
        self.assertIn("pattern,sls", text)
        self.assertIn(self.sls["source"]["sha256"], text)
        self.assertNotIn("category_scorer", text)
        self.assertNotIn("final_pesticides", text)
        self.assertNotIn("han_endocrine", text)
        json.dumps(report, allow_nan=False)


class AnnotationTests(unittest.TestCase):
    def test_original_excerpt_sources_and_korean_priority(self):
        record = {"Record": {"RecordTitle": "Water", "Reference": [{"ReferenceNumber": 1, "SourceName": "Test Source", "URL": "https://example.org/source"}],
                 "Section": [{"Information": [{"ReferenceNumber": 1, "Value": {"StringWithMarkup": [{"String": "English source description."}, {"String": "한국어 원문 설명"}]}}]}]}}
        result = summarize_record(record, 962)
        self.assertEqual(result["entries"][0]["text"], "한국어 원문 설명")
        self.assertEqual(result["entries"][0]["source"], "Test Source")
        self.assertEqual(result["entries"][0]["url"], "https://example.org/source")
        self.assertEqual(result["cid"], 962)

    def test_ambiguous_lookup_never_merges_annotations(self):
        with patch("desktop.annotations._json", return_value={"IdentifierList": {"CID": [1, 2]}}) as fetch:
            result = fetch_annotations("CCO")
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result["entries"], [])
