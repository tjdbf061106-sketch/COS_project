"""Recompute development selection and independently repeat the final full-data fit."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
import epa_harness as u
import finalize_model as f
import predict

ROOT = Path(__file__).resolve().parent


def main():
    cfg, identity = f.load_final_config()
    df = pd.read_csv(ROOT / 'input_snapshot.csv', low_memory=False)
    y = u.epa_labels(df.final_label)['A']
    X = np.load(ROOT / (cfg['representation'] + '.npy'))
    candidates = []
    for candidate in cfg['grid']:
        result = u.load_record(ROOT / 'final_development' / (candidate['candidate_id'] + '.json'), identity)
        assert result['candidate'] == candidate
        rows = pd.DataFrame(result['predictions'])
        assert len(rows) == 2019 and not rows.duplicated(['seed', 'row_index']).any()
        assert np.isfinite(rows.score).all()
        np.testing.assert_array_equal(rows.y_true, y[rows.row_index])
        aucs = []
        for seed, folds in cfg['splits'].items():
            for fold, part in enumerate(folds):
                subset = rows[(rows.seed == int(seed)) & (rows.fold == fold)]
                assert sorted(subset.row_index) == sorted(part['test'])
                aucs.append(roc_auc_score(subset.y_true, subset.score))
        np.testing.assert_allclose(aucs, result['fold_aucs'], rtol=0, atol=1e-12)
        np.testing.assert_allclose(np.mean(aucs), result['mean_auc'], rtol=0, atol=1e-12)
        candidates.append(result)
    best = max(candidates, key=lambda r: r['mean_auc'])
    rows = pd.DataFrame(best['predictions'])
    cutoff = u.threshold(rows.score.to_numpy(), rows.y_true.to_numpy())
    selected = json.loads((ROOT / 'selected_parameters.json').read_text(encoding='utf-8'))
    assert selected['candidate'] == best['candidate'] and selected['threshold'] == cutoff
    bundle = predict.load_bundle()
    assert bundle['metadata']['identity'] == identity
    assert bundle['threshold'] == cutoff
    assert bundle['representation'] == cfg['representation'] and bundle['model'] == cfg['model']
    params = bundle['pipeline'].named_steps['model'].get_params()
    for key, value in best['candidate']['params'].items():
        assert params[key] == value
    # Reproduce one selected-candidate development fold from raw training rows.
    seed = next(iter(cfg['splits']))
    part = cfg['splits'][seed][0]
    estimator = u.fit_weighted(u.build_estimator(cfg['model'], best['candidate']['params']), X[part['train']], y[part['train']])
    scores = u.predict_scores(estimator, X[part['test']], cfg['model'])
    expected = rows[(rows.seed == int(seed)) & (rows.fold == 0)].set_index('row_index').loc[part['test']]
    np.testing.assert_allclose(scores, expected.score, rtol=0, atol=1e-12)
    # Separate deterministic fit, not a new independent performance evaluation.
    rebuilt = u.fit_weighted(u.build_estimator(cfg['model'], best['candidate']['params']), X, y)
    expected_scores = u.predict_scores(rebuilt, X, cfg['model'])
    saved_scores = predict.predict_features(bundle, X)
    np.testing.assert_allclose(saved_scores.eye_A_score, expected_scores, rtol=0, atol=1e-12)
    np.testing.assert_array_equal(saved_scores.eye_A_prediction, expected_scores >= cutoff)
    f.require_binding(cfg)
    u.atomic_json(ROOT / 'final_reconstruction_verification.json', {
        'status': 'passed', 'identity': identity, 'candidate_metrics_recomputed': 20,
        'threshold_recomputed': True, 'development_fold_refits_checked': 1,
        'full_fit_reproduced_rows': 673, 'model_sha256': u.file_hash(ROOT / 'eye_A_final.joblib'),
        'independent_external_evaluation': False})
    print('FINAL SELECTION AND FULL FIT RECONSTRUCTED', flush=True)


if __name__ == '__main__':
    main()
