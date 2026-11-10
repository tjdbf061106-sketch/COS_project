"""Exploratory EPA A comparison on all 673 rows; no final model refit."""
from __future__ import annotations

import os
for _name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_name] = '1'

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, matthews_corrcoef, roc_auc_score
import epa_harness as u

ROOT = Path(__file__).resolve().parent
SEEDS = (42, 202, 777)
MODELS = ('lr', 'rf', 'xgb')
REPRESENTATIONS = ('wmean', 'max')
INPUTS = ('input_snapshot.csv', 'wmean.npy', 'max.npy', 'feature_names.json')
CONFIG = ROOT / 'comparison_config.json'
CACHE = None
SELECTION_RULE = ('Mean overall seedwise MCC descending, then ROC-AUC descending, then '
                  'sensitivity-specificity gap ascending; exact ties use lr/rf/xgb and wmean/max order.')
SCOPE = ('Exploratory model/representation comparison, not unbiased performance of winner-selection. '
         'Repeated seeds are not independent cohorts. No final refit is performed here.')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def verify_hashes(hashes):
    for name, expected in hashes.items():
        require(u.file_hash(ROOT / name) == expected, f'Artifact changed: {name}')


def prepare():
    envelope = read_json(ROOT / 'source_config.json')
    old = u.load_record(ROOT / 'source_config.json', envelope['identity'])
    require(u.hash_json(old) == envelope['identity'], 'Invalid source identity')
    verify_hashes({n: old['artifact_hashes'][n] for n in (*INPUTS, 'epa_harness.py')})
    df = pd.read_csv(ROOT / 'input_snapshot.csv', low_memory=False)
    require(len(df) == 673 and df.formulation_id.notna().all() and df.formulation_id.is_unique,
            'Expected 673 unique formulation rows')
    y = u.epa_labels(df.final_label)['A']
    require(np.bincount(y).tolist() == [548, 125], 'Unexpected EPA A class counts')
    names = read_json(ROOT / 'feature_names.json')
    require(len(names) == 2265 and len(set(names)) == 2265, 'Invalid feature names')
    groups = np.asarray(old['groups'])
    require(groups.shape == (673,) and len(set(groups)) == 388 and not pd.isna(groups).any(),
            'Expected original 388 conservative groups')
    for column in ('comp_group_id', 'split_group_id'):
        require(df[column].notna().all() and df[column].astype(str).str.strip().ne('').all(),
                f'Missing group IDs: {column}')
        counts = pd.DataFrame({'key': df[column], 'group': groups}).groupby('key')['group'].nunique()
        require(counts.eq(1).all(), f'Group identifier crosses conservative groups: {column}')
    for rep in REPRESENTATIONS:
        matrix = np.load(ROOT / f'{rep}.npy', allow_pickle=False)
        require(matrix.shape == (673, 2265) and not np.isinf(matrix).any(), f'Invalid {rep} matrix')
        values = np.round(np.nan_to_num(matrix, nan=0.0), 6)
        values[values == 0] = 0
        seen = {}
        for row, group in zip(values, groups):
            key = row.tobytes()
            require(key not in seen or seen[key] == group, f'{rep} vector collision crosses groups')
            seen[key] = group
    roles = df.evaluation_role.value_counts().to_dict()
    require(roles == {'existing_evaluation_pool': 606, 'augmentation_train_only': 67}, 'Unexpected original cohorts')
    counts = pd.to_numeric(df.n_components_used, errors='raise').to_numpy()
    require(np.isfinite(counts).all() and (counts >= 1).all() and (counts == np.floor(counts)).all(),
            'Invalid component counts')
    grids = {m: old['grids'][m] for m in MODELS}
    for model, grid in grids.items():
        require(len(grid) == 20 and len({c['candidate_id'] for c in grid}) == 20, f'Invalid {model} grid')
        require(all(Path(c['candidate_id']).name == c['candidate_id'] for c in grid), 'Unsafe candidate ID')
    splits = {str(s): u.nested_splits(df.final_label.to_numpy(), groups, s) for s in SEEDS}
    for folds in splits.values():
        require(len(folds) == 5 and sorted(i for f in folds for i in f['test']) == list(range(673)),
                'Outer folds do not cover all rows once')
        for fold in folds:
            require(sorted(fold['train'] + fold['test']) == list(range(673)), 'Incomplete outer partition')
            require(len(fold['inner']) == 3, 'Expected three inner folds')
            require(sorted(i for p in fold['inner'] for i in p['validation']) == sorted(fold['train']),
                    'Inner OOF coverage mismatch')
            for part in fold['inner']:
                require(sorted(part['train'] + part['validation']) == sorted(fold['train']),
                        'Inner partition escapes outer training rows')
    cfg = {
        'protocol': 'all-673-EPA-A-model-aggregation-comparison-v1', 'label': 'A',
        'rows': 673, 'evaluation_rows': 673, 'augmentation_train_only': 0,
        'models': list(MODELS), 'representations': list(REPRESENTATIONS), 'seeds': list(SEEDS),
        'groups': groups.tolist(), 'splits': splits, 'grids': grids,
        'outer_jobs': 90, 'candidate_count': 20, 'expected_total_fits': 5490,
        'source_identity': envelope['identity'], 'source_hashes': old.get('source_hashes', {}),
        'input_hashes': {n: u.file_hash(ROOT / n) for n in (*INPUTS, 'source_config.json')},
        'code_hashes': {n: u.file_hash(ROOT / n) for n in ('run_comparison.py', 'epa_harness.py')},
        'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                        'packages': {n: importlib.metadata.version(n) for n in
                                     ('numpy', 'pandas', 'scipy', 'scikit-learn', 'xgboost', 'joblib', 'threadpoolctl')}},
        'estimator_seed': 42,
        'candidate_selection': 'Maximum mean inner fold ROC-AUC; exact ties use original grid order.',
        'threshold_selection': 'Selected candidate inner OOF only, using epa_harness.threshold.',
        'preprocessing': 'Constant-zero imputation and model-specific scaling fit on each training split; weights recomputed per fit.',
        'selection_rule': SELECTION_RULE, 'scope': SCOPE,
    }
    identity = u.hash_json(cfg)
    u.save_record(CONFIG, identity, cfg)
    return cfg, identity


