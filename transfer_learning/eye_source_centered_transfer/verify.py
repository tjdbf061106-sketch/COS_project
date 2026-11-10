"""Verify published evidence, or compare a fresh complete rerun with that evidence."""
from pathlib import Path
import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from common import read_json, sha256, vectorize, feature_group, objective, score_bundle
from run_eye_source_centered_transfer import metrics

ROOT = Path(__file__).resolve().parent
METHODS = ['source_centered_transfer', 'zero_centered_control', 'frozen_source']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, help='Fresh training output to compare with results/')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve() if args.output_dir else ROOT/'results'
    files = read_json(ROOT/'checksums.json')['files']
    for name, expected in files.items():
        path = (ROOT/name).resolve()
        assert path.is_relative_to(ROOT) and sha256(path) == expected, name
    for name, info in read_json(ROOT/'input_manifest.json').items():
        assert sha256(ROOT/name) == info['sha256'], name
    for name, info in read_json(ROOT/'source_manifest.json')['files'].items():
        assert sha256(ROOT/name) == info['sha256'], name
    protocol = read_json(ROOT/'data/protocol.json')
    mapping = read_json(ROOT/'data/mapping.json')
    assert sha256(ROOT/'data/mapping.json') == protocol['mapping_sha256']
    assert sha256(ROOT/'source_model/eye_A_final.joblib') == protocol['source_model_sha256']
    source = joblib.load(ROOT/'source_model/eye_A_final.joblib')
    assert source['format'] == 'eye-A-grouped-v1' and source['representation'] == 'wmean'
    assert source['metadata']['evaluation_unique_rows'] == source['metadata']['training_rows'] == 673
    payloads = read_json(ROOT/'data/payloads.json')
    cohort = pd.read_csv(ROOT/'data/formulations.csv')
    ids = cohort.formulation_id.tolist()
    assert ids == [row['formulation_id'] for row in payloads]
    y = cohort.label.to_numpy(dtype=int)
    assert len(y) == 16 and np.bincount(y).tolist() == [5, 11]
    pairs = [vectorize(row, source['feature_names'], mapping) for row in payloads]
    X = np.stack([pair[0] for pair in pairs])
    groups = np.array([feature_group(row) for row in X])
    assert len(np.unique(groups)) == 15
    spec = importlib.util.spec_from_file_location('source_predict', ROOT/'source_model/predict.py')
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    by_id = {row['id']: row for row in mapping['entries']}
    feature_error = 0.0
    for row, (_, coverage) in zip(X, pairs):
        selected = [item for item in coverage['component_audit'] if item['mapped_id'] and item['amount_pct'] > 0]
        check = original.vectorize_components(source,
                    [by_id[item['mapped_id']]['canonical_smiles'] for item in selected],
                    [item['amount_pct'] for item in selected]).to_numpy()[0]
        np.testing.assert_allclose(row, check, rtol=0, atol=1e-12, equal_nan=True)
        feature_error = max(feature_error, float(np.nanmax(np.abs(row-check))))
    expected = pd.read_csv(ROOT/'results/predictions.csv')
    actual = pd.read_csv(output/'predictions.csv')
    assert actual.formulation_id.tolist() == expected.formulation_id.tolist() == ids
    np.testing.assert_array_equal(actual.label, y)
    np.testing.assert_array_equal(actual.feature_group, groups)
    score_error = 0.0
    saved_metrics = read_json(output/'metrics.json')
    for method in METHODS + ['frozen_source_at_0.5']:
        column = 'frozen_source' if method == 'frozen_source_at_0.5' else method
        threshold = source['threshold'] if method == 'frozen_source' else .5
        values = actual[column+'_score'].to_numpy()
        np.testing.assert_allclose(values, expected[column+'_score'], rtol=0, atol=1e-12)
        score_error = max(score_error, float(np.max(np.abs(values-expected[column+'_score']))))
        recalculated = metrics(y, values, threshold)
        for key, value in recalculated.items():
            np.testing.assert_allclose(value, saved_metrics[method][key], rtol=0, atol=1e-12)
        if method != 'frozen_source_at_0.5':
            np.testing.assert_array_equal(actual[column+'_prediction'], values >= threshold)
    np.testing.assert_allclose(actual.frozen_source_score, source['pipeline'].predict_proba(X)[:, 1], rtol=0, atol=1e-12)
    assert read_json(output/'bootstrap_ci.json') == read_json(ROOT/'results/bootstrap_ci.json')
    assert read_json(output/'protocol.json') == protocol
    model = joblib.load(output/'eye_transfer_final.joblib')
    reference_model = joblib.load(ROOT/'results/eye_transfer_final.joblib')
    assert model['metadata'] == read_json(output/'metadata.json')
    assert model['metadata']['source_model_sha256'] == protocol['source_model_sha256']
    assert model['metadata']['protocol_sha256'] == sha256(ROOT/'data/protocol.json')
    assert model['metadata']['source_model_evaluation_unique_rows'] == 673
    assert model['metadata']['oof_evaluation'] == saved_metrics['source_centered_transfer']
    assert model['feature_names'] == source['feature_names'] and model['mapping'] == mapping
    assert model['threshold'] == .5
    np.testing.assert_array_equal(model['pipeline'][:-1].transform(X), source['pipeline'][:-1].transform(X))
    np.testing.assert_allclose(model['pipeline'].predict_proba(X), reference_model['pipeline'].predict_proba(X), rtol=0, atol=1e-12)
    refit = pd.read_csv(output/'refit_predictions_NOT_validation.csv')
    np.testing.assert_allclose(refit.score, model['pipeline'].predict_proba(X)[:, 1], rtol=0, atol=1e-12)
    estimator = model['pipeline'].steps[-1][1]
    base = source['pipeline'].steps[-1][1]
    anchor = np.r_[base.coef_.ravel(), base.intercept_]
    theta = np.r_[estimator.coef_.ravel(), estimator.intercept_]
    design = np.c_[source['pipeline'][:-1].transform(X), np.ones(len(y))]
    gradient = objective(theta, design, y, anchor, protocol['lambda'])[1]
    assert np.max(np.abs(gradient)) < 1e-5
    folds = read_json(output/'fold_log.json')
    assert len(folds) == 30
    exposure = {method: np.zeros(len(y), dtype=int) for method in METHODS[:2]}
    checked = 0
    for fold in folds:
        train = np.array([ids.index(fid) for fid in fold['train_ids']])
        test = np.array([ids.index(fid) for fid in fold['test_ids']])
        assert not set(train) & set(test) and set(train) | set(test) == set(range(len(y)))
        assert not set(groups[train]) & set(groups[test])
        exposure[fold['method']][test] += 1
        if args.output_dir:
            bundle = joblib.load(output/fold['model_file'])
            np.testing.assert_allclose(bundle['pipeline'].predict_proba(X[test])[:, 1],
                                       actual[fold['method']+'_score'].to_numpy()[test], rtol=0, atol=1e-12)
            checked += 1
    for counts in exposure.values():
        np.testing.assert_array_equal(counts, np.ones(len(y)))
    if args.output_dir:
        regenerated = np.load(output/'features.npz')
        np.testing.assert_allclose(X, regenerated['X'], rtol=0, atol=1e-12, equal_nan=True)
        np.testing.assert_array_equal(groups, regenerated['groups'])
    with tempfile.TemporaryDirectory(prefix='eye_transfer_cli_') as temporary:
        example = ROOT/'examples/CTFA1996_HZT.json'
        result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'predict.py'), '--input', str(example),
                                 '--model', str(output/'eye_transfer_final.joblib')], cwd=temporary,
                                capture_output=True, check=True, encoding='utf-8', timeout=120)
        assert json.loads(result.stdout) == score_bundle(model, read_json(example))
    report = {'status': 'passed', 'mode': 'full_rerun_comparison' if args.output_dir else 'published_evidence',
              'checksummed_files': len(files), 'target_rows': len(y), 'target_groups': len(set(groups)),
              'source_evaluation_rows': 673, 'feature_recipe_max_abs_error': feature_error,
              'oof_score_max_abs_error': score_error, 'fold_models_reloaded': checked,
              'group_separation_and_single_oof_exposure': True, 'metrics_recalculated': True,
              'bootstrap_matches_reference': True, 'cli_from_other_directory': True,
              'scope': 'reconstruction reproducibility; not independent external validation'}
    if args.report:
        args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    with threadpool_limits(limits=1):
        main()
