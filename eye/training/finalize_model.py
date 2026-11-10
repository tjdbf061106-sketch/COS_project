"""Tune/refit the selected family on all rows; development scores are not test scores."""
from __future__ import annotations
import os
for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
import epa_harness as u
from verify_comparison import OUTPUTS, verify_config

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8-sig'))


def audit_binding():
    prior, identity = verify_config(ROOT)
    audit = read('comparison_verification.json')
    assert audit['schema_version'] == 2 and audit['status'] == 'passed'
    assert audit['identity'] == identity, 'Audit identity mismatch'
    assert audit['config_sha256'] == u.file_hash(ROOT / 'comparison_config.json')
    assert audit['input_hashes'] == prior['input_hashes']
    assert audit['code_hashes'] == prior['code_hashes']
    assert set(audit['output_hashes']) == set(OUTPUTS)
    for name, expected in audit['output_hashes'].items():
        assert u.file_hash(ROOT / name) == expected, f'Audited output changed: {name}'
    selected = read('selected_model.json')
    assert selected['identity'] == identity, 'Selection identity mismatch'
    assert selected['model'] in prior['models'] and selected['representation'] in prior['representations']
    binding = {'comparison_identity': identity, 'config_sha256': audit['config_sha256'],
               'input_hashes': audit['input_hashes'], 'code_hashes': audit['code_hashes'],
               'output_hashes': audit['output_hashes'],
               'audit_sha256': u.file_hash(ROOT / 'comparison_verification.json'),
               'final_code_hashes': {name: u.file_hash(ROOT / name)
                                    for name in ('finalize_model.py', 'predict.py', 'verify_comparison.py')}}
    return prior, selected, binding


def require_binding(cfg):
    _, selected, binding = audit_binding()
    assert cfg['audit_binding'] == binding, 'Final configuration lineage changed'
    assert (cfg['model'], cfg['representation']) == (selected['model'], selected['representation'])


def load_final_config():
    record = read('final_config.json')
    cfg = u.load_record(ROOT / 'final_config.json', record['identity'])
    assert u.hash_json(cfg) == record['identity'], 'Final identity mismatch'
    require_binding(cfg)
    return cfg, record['identity']