def cached_data(identity):
    global CACHE
    if CACHE is None:
        cfg = u.load_record(CONFIG, identity)
        require(u.hash_json(cfg) == identity, 'Comparison identity mismatch')
        verify_hashes({**cfg['input_hashes'], **cfg['code_hashes']})
        df = pd.read_csv(ROOT / 'input_snapshot.csv', low_memory=False)
        CACHE = (identity, cfg, df, u.epa_labels(df.final_label)['A'],
                 {r: np.load(ROOT / f'{r}.npy', mmap_mode='r', allow_pickle=False) for r in REPRESENTATIONS})
    require(CACHE[0] == identity, 'Worker identity changed')
    return CACHE[1:]


def jobs():
    # Interleave families/representations while scheduling the expensive RF fits first.
    return [dict(model=m, representation=r, seed=s, fold=f)
            for s in SEEDS for f in range(5) for m in ('rf', 'lr', 'xgb') for r in REPRESENTATIONS]


def job_path(job):
    return ROOT / 'results' / job['representation'] / job['model'] / str(job['seed']) / f"fold-{job['fold']}"


def candidate_record(path, identity, candidate, split, y):
    result = u.load_record(path, identity)
    require(result['candidate'] == candidate and result['calibration_rows'] == split['train'],
            f'Candidate metadata mismatch: {path}')
    scores = np.asarray(result['calibration_scores'])
    require(scores.shape == (len(split['train']),) and np.isfinite(scores).all(), 'Invalid calibration scores')
    lookup = dict(zip(split['train'], scores))
    aucs = [float(roc_auc_score(y[p['validation']], [lookup[i] for i in p['validation']])) for p in split['inner']]
    require(result['fold_aucs'] == aucs and result['mean_auc'] == float(np.mean(aucs)), 'Candidate AUC mismatch')
    return result


def completed_record(job, cfg, identity, y):
    path = job_path(job)
    result = u.load_record(path / 'outer.json', identity)
    split = cfg['splits'][str(job['seed'])][job['fold']]
    require(all(result[k] == v for k, v in job.items()), 'Outer job metadata mismatch')
    require(result['test'] == split['test'] and result['train_rows'] == split['train'], 'Outer scope mismatch')
    require(result['y_true'] == y[split['test']].tolist(), 'Outer targets mismatch')
    candidates = [candidate_record(path / 'candidates' / (c['candidate_id'] + '.json'), identity, c, split, y)
                  for c in cfg['grids'][job['model']]]
    best = max(candidates, key=lambda c: c['mean_auc'])
    cutoff = float(u.threshold(best['calibration_scores'], y[split['train']]))
    require(result['selected_candidate'] == best['candidate'] and result['threshold'] == cutoff,
            'Outer selection/threshold mismatch')
    scores = np.asarray(result['scores'])
    require(scores.shape == (len(split['test']),) and np.isfinite(scores).all(), 'Invalid outer scores')
    require(result['predictions'] == (scores >= cutoff).astype(int).tolist(), 'Outer threshold application mismatch')
    require(result['candidates_evaluated'] == 20, 'Incomplete candidate search')
    require(u.file_hash(path / 'estimator.joblib') == result['estimator_sha256'], 'Estimator checksum mismatch')
    return result


