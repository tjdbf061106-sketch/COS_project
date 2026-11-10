"""Synthetic artifact guard tests; no training or production artifacts are touched."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import epa_harness as u
import verify_comparison as v
import finalize_model as f


class ArtifactGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.df = pd.DataFrame({
            'formulation_id': [f'f{i}' for i in range(8)],
            'final_label': [1, 3] * 4,
            'evaluation_role': ['existing_evaluation_pool'] * 4 + ['augmentation_train_only'] * 4,
            'n_components_used': [1, 1, 2, 2] * 2,
        })
        self.df.to_csv(self.root / 'input_snapshot.csv', index=False)
        for name in ('wmean.npy', 'max.npy'):
            np.save(self.root / name, np.zeros((8, 2)))
        for name in ('feature_names.json', 'source_config.json', 'run_comparison.py',
                     'epa_harness.py', 'finalize_model.py', 'predict.py', 'verify_comparison.py'):
            (self.root / name).write_text('{}', encoding='utf-8')
        self.cfg = {
            'models': list(v.MODELS), 'representations': list(v.REPRESENTATIONS), 'seeds': [42, 202, 777],
            'splits': {str(seed): [{'test': list(range(4)), 'train': list(range(4, 8))},
                                  {'test': list(range(4, 8)), 'train': list(range(4))}]
                       for seed in (42, 202, 777)},
            'grids': {model: [{'candidate_id': str(i), 'params': {}} for i in range(20)] for model in v.MODELS},
            'input_hashes': {name: u.file_hash(self.root / name) for name in (*v.INPUTS, 'source_config.json')},
            'code_hashes': {name: u.file_hash(self.root / name) for name in ('run_comparison.py', 'epa_harness.py')},
        }
        self.identity = u.hash_json(self.cfg)
        u.save_record(self.root / 'comparison_config.json', self.identity, self.cfg)
        records = []
        for model in v.MODELS:
            for rep in v.REPRESENTATIONS:
                for seed in self.cfg['seeds']:
                    for i, row in self.df.iterrows():
                        target = int(row.final_label <= 2)
                        records.append({'label': 'A', 'model': model, 'representation': rep, 'seed': seed,
                                        'fold': i // 4, 'row_index': i, 'formulation_id': row.formulation_id,
                                        'y_true': target, 'score': 0.8 if target else 0.2, 'prediction': target,
                                        'threshold': 0.5, 'components_used': row.n_components_used,
                                        'original_role': row.evaluation_role})
        self.oof = pd.DataFrame(records)
        seeds, folds, summary = v.reconstruct_tables(self.oof, self.df, self.cfg)
        ranking = v.ranked_summary(summary)
        self.tables = {
            'metrics_by_seed.csv': (seeds, ['label', 'model', 'representation', 'seed', 'subgroup']),
            'metrics_by_fold.csv': (folds, ['label', 'model', 'representation', 'seed', 'fold']),
            'metrics_summary.csv': (summary, ['label', 'model', 'representation', 'subgroup']),
            'ranking.csv': (ranking, ['rank']),
        }
        for name, frame in [('oof_predictions.csv', self.oof), ('metrics_by_seed.csv', seeds),
                            ('metrics_by_fold.csv', folds), ('metrics_summary.csv', summary), ('ranking.csv', ranking)]:
            frame.to_csv(self.root / name, index=False)
        self.selected = {'identity': self.identity, 'model': 'lr', 'representation': 'wmean',
                         'selection_rule': v.SELECTION_RULE,
                         'selection_reason': 'Rank 1 under the declared deterministic exploratory ranking.',
                         'mean_overall_MCC': 1.0, 'mean_overall_ROC_AUC': 1.0, 'mean_overall_gap': 0.0,
                         'scope': v.SCOPE, 'final_refit_performed': False}
        u.atomic_json(self.root / 'selected_model.json', self.selected)
        u.atomic_json(self.root / 'comparison_verification.json', {
            'schema_version': 2, 'status': 'passed', 'identity': self.identity,
            'config_sha256': u.file_hash(self.root / 'comparison_config.json'),
            'input_hashes': self.cfg['input_hashes'], 'code_hashes': self.cfg['code_hashes'],
            'output_hashes': {name: u.file_hash(self.root / name) for name in v.OUTPUTS},
        })

    def verify(self, oof=None):
        v.verify_tables(self.root, self.oof if oof is None else oof, self.df, self.cfg, self.identity)

    def test_exact_ties(self):
        self.verify()
        ranking = pd.read_csv(self.root / 'ranking.csv')
        self.assertEqual(list(zip(ranking.model, ranking.representation)),
                         [(m, r) for m in v.MODELS for r in v.REPRESENTATIONS])
        with patch.object(f, 'ROOT', self.root):
            f.audit_binding()

    def test_legitimate_single_class_nan(self):
        # Both predicted classes avoid sklearn's single-label confusion warning,
        # while the true labels still exercise undefined single-class metrics.
        rows = pd.DataFrame({'y_true': [1, 1], 'prediction': [0, 1], 'score': [0.2, 0.8]})
        values = v.metric_values(rows)
        self.assertEqual(values['sensitivity'], 0.5)
        self.assertEqual(values['MCC'], 0.0)
        for column in ('specificity', 'gap', 'ROC-AUC'):
            self.assertTrue(np.isnan(values[column]), column)
        expected = pd.DataFrame([{'subgroup': 'single', **values}])
        v.compare_table(expected.copy(), expected, ['subgroup'])
        for column in ('specificity', 'gap', 'ROC-AUC'):
            changed = expected.copy()
            changed.loc[0, column] = 0.0
            with self.assertRaises(AssertionError):
                v.compare_table(changed, expected, ['subgroup'])

    def test_oof_source_fields_and_coverage(self):
        for column, value in [('y_true', 0), ('formulation_id', 'wrong'), ('original_role', 'wrong'),
                              ('components_used', 99), ('fold', 1), ('model', 'unknown')]:
            with self.subTest(column=column):
                altered = self.oof.copy()
                altered.loc[0, column] = value
                with self.assertRaises(AssertionError):
                    self.verify(altered)
        for altered in (self.oof.iloc[1:], pd.concat([self.oof, self.oof.iloc[:1]])):
            with self.assertRaises(AssertionError):
                self.verify(altered)

    def test_every_metric_table_cell_and_key_coverage(self):
        for name, (frame, keys) in self.tables.items():
            v.compare_table(frame.copy(), frame, keys)
            indices = frame.drop_duplicates('subgroup').index if 'subgroup' in frame else frame.index[:1]
            for column in frame.columns:
                for index in indices:
                    with self.subTest(table=name, column=column, row=index):
                        changed = frame.copy()
                        value = changed.loc[index, column]
                        changed.loc[index, column] = (
                            'tampered' if isinstance(value, str) else
                            0.123 if pd.isna(value) else value + 1)
                        with self.assertRaises(AssertionError):
                            v.compare_table(changed, frame, keys)
            for changed in (frame.iloc[1:], pd.concat([frame, frame.iloc[:1]])):
                with self.assertRaises(AssertionError):
                    v.compare_table(changed, frame, keys)

    def test_metric_tables_end_to_end_tampering(self):
        for name, (frame, _) in self.tables.items():
            path = self.root / name
            original = path.read_bytes()
            changed = frame.copy()
            column = 'MCC_mean' if 'MCC_mean' in frame else 'MCC'
            changed.loc[changed.index[0], column] += 1
            changed.to_csv(path, index=False)
            with self.subTest(table=name), self.assertRaises(AssertionError):
                self.verify()
            path.write_bytes(original)

    def test_selection_fields(self):
        path = self.root / 'selected_model.json'
        for key, value in [('identity', 'stale'), ('representation', 'max'), ('mean_overall_MCC', 0.0),
                           ('selection_rule', 'wrong'), ('final_refit_performed', True)]:
            u.atomic_json(path, {**self.selected, key: value})
            with self.assertRaises(AssertionError):
                self.verify()
            u.atomic_json(path, self.selected)

    def test_post_audit_tampering_precedes_candidate_cache_or_fit(self):
        with patch.object(f, 'ROOT', self.root):
            _, _, binding = f.audit_binding()
            cfg = {'model': 'lr', 'representation': 'wmean', 'grid': self.cfg['grids']['lr'],
                   'audit_binding': binding}
            identity = u.hash_json(cfg)
            u.save_record(self.root / 'final_config.json', identity, cfg)
            path = self.root / 'final_development' / '0.json'
            path.parent.mkdir()
            u.save_record(path, identity, {'cached': True})
            self.assertEqual(f.candidate_job(cfg['grid'][0]), {'cached': True})
            names = (*self.cfg['input_hashes'], *self.cfg['code_hashes'], *v.OUTPUTS,
                     'comparison_config.json', 'comparison_verification.json',
                     'finalize_model.py', 'predict.py', 'verify_comparison.py')
            for name in names:
                with self.subTest(name=name):
                    target = self.root / name
                    original = target.read_bytes()
                    target.write_bytes(original + b' ')
                    with patch.object(u, 'fit_weighted', side_effect=RuntimeError('must not fit')) as fit:
                        with self.assertRaises(AssertionError):
                            f.candidate_job(cfg['grid'][0])
                        fit.assert_not_called()
                    target.write_bytes(original)


if __name__ == '__main__':
    unittest.main()
