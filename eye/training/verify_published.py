"""Verify published OOF tables and final predictions without retraining."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import epa_harness as u
import predict
from run_comparison import INPUTS
from verify_comparison import verify_tables

ROOT = Path(__file__).resolve().parent
EVALUATION = ROOT.parent / "evaluation"


def main():
    if not __debug__:
        raise RuntimeError("Run without -O: upstream verifiers use assertions")
    path = EVALUATION / "comparison_config.json"
    record = json.loads(path.read_text(encoding="utf-8-sig"))
    cfg = u.load_record(path, record["identity"])
    assert u.hash_json(cfg) == record["identity"]
    assert set(cfg["input_hashes"]) == set((*INPUTS, "source_config.json"))
    assert set(cfg["code_hashes"]) == {"run_comparison.py", "epa_harness.py"}
    for hashes in (cfg["input_hashes"], cfg["code_hashes"]):
        for name, expected in hashes.items():
            assert u.file_hash(ROOT / name) == expected, f"Changed artifact: {name}"
    df = pd.read_csv(ROOT / "input_snapshot.csv", low_memory=False)
    oof = pd.read_csv(EVALUATION / "oof_predictions.csv")
    assert len(df) == 673 and len(oof) == 673 * 3 * 6
    verify_tables(EVALUATION, oof, df, cfg, record["identity"])
    bundle = predict.load_bundle(ROOT.parent / "model" / "eye_A_final.joblib")
    reference = pd.read_csv(EVALUATION / "refit_reference_predictions.csv")
    matrix = np.load(ROOT / (bundle["representation"] + ".npy"), allow_pickle=False)
    actual = predict.predict_features(bundle, matrix)
    assert len(reference) == len(df)
    np.testing.assert_array_equal(reference.formulation_id, df.formulation_id)
    np.testing.assert_allclose(actual.eye_A_score, reference.score, rtol=0, atol=1e-12)
    np.testing.assert_array_equal(actual.eye_A_prediction, reference.prediction)
    print("Published evaluation verified: 12114 OOF rows, metric tables, 673 final predictions")
    print("No full nested-CV retraining or independent external evaluation performed")


if __name__ == "__main__":
    main()
