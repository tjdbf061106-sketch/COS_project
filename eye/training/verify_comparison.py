"""Reconstruct held-out predictions and verify every candidate/split boundary."""
from __future__ import annotations
import os
for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[name] = '1'
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, confusion_matrix, matthews_corrcoef
import epa_harness as u
from run_comparison import INPUTS, MODELS, REPRESENTATIONS, SELECTION_RULE, SCOPE

ROOT = Path(__file__).resolve().parent
OUTPUTS = ('oof_predictions.csv', 'metrics_by_seed.csv', 'metrics_by_fold.csv',
           'metrics_summary.csv', 'ranking.csv', 'selected_model.json')
METRICS = ['sensitivity', 'specificity', 'MCC', 'ROC-AUC', 'gap', 'TN', 'FP', 'FN', 'TP']


def verify_config(root):
    record = json.loads((root / 'comparison_config.json').read_text(encoding='utf-8-sig'))
    cfg = u.load_record(root / 'comparison_config.json', record['identity'])
    assert u.hash_json(cfg) == record['identity'], 'Comparison identity mismatch'
    assert set(cfg['input_hashes']) == set((*INPUTS, 'source_config.json'))
    assert set(cfg['code_hashes']) == {'run_comparison.py', 'epa_harness.py'}
    for hashes in (cfg['input_hashes'], cfg['code_hashes']):
        for name, expected in hashes.items():
            assert u.file_hash(root / name) == expected, f'Artifact changed: {name}'
    return cfg, record['identity']


def metric_values(rows):
    assert len(rows), 'Empty metric subgroup'
    tn, fp, fn, tp = confusion_matrix(rows.y_true, rows.prediction, labels=[0, 1]).ravel()
    sens = float(tp / (tp + fn)) if tp + fn else float('nan')
    spec = float(tn / (tn + fp)) if tn + fp else float('nan')
    return {'sensitivity': sens, 'specificity': spec, 'gap': abs(sens - spec),
            'MCC': float(matthews_corrcoef(rows.y_true, rows.prediction)) if len(rows) else float('nan'),
            'ROC-AUC': float(roc_auc_score(rows.y_true, rows.score)) if rows.y_true.nunique() == 2 else float('nan'),
            'TN': int(tn), 'FP': int(fp), 'FN': int(fn), 'TP': int(tp)}


def compare_table(actual, expected, keys):
    assert set(actual.columns) == set(expected.columns), 'Table columns mismatch'
    assert not actual.duplicated(keys).any(), f'Duplicate keys: {keys}'
    assert not expected.duplicated(keys).any()
    a = actual.set_index(keys).sort_index()
    e = expected.set_index(keys).sort_index()
    pd.testing.assert_index_equal(a.index, e.index, exact=False)
    for column in e:
        if pd.api.types.is_numeric_dtype(e[column]):
            np.testing.assert_allclose(a[column], e[column], rtol=0, atol=1e-12, equal_nan=True,
                                       err_msg=column)
        else:
            np.testing.assert_array_equal(a[column], e[column], err_msg=column)


def reconstruct_tables(oof, df, cfg):
    assert cfg['models'] == list(MODELS) and cfg['representations'] == list(REPRESENTATIONS)
    assert len(set(cfg['seeds'])) == len(cfg['seeds'])
    keys = ['model', 'representation', 'seed', 'fold', 'row_index']
    expected = pd.DataFrame([
        (model, rep, seed, fold, i)
        for model in MODELS for rep in REPRESENTATIONS for seed in cfg['seeds']
        for fold, part in enumerate(cfg['splits'][str(seed)]) for i in part['test']
    ], columns=keys)
    compare_table(oof[keys], expected, keys)
    assert not oof.duplicated(['model', 'representation', 'seed', 'row_index']).any()
    for _, block in oof.groupby(['model', 'representation', 'seed']):
        assert sorted(block.row_index.tolist()) == list(range(len(df)))
    idx = oof.row_index.to_numpy()
    assert np.issubdtype(idx.dtype, np.integer)
    for column, values in {
        'y_true': (df.final_label.to_numpy() <= 2).astype(int),
        'formulation_id': df.formulation_id.to_numpy(),
        'original_role': df.evaluation_role.to_numpy(),
        'components_used': df.n_components_used.to_numpy(),
    }.items():
        np.testing.assert_array_equal(oof[column], values[idx], err_msg=column)
    assert oof.label.eq('A').all()
    assert np.isfinite(oof[['score', 'threshold']].to_numpy()).all()
    np.testing.assert_array_equal(oof.prediction, (oof.score >= oof.threshold).astype(int))
    seeds, folds = [], []
    for (model, rep, seed), block in oof.groupby(['model', 'representation', 'seed']):
        base = {'label': 'A', 'model': model, 'representation': rep, 'seed': seed}
        masks = {'overall': np.ones(len(block), dtype=bool), 'single': block.components_used.eq(1),
                 'multi': block.components_used.gt(1), 'original606': block.original_role.eq('existing_evaluation_pool'),
                 'added67': block.original_role.eq('augmentation_train_only')}
        for subgroup, mask in masks.items():
            subset = block.loc[mask]
            seeds.append({**base, 'subgroup': subgroup, 'rows': len(subset), **metric_values(subset)})
        for fold, subset in block.groupby('fold'):
            assert subset.threshold.nunique() == 1
            folds.append({**base, 'fold': fold, 'rows': len(subset),
                          'threshold': subset.threshold.iloc[0], **metric_values(subset)})
    seeds = pd.DataFrame(seeds)
    summary = seeds.groupby(['label', 'model', 'representation', 'subgroup'])[METRICS].agg(['mean', 'std', 'min', 'max'])
    summary.columns = ['_'.join(c) for c in summary.columns]
    return seeds, pd.DataFrame(folds), summary.reset_index()