def candidate_job(candidate):
    cfg, identity = load_final_config()
    assert candidate in cfg['grid']
    path = ROOT / 'final_development' / (candidate['candidate_id'] + '.json')
    if path.exists():
        return u.load_record(path, identity)
    df = pd.read_csv(ROOT / 'input_snapshot.csv', low_memory=False)
    X = np.load(ROOT / (cfg['representation'] + '.npy'))
    y = u.epa_labels(df.final_label)['A']
    records, aucs = [], []
    for seed, folds in cfg['splits'].items():
        for fold, part in enumerate(folds):
            tr, va = part['train'], part['test']
            est = u.fit_weighted(u.build_estimator(cfg['model'], candidate['params']), X[tr], y[tr])
            scores = u.predict_scores(est, X[va], cfg['model'])
            aucs.append(float(roc_auc_score(y[va], scores)))
            records.extend({'seed': int(seed), 'fold': fold, 'row_index': int(i), 'y_true': int(y[i]), 'score': float(s)} for i, s in zip(va, scores))
    result = {'candidate': candidate, 'mean_auc': float(np.mean(aucs)), 'fold_aucs': aucs, 'predictions': records}
    require_binding(cfg)
    u.save_record(path, identity, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.workers <= 6:
        raise ValueError('workers must be 1..6')
    prior, selected, binding = audit_binding()
    comparison = {'identity': binding['comparison_identity']}
    model, rep = selected['model'], selected['representation']
    cfg = {'comparison_identity': comparison['identity'], 'model': model, 'representation': rep,
           'grid': prior['grids'][model], 'splits': prior['splits'],
           'selection_rule': 'Highest mean development fold AUC, original grid order ties; inner-development OOF threshold gap/MCC rule.',
           'audit_binding': binding}
    identity = u.hash_json(cfg)
    if (ROOT / 'final_config.json').exists():
        u.load_record(ROOT / 'final_config.json', identity)
    else:
        u.save_record(ROOT / 'final_config.json', identity, cfg)
    (ROOT / 'final_development').mkdir(exist_ok=True)
    results = []
    require_binding(cfg)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(candidate_job, c) for c in cfg['grid']]
        for future in as_completed(futures):
            results.append(future.result())
            print(f'Final development candidates: {len(results)}/20', flush=True)
    order = {c['candidate_id']: i for i, c in enumerate(cfg['grid'])}
    results.sort(key=lambda r: order[r['candidate']['candidate_id']])
    best = max(results, key=lambda r: r['mean_auc'])
    calibration = pd.DataFrame(best['predictions'])
    assert len(calibration) == 2019 and calibration.row_index.nunique() == 673
    assert calibration.groupby(['seed', 'row_index']).size().eq(1).all()
    cutoff = float(u.threshold(calibration.score.to_numpy(), calibration.y_true.to_numpy()))
    calibration.to_csv(ROOT / 'development_oof_predictions.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame([{'candidate_id': r['candidate']['candidate_id'], **r['candidate']['params'], 'development_mean_auc': r['mean_auc']} for r in results]).to_csv(ROOT / 'hyperparameter_search.csv', index=False, encoding='utf-8-sig')
    require_binding(cfg)
    df = pd.read_csv(ROOT / 'input_snapshot.csv', low_memory=False)
    X = np.load(ROOT / (rep + '.npy'))
    y = u.epa_labels(df.final_label)['A']
    require_binding(cfg)
    est = u.fit_weighted(u.build_estimator(model, best['candidate']['params']), X, y)
    summary = pd.read_csv(ROOT / 'metrics_summary.csv')
    estimate = summary[(summary.model == model) & (summary.representation == rep) & (summary.subgroup == 'overall')].to_dict('records')
    metadata = {'identity': identity, 'comparison_identity': comparison['identity'],
                'model': model, 'representation': rep, 'target': 'EPA I/II vs III/IV',
                'training_rows': 673, 'evaluation_unique_rows': 673, 'n_features': 2265,
                'class_counts': {'negative': 548, 'positive': 125},
                'parameters': best['candidate']['params'], 'threshold': cutoff, 'comparison_operator': '>=',
                'nested_cv_estimate': estimate,
                'performance_note': 'Internal nested CV of each family. Winner chosen on these comparison results; winner performance is selection-conditioned, not independent external validation. Repeated predictions are not independent samples.',
                'interpretation': 'Scores are not externally calibrated irritation probabilities; negative EPA III/IV does not imply no irritation.'}
    bundle = {'format': 'eye-A-grouped-v1', 'pipeline': est, 'feature_names': read('feature_names.json'),
              'model': model, 'representation': rep, 'threshold': cutoff, 'metadata': metadata}
    joblib.dump(bundle, ROOT / 'eye_A_final.joblib', compress=3)
    scores = u.predict_scores(est, X, model)
    restored = joblib.load(ROOT / 'eye_A_final.joblib')
    np.testing.assert_allclose(scores, u.predict_scores(restored['pipeline'], X, model), rtol=0, atol=1e-12)
    assert int(est.named_steps['scaler'].n_samples_seen_) == 673 if 'scaler' in est.named_steps else True
    pd.DataFrame({'formulation_id': df.formulation_id, 'score': scores, 'prediction': (scores >= cutoff).astype(int)}).to_csv(ROOT / 'refit_reference_predictions.csv', index=False, encoding='utf-8-sig')
    u.atomic_json(ROOT / 'metadata.json', metadata)
    u.atomic_json(ROOT / 'selected_parameters.json', {'candidate': best['candidate'], 'threshold': cutoff, 'calibration_unique_rows': 673, 'calibration_predictions': 2019, 'development_only': True})
    require_binding(cfg)
    u.atomic_json(ROOT / 'final_verification.json', {
        'status': 'passed', 'identity': identity, 'full_refit_rows': 673,
        'serialization_predictions_equal': True, 'audited_lineage_rechecked': True,
        'coverage': 'Serialization round-trip and audited artifact lineage only.',
        'independent_model_or_performance_validation': False,
        'note': 'Does not independently verify development tuning, final-fit correctness, or generalization performance.'})
    print(json.dumps({'model': model, 'representation': rep, 'threshold': cutoff, 'parameters': best['candidate']['params']}), flush=True)


if __name__ == '__main__':
    main()
