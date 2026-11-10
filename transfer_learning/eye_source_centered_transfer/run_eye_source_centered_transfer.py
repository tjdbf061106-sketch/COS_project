"""Evaluate documented source-centered transfer, then refit all target rows."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import importlib.metadata
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from sklearn.metrics import confusion_matrix, matthews_corrcoef, roc_auc_score, balanced_accuracy_score
from threadpoolctl import threadpool_limits

from common import FORMAT, read_json, write_json, sha256, vectorize, feature_group, objective

ROOT = Path(__file__).resolve().parent


def metrics(labels, scores, threshold):
    predictions = (scores >= threshold).astype(int)
    return {'n': len(labels), 'correct': int(np.sum(predictions == labels)),
            'accuracy': float(np.mean(predictions == labels)),
            'MCC': float(matthews_corrcoef(labels, predictions)),
            'ROC_AUC': float(roc_auc_score(labels, scores)),
            'balanced_accuracy': float(balanced_accuracy_score(labels, predictions)),
            'threshold': threshold,
            'confusion_matrix': confusion_matrix(labels, predictions, labels=[0, 1]).tolist()}


def fit(design, labels, anchor, protocol):
    options = dict(protocol['optimizer'])
    method = options.pop('method')
    result = minimize(objective, anchor.copy(),
                      args=(design, labels, anchor, protocol['lambda']),
                      jac=True, method=method, options=options)
    gradient = float(np.max(np.abs(result.jac)))
    if not result.success or not np.all(np.isfinite(result.x)) or gradient > 1e-5:
        raise RuntimeError(f'Optimizer failed: {result.message}; gradient={gradient}')
    return result.x, {'success': bool(result.success), 'iterations': int(result.nit),
                      'loss': float(result.fun), 'gradient_max_abs': gradient,
                      'message': str(result.message)}


def make_bundle(source, theta, mapping, metadata):
    pipeline = deepcopy(source['pipeline'])
    classifier = pipeline.steps[-1][1]
    classifier.coef_ = theta[:-1][None, :].copy()
    classifier.intercept_ = theta[-1:].copy()
    return {'format': FORMAT, 'pipeline': pipeline, 'feature_names': source['feature_names'],
            'threshold': .5, 'mapping': mapping, 'metadata': metadata}


def group_bootstrap(y, scores, groups, config):
    rng = np.random.default_rng(config['seed'])
    unique = np.unique(groups)
    values, invalid = [], 0
    for _ in range(config['group_resamples']):
        sample = rng.choice(unique, size=len(unique), replace=True)
        indices = np.concatenate([np.flatnonzero(groups == group) for group in sample])
        if len(np.unique(y[indices])) != 2:
            invalid += 1
            continue
        values.append([matthews_corrcoef(y[indices], scores[indices] >= .5),
                       roc_auc_score(y[indices], scores[indices])])
    values = np.asarray(values)
    return {'resamples': config['group_resamples'], 'valid_resamples': len(values),
            'single_class_resamples_excluded': invalid, 'seed': config['seed'],
            'MCC_95_percentile_interval': np.quantile(values[:, 0], [.025, .975]).tolist(),
            'ROC_AUC_95_percentile_interval': np.quantile(values[:, 1], [.025, .975]).tolist(),
            'scope': 'resample fixed OOF scores by feature group; no model refit or model-selection uncertainty'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT/'reproduced')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(exist_ok=True, parents=True)
    if (output/'eye_transfer_final.joblib').exists():
        raise FileExistsError('Use a new --output-dir; existing final models are never overwritten')
    protocol = read_json(ROOT/'data/protocol.json')
    mapping = read_json(ROOT/'data/mapping.json')
    assert sha256(ROOT/'data/mapping.json') == protocol['mapping_sha256']
    assert sha256(ROOT/'source_model/eye_A_final.joblib') == protocol['source_model_sha256']
    for name, info in read_json(ROOT/'input_manifest.json').items():
        assert sha256(ROOT/name) == info['sha256'], name
    source = joblib.load(ROOT/'source_model/eye_A_final.joblib')
    assert source['format'] == 'eye-A-grouped-v1'
    assert source['representation'] == 'wmean'
    assert source['metadata']['evaluation_unique_rows'] == 673
    cohort = pd.read_csv(ROOT/'data/formulations.csv')
    payloads = read_json(ROOT/'data/payloads.json')
    assert list(cohort.formulation_id) == [p['formulation_id'] for p in payloads]
    vectors, coverage = zip(*(vectorize(p, source['feature_names'], mapping) for p in payloads))
    X = np.stack(vectors)
    y = cohort.label.to_numpy(dtype=int)
    assert len(y) == 16 and np.sum(y) == 11
    groups = np.array([feature_group(row) for row in X])
    assert len(np.unique(groups)) == 15
    transformed = source['pipeline'][:-1].transform(X)
    design = np.c_[transformed, np.ones(len(y))]
    estimator = source['pipeline'].steps[-1][1]
    anchor = np.r_[estimator.coef_.ravel(), estimator.intercept_]
    frozen = source['pipeline'].predict_proba(X)[:, 1]
    np.testing.assert_allclose(expit(design @ anchor), frozen, rtol=0, atol=1e-13)
    methods = {'source_centered_transfer': anchor, 'zero_centered_control': np.zeros_like(anchor)}
    predictions = {method: np.full(len(y), np.nan) for method in methods}
    folds = []
    (output/'fold_models').mkdir(exist_ok=True)
    for fold, group in enumerate(np.unique(groups), 1):
        test = np.flatnonzero(groups == group)
        train = np.flatnonzero(groups != group)
        assert not set(groups[train]) & set(groups[test])
        for method, center in methods.items():
            theta, optimization = fit(design[train], y[train], center, protocol)
            score = expit(design[test] @ theta)
            predictions[method][test] = score
            metadata = {'role': 'held_out_fold', 'method': method,
                        'train_ids': cohort.formulation_id.iloc[train].tolist(),
                        'test_ids': cohort.formulation_id.iloc[test].tolist(), 'group': group}
            bundle = make_bundle(source, theta, mapping, metadata)
            path = output/'fold_models'/f'{method}_{fold:02d}.joblib'
            joblib.dump(bundle, path, compress=3)
            loaded = joblib.load(path)
            np.testing.assert_allclose(loaded['pipeline'].predict_proba(X[test])[:, 1],
                                       score, rtol=0, atol=1e-12)
            folds.append({'fold': fold, 'method': method, 'model_file': str(path.relative_to(output)),
                          **metadata, 'optimization': optimization})
        print(f'Completed group {fold}/{len(np.unique(groups))}', flush=True)
    assert all(np.all(np.isfinite(scores)) for scores in predictions.values())
    result = cohort[['formulation_id', 'label']].copy()
    result['feature_group'] = groups
    result['frozen_source_score'] = frozen
    result['frozen_source_prediction'] = (frozen >= source['threshold']).astype(int)
    for method, scores in predictions.items():
        result[method+'_score'] = scores
        result[method+'_prediction'] = (scores >= .5).astype(int)
    result.to_csv(output/'predictions.csv', index=False, encoding='utf-8-sig')
    evaluation = {method: metrics(y, scores, .5) for method, scores in predictions.items()}
    evaluation['frozen_source'] = metrics(y, frozen, float(source['threshold']))
    evaluation['frozen_source_at_0.5'] = metrics(y, frozen, .5)
    write_json(output/'metrics.json', evaluation)
    pd.DataFrame([{'method': method, **{k: v for k, v in value.items() if k != 'confusion_matrix'},
                   'TN': value['confusion_matrix'][0][0], 'FP': value['confusion_matrix'][0][1],
                   'FN': value['confusion_matrix'][1][0], 'TP': value['confusion_matrix'][1][1]}
                  for method, value in evaluation.items()]).to_csv(output/'metrics.csv', index=False)
    write_json(output/'fold_log.json', folds)
    write_json(output/'coverage_audit.json', [dict(formulation_id=p['formulation_id'], **c)
                                            for p, c in zip(payloads, coverage)])
    np.savez_compressed(output/'features.npz', X=X, y=y, groups=groups,
                        formulation_ids=cohort.formulation_id.to_numpy(dtype=str))
    current = evaluation['source_centered_transfer']
    reference = protocol['reference_values_not_training_targets']
    agreement = (current['confusion_matrix'] == reference['confusion_matrix']
                 and round(current['ROC_AUC'], 3) == reference['ROC_AUC_rounded'])
    metadata = {'format': FORMAT, 'created_at': datetime.now(timezone.utc).isoformat(),
                'role': 'all_16_target_rows_refit_for_prediction', 'method': 'source_centered_transfer',
                'training_rows': len(y), 'feature_groups': len(np.unique(groups)),
                'class_counts': {'negative': int(np.sum(y == 0)), 'positive': int(np.sum(y == 1))},
                'n_features': X.shape[1], 'threshold': .5,
                'source_model_sha256': protocol['source_model_sha256'],
                'source_model_file': protocol['source_model_file'],
                'source_model_training_rows': 673, 'source_model_evaluation_unique_rows': 673,
                'mapping_sha256': protocol['mapping_sha256'], 'protocol_sha256': sha256(ROOT/'data/protocol.json'),
                'original_model_recovered': False, 'original_mapping_recovered': False,
                'rounded_reference_metrics_match': agreement,
                'oof_evaluation': current,
                'evaluation_scope': 'target-internal grouped OOF; not an independent test of final refit',
                'source_training_overlap': 'unresolved',
                'assumptions': protocol['reconstruction_assumptions'],
                'environment': {name: importlib.metadata.version(name) for name in
                                ['numpy', 'pandas', 'scikit-learn', 'scipy', 'joblib', 'rdkit', 'threadpoolctl']},
                'python': sys.version.split()[0]}
    theta, final_optimization = fit(design, y, anchor, protocol)
    metadata['final_optimization'] = final_optimization
    bundle = make_bundle(source, theta, mapping, metadata)
    joblib.dump(bundle, output/'eye_transfer_final.joblib', compress=3)
    write_json(output/'metadata.json', metadata)
    write_json(output/'feature_names.json', source['feature_names'])
    result = cohort[['formulation_id', 'label']].copy()
    result['score'] = bundle['pipeline'].predict_proba(X)[:, 1]
    result['prediction'] = (result.score >= .5).astype(int)
    result.to_csv(output/'refit_predictions_NOT_validation.csv', index=False)
    write_json(output/'bootstrap_ci.json', group_bootstrap(y, predictions['source_centered_transfer'], groups, protocol['bootstrap']))
    write_json(output/'protocol.json', protocol)
    assert sha256(ROOT/'source_model/eye_A_final.joblib') == protocol['source_model_sha256']
    print('Final model saved:', output/'eye_transfer_final.joblib', flush=True)
    print('Actual reconstructed OOF metrics:', current, flush=True)


if __name__ == '__main__':
    with threadpool_limits(limits=1):
        main()