def run_fold(job, identity):
    cfg, df, y, matrices = cached_data(identity)
    path = job_path(job)
    if (path / 'outer.json').exists():
        return completed_record(job, cfg, identity, y)
    started = time.perf_counter()
    split = cfg['splits'][str(job['seed'])][job['fold']]
    matrix, model = matrices[job['representation']], job['model']
    candidates = []
    for candidate in cfg['grids'][model]:
        cp = path / 'candidates' / (candidate['candidate_id'] + '.json')
        if not cp.exists():
            scores = np.full(len(df), np.nan)
            aucs = []
            for part in split['inner']:
                tr, va = part['train'], part['validation']
                estimator = u.fit_weighted(u.build_estimator(model, candidate['params']), matrix[tr], y[tr])
                predicted = u.predict_scores(estimator, matrix[va], model)
                scores[va] = predicted
                aucs.append(float(roc_auc_score(y[va], predicted)))
            require(np.isfinite(scores[split['train']]).all(), 'Missing inner predictions')
            u.save_record(cp, identity, {'candidate': candidate, 'mean_auc': float(np.mean(aucs)),
                                        'fold_aucs': aucs, 'calibration_rows': split['train'],
                                        'calibration_scores': scores[split['train']].tolist()})
        candidates.append(candidate_record(cp, identity, candidate, split, y))
        print(f"{job} candidate {len(candidates)}/20", flush=True)
    best = max(candidates, key=lambda c: c['mean_auc'])
    cutoff = float(u.threshold(best['calibration_scores'], y[split['train']]))
    tr, te = split['train'], split['test']
    estimator = u.fit_weighted(u.build_estimator(model, best['candidate']['params']), matrix[tr], y[tr])
    scores = u.predict_scores(estimator, matrix[te], model)
    # An uncommitted estimator from an interrupted job is safe to replace. Completed jobs are never rewritten.
    temporary = path / 'estimator.joblib.tmp'
    joblib.dump(estimator, temporary, compress=3)
    os.replace(temporary, path / 'estimator.joblib')
    result = {**job, 'label': 'A', 'test': te, 'train_rows': tr, 'calibration_rows': tr,
              'y_true': y[te].tolist(), 'scores': scores.tolist(),
              'predictions': (scores >= cutoff).astype(int).tolist(), 'threshold': cutoff,
              'selected_candidate': best['candidate'], 'candidates_evaluated': len(candidates),
              'estimator_sha256': u.file_hash(path / 'estimator.joblib'),
              'seconds': time.perf_counter() - started, 'completed_at': datetime.now(timezone.utc).isoformat()}
    u.save_record(path / 'outer.json', identity, result)
    return result


def metrics(y, score, pred):
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    sens = float(tp / (tp + fn)) if tp + fn else float('nan')
    spec = float(tn / (tn + fp)) if tn + fp else float('nan')
    return {'sensitivity': sens, 'specificity': spec, 'gap': abs(sens - spec),
            'MCC': float(matthews_corrcoef(y, pred)) if len(y) else float('nan'),
            'ROC-AUC': float(roc_auc_score(y, score)) if len(np.unique(y)) == 2 else float('nan'),
            'TN': int(tn), 'FP': int(fp), 'FN': int(fn), 'TP': int(tp)}


def csv(name, frame):
    target = ROOT / name
    temporary = target.with_name(target.name + '.tmp')
    frame.to_csv(temporary, index=False, encoding='utf-8-sig')
    os.replace(temporary, target)