def ranked_summary(summary):
    ranking = summary[summary.subgroup.eq('overall')].copy()
    ranking['_model_order'] = ranking.model.map(dict(zip(MODELS, range(len(MODELS)))))
    ranking['_rep_order'] = ranking.representation.map(dict(zip(REPRESENTATIONS, range(len(REPRESENTATIONS)))))
    ranking = ranking.sort_values(['MCC_mean', 'ROC-AUC_mean', 'gap_mean', '_model_order', '_rep_order'],
                                 ascending=[False, False, True, True, True]).drop(columns=['_model_order', '_rep_order'])
    ranking.insert(0, 'rank', range(1, len(ranking) + 1))
    ranking['scope'] = SCOPE
    return ranking


def verify_tables(root, oof, df, cfg, identity):
    seeds, folds, summary = reconstruct_tables(oof, df, cfg)
    ranking = ranked_summary(summary)
    for name, expected, keys in [
        ('metrics_by_seed.csv', seeds, ['label', 'model', 'representation', 'seed', 'subgroup']),
        ('metrics_by_fold.csv', folds, ['label', 'model', 'representation', 'seed', 'fold']),
        ('metrics_summary.csv', summary, ['label', 'model', 'representation', 'subgroup']),
        ('ranking.csv', ranking, ['rank']),
    ]:
        compare_table(pd.read_csv(root / name), expected, keys)
    winner = ranking.iloc[0]
    expected = {'identity': identity, 'model': winner.model, 'representation': winner.representation,
                'selection_rule': SELECTION_RULE,
                'selection_reason': 'Rank 1 under the declared deterministic exploratory ranking.',
                'mean_overall_MCC': float(winner.MCC_mean), 'mean_overall_ROC_AUC': float(winner['ROC-AUC_mean']),
                'mean_overall_gap': float(winner.gap_mean), 'scope': SCOPE, 'final_refit_performed': False}
    selected = json.loads((root / 'selected_model.json').read_text(encoding='utf-8-sig'))
    assert set(selected) == set(expected)
    for key, value in expected.items():
        if isinstance(value, float):
            np.testing.assert_allclose(selected[key], value, rtol=0, atol=1e-12, equal_nan=False)
        else:
            assert selected[key] == value, f'Selection mismatch: {key}'