def summarize(cfg, identity):
    require(all((job_path(j) / 'outer.json').exists() for j in jobs()), 'All 90 outer folds must finish before summary')
    _, df, y, _ = cached_data(identity)
    rows, folds = [], []
    for job in jobs():
        result = completed_record(job, cfg, identity, y)
        folds.append({**job, 'label': 'A', 'rows': len(result['test']), 'threshold': result['threshold'],
                      **metrics(result['y_true'], result['scores'], result['predictions'])})
        for i, score, pred in zip(result['test'], result['scores'], result['predictions']):
            rows.append({**job, 'label': 'A', 'row_index': i, 'formulation_id': df.formulation_id.iloc[i],
                         'y_true': int(y[i]), 'score': score, 'prediction': pred, 'threshold': result['threshold'],
                         'components_used': int(df.n_components_used.iloc[i]), 'original_role': df.evaluation_role.iloc[i]})
    oof = pd.DataFrame(rows).sort_values(['model', 'representation', 'seed', 'row_index'])
    require(len(oof) == 12114, 'Expected 12114 OOF predictions')
    seed_rows = []
    for (model, rep, seed), block in oof.groupby(['model', 'representation', 'seed'], sort=False):
        require(block.row_index.tolist() == list(range(673)), 'OOF rows must occur exactly once per combination and seed')
        masks = {'overall': np.ones(len(block), dtype=bool), 'single': block.components_used.eq(1),
                 'multi': block.components_used.gt(1), 'original606': block.original_role.eq('existing_evaluation_pool'),
                 'added67': block.original_role.eq('augmentation_train_only')}
        for subgroup, mask in masks.items():
            subset = block.loc[mask]
            seed_rows.append({'label': 'A', 'model': model, 'representation': rep, 'seed': seed,
                              'subgroup': subgroup, 'rows': len(subset),
                              **metrics(subset.y_true.to_numpy(), subset.score.to_numpy(), subset.prediction.to_numpy())})
    seed_metrics = pd.DataFrame(seed_rows)
    columns = ['sensitivity', 'specificity', 'MCC', 'ROC-AUC', 'gap', 'TN', 'FP', 'FN', 'TP']
    summary = seed_metrics.groupby(['label', 'model', 'representation', 'subgroup'])[columns].agg(['mean', 'std', 'min', 'max'])
    summary.columns = ['_'.join(c) for c in summary.columns]
    summary = summary.reset_index()
    ranking = summary[summary.subgroup.eq('overall')].copy()
    ranking['_model_order'] = ranking.model.map({m: i for i, m in enumerate(MODELS)})
    ranking['_rep_order'] = ranking.representation.map({r: i for i, r in enumerate(REPRESENTATIONS)})
    ranking = ranking.sort_values(['MCC_mean', 'ROC-AUC_mean', 'gap_mean', '_model_order', '_rep_order'],
                                 ascending=[False, False, True, True, True]).drop(columns=['_model_order', '_rep_order'])
    ranking.insert(0, 'rank', range(1, len(ranking) + 1))
    ranking['scope'] = SCOPE
    for name, frame in [('oof_predictions.csv', oof), ('metrics_by_seed.csv', seed_metrics),
                        ('metrics_by_fold.csv', pd.DataFrame(folds)), ('metrics_summary.csv', summary), ('ranking.csv', ranking)]:
        csv(name, frame)
    winner = ranking.iloc[0]
    u.atomic_json(ROOT / 'selected_model.json', {'identity': identity, 'model': winner.model,
                  'representation': winner.representation, 'selection_rule': SELECTION_RULE,
                  'selection_reason': 'Rank 1 under the declared deterministic exploratory ranking.',
                  'mean_overall_MCC': float(winner.MCC_mean), 'mean_overall_ROC_AUC': float(winner['ROC-AUC_mean']),
                  'mean_overall_gap': float(winner.gap_mean), 'scope': SCOPE, 'final_refit_performed': False})


@contextmanager
def exclusive_run():
    # OS advisory lock is released after crashes, permitting safe checkpoint resume.
    with (ROOT / '.comparison.lock').open('a+b') as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def status(identity, state, completed, started, **extra):
    u.atomic_json(ROOT / 'status.json', {'identity': identity, 'status': state, 'completed_outer': completed,
                  'total_outer': 90, 'pid': os.getpid(), 'elapsed_seconds': time.monotonic() - started,
                  'updated_at': datetime.now(timezone.utc).isoformat(), **extra})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, choices=range(1, 7), default=4)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--prepare-only', action='store_true')
    modes.add_argument('--summarize-only', action='store_true')
    args = parser.parse_args()
    with exclusive_run():
        cfg, identity = prepare()
        started, completed = time.monotonic(), 0
        try:
            _, _, y, _ = cached_data(identity)
            pending = []
            for job in jobs():
                if (job_path(job) / 'outer.json').exists():
                    completed_record(job, cfg, identity, y)
                    completed += 1
                else:
                    pending.append(job)
            status(identity, 'prepared' if args.prepare_only else 'running', completed, started)
            print(f'Identity {identity}; completed outer folds {completed}/90; 20 candidates/fold', flush=True)
            if args.prepare_only:
                return
            if not args.summarize_only:
                with ProcessPoolExecutor(max_workers=args.workers) as pool:
                    futures = [pool.submit(run_fold, job, identity) for job in pending]
                    for future in as_completed(futures):
                        future.result()
                        completed += 1
                        status(identity, 'running', completed, started)
                        print(f'Outer folds completed: {completed}/90', flush=True)
            require(completed == 90, f'Only {completed}/90 completed; summary refused')
            summarize(cfg, identity)
            status(identity, 'compared_pending_verification', completed, started, scope=SCOPE)
        except BaseException as exc:
            status(identity, 'failed', completed, started, error=repr(exc))
            raise


if __name__ == '__main__':
    main()