def main():
    cfg, identity = verify_config(ROOT)
    initial_hashes = {name: u.file_hash(ROOT / name) for name in (*OUTPUTS, 'comparison_config.json')}
    source_record = json.loads((ROOT / 'source_config.json').read_text(encoding='utf-8'))
    source = u.load_record(ROOT / 'source_config.json', source_record['identity'])
    for name in ('input_snapshot.csv', 'wmean.npy', 'max.npy', 'feature_names.json', 'epa_harness.py'):
        assert u.file_hash(ROOT / name) == source['artifact_hashes'][name]
    groups = np.asarray(cfg['groups'])
    df = pd.read_csv(ROOT / 'input_snapshot.csv', low_memory=False)
    y = (df.final_label.to_numpy() <= 2).astype(int)
    assert len(df) == 673 and np.bincount(y).tolist() == [548, 125]
    oof = pd.read_csv(ROOT / 'oof_predictions.csv')
    verify_tables(ROOT, oof, df, cfg, identity)
    assert len(oof) == 673 * 3 * 6
    count = 0
    for rep in ('wmean', 'max'):
        X = np.load(ROOT / (rep + '.npy'))
        for model in ('lr', 'rf', 'xgb'):
            for seed in cfg['seeds']:
                covered = []
                for fold, part in enumerate(cfg['splits'][str(seed)]):
                    path = ROOT / 'results' / rep / model / str(seed) / f'fold-{fold}'
                    result = u.load_record(path / 'outer.json', identity)
                    tr, te = np.asarray(part['train']), np.asarray(part['test'])
                    assert result['test'] == te.tolist() and result['train_rows'] == tr.tolist()
                    assert not set(groups[tr]) & set(groups[te])
                    assert sorted(np.r_[tr, te]) == list(range(673))
                    valid_rows = []
                    for inner in part['inner']:
                        a, b = np.asarray(inner['train']), np.asarray(inner['validation'])
                        assert set(a) | set(b) == set(tr) and not set(a) & set(b)
                        assert not set(groups[a]) & set(groups[b])
                        assert not set(groups[np.r_[a, b]]) & set(groups[te])
                        valid_rows.extend(b.tolist())
                    assert sorted(valid_rows) == sorted(tr.tolist())
                    candidates = []
                    for candidate in cfg['grids'][model]:
                        value = u.load_record(path / 'candidates' / (candidate['candidate_id'] + '.json'), identity)
                        assert value['candidate'] == candidate
                        idx = np.asarray(value['calibration_rows'])
                        scores = np.asarray(value['calibration_scores'])
                        assert sorted(idx.tolist()) == sorted(tr.tolist()) and np.isfinite(scores).all()
                        lookup = dict(zip(idx.tolist(), scores.tolist()))
                        aucs = [roc_auc_score(y[p['validation']], [lookup[i] for i in p['validation']]) for p in part['inner']]
                        np.testing.assert_allclose(aucs, value['fold_aucs'], rtol=0, atol=1e-12)
                        np.testing.assert_allclose(np.mean(aucs), value['mean_auc'], rtol=0, atol=1e-12)
                        candidates.append(value)
                    best = max(candidates, key=lambda c: c['mean_auc'])
                    assert best['candidate'] == result['selected_candidate']
                    cutoff = u.threshold(best['calibration_scores'], y[best['calibration_rows']])
                    assert cutoff == result['threshold']
                    est = joblib.load(path / 'estimator.joblib')
                    if 'scaler' in est.named_steps:
                        imputed = np.nan_to_num(X[tr], nan=0.0)
                        np.testing.assert_allclose(est.named_steps['scaler'].mean_, imputed.mean(axis=0), rtol=1e-12, atol=1e-10)
                        assert int(est.named_steps['scaler'].n_samples_seen_) == len(tr)
                    rebuilt = u.predict_scores(est, X[te], model)
                    np.testing.assert_allclose(rebuilt, result['scores'], rtol=0, atol=1e-12)
                    np.testing.assert_array_equal(y[te], result['y_true'])
                    np.testing.assert_array_equal(rebuilt >= cutoff, result['predictions'])
                    rows = oof[(oof.representation == rep) & (oof.model == model) & (oof.seed == seed) & (oof.fold == fold)].set_index('row_index').loc[te]
                    np.testing.assert_allclose(rows.score, rebuilt, rtol=0, atol=1e-12)
                    np.testing.assert_allclose(rows.threshold, cutoff, rtol=0, atol=1e-12)
                    np.testing.assert_array_equal(rows.prediction, rebuilt >= cutoff)
                    covered.extend(te.tolist())
                    count += 1
                assert sorted(covered) == list(range(673))
                rows = oof[(oof.representation == rep) & (oof.model == model) & (oof.seed == seed)]
                assert rows.row_index.nunique() == 673
                assert df.evaluation_role.iloc[rows.row_index].value_counts().to_dict() == {'existing_evaluation_pool': 606, 'augmentation_train_only': 67}
                print(f'Verified {rep}/{model}/{seed}', flush=True)
    verify_config(ROOT)
    assert initial_hashes == {name: u.file_hash(ROOT / name) for name in initial_hashes}, 'Artifacts changed during audit'
    u.atomic_json(ROOT / 'comparison_verification.json', {'status': 'passed', 'identity': identity, 'schema_version': 2,
                  'config_sha256': initial_hashes['comparison_config.json'],
                  'input_hashes': cfg['input_hashes'], 'code_hashes': cfg['code_hashes'],
                  'output_hashes': {name: initial_hashes[name] for name in OUTPUTS},
                  'outer_folds': count, 'candidate_records': count * 20, 'oof_predictions': len(oof),
                  'unique_rows_per_combination_seed': 673, 'added_rows_evaluated': 67,
                  'heldout_scores_reconstructed': True, 'group_disjointness_verified': True,
                  'inner_only_thresholds_verified': True, 'metrics_recomputed': True,
                  'note': 'Audit verifies artifacts and code boundaries; it is not independent external validation.'})
    print('COMPARISON VERIFICATION PASSED', flush=True)


if __name__ == '__main__':
    main()
