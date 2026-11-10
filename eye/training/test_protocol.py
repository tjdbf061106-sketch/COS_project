"""Fast behavior checks; does not rerun the full training search."""
import json
from pathlib import Path
import unittest
import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, matthews_corrcoef
import epa_harness as u
import predict

ROOT = Path(__file__).resolve().parent


class ProtocolTests(unittest.TestCase):
    def test_all_rows_group_disjoint_inner_and_outer(self):
        cfg = json.loads((ROOT / 'comparison_config.json').read_text(encoding='utf-8'))['payload']
        groups = np.asarray(cfg['groups'])
        for folds in cfg['splits'].values():
            self.assertEqual(sorted(i for f in folds for i in f['test']), list(range(673)))
            for f in folds:
                self.assertFalse(set(groups[f['train']]) & set(groups[f['test']]))
                self.assertEqual(sorted(i for p in f['inner'] for i in p['validation']), sorted(f['train']))
                for p in f['inner']:
                    self.assertEqual(set(p['train']) | set(p['validation']), set(f['train']))
                    self.assertFalse(set(groups[p['train']]) & set(groups[p['validation']]))

    def test_threshold_rule_against_bruteforce(self):
        scores = np.array([0.1, 0.2, 0.2, 0.4, 0.55, 0.7, 0.9])
        y = np.array([0, 1, 0, 0, 1, 0, 1])
        unique = np.unique(scores)
        candidates = []
        for cutoff in (unique[:-1] + unique[1:]) / 2:
            prediction = scores >= cutoff
            tn, fp, fn, tp = confusion_matrix(y, prediction, labels=[0, 1]).ravel()
            candidates.append((abs(tp * (tn + fp) - tn * (tp + fn)), -matthews_corrcoef(y, prediction), cutoff))
        self.assertEqual(u.threshold(scores, y), min(candidates)[2])
        for bad in (np.ones(7), np.full(7, np.nan)):
            with self.assertRaises(ValueError):
                u.threshold(bad, y)

    def test_preprocessing_fits_training_only(self):
        X = np.array([[0.0, np.nan], [2.0, np.nan], [4.0, np.nan], [6.0, np.nan]])
        y = np.array([0, 0, 1, 1])
        est = u.fit_weighted(u.build_estimator('lr', {'C': 1, 'solver': 'lbfgs', 'max_iter': 5000, 'tol': 1e-4}), X, y)
        before = est.named_steps['scaler'].mean_.copy()
        scores = u.predict_scores(est, np.array([[1e6, np.nan]]), 'lr')
        np.testing.assert_array_equal(before, [3, 0])
        np.testing.assert_array_equal(est.named_steps['scaler'].mean_, before)
        self.assertTrue(np.isfinite(scores).all())
        np.testing.assert_allclose(u.balanced_weights(np.array([0, 0, 0, 1])), [2 / 3, 2 / 3, 2 / 3, 2])

    def test_component_aggregation_uses_bundle_method(self):
        names = json.loads((ROOT / 'feature_names.json').read_text(encoding='utf-8'))
        bundle = {'feature_names': names, 'representation': 'wmean'}
        a = predict.vectorize_components(bundle, ['CCO']).to_numpy()[0]
        b = predict.vectorize_components(bundle, ['O']).to_numpy()[0]
        actual = predict.vectorize_components(bundle, ['CCO', 'O'], [1, 3]).to_numpy()[0]
        finite = np.isfinite(np.stack([a, b]))
        weights = np.array([0.25, 0.75])[:, None]
        numerator = (np.where(finite, np.stack([a, b]), 0) * weights).sum(axis=0)
        denominator = (finite * weights).sum(axis=0)
        expected = np.divide(numerator, denominator, out=np.full(len(a), np.nan), where=denominator > 0)
        np.testing.assert_allclose(actual, expected, equal_nan=True)
        bundle['representation'] = 'max'
        actual_max = predict.vectorize_components(bundle, ['CCO', 'O']).to_numpy()[0]
        np.testing.assert_allclose(actual_max, np.fmax(a, b), equal_nan=True)
        self.assertTrue(np.any(np.abs(actual_max - actual) > 1e-6))
        with self.assertRaises(ValueError):
            predict.vectorize_components(bundle, ['not_a_smiles'])
        bundle['representation'] = 'wmean'
        with self.assertRaises(ValueError):
            predict.vectorize_components(bundle, ['CCO', 'O'])

    def test_named_features_threshold_and_invalid_input(self):
        X = np.array([[0.0, 1.0], [1.0, 2.0], [3.0, 4.0], [4.0, 5.0]])
        y = np.array([0, 0, 1, 1])
        est = u.fit_weighted(u.build_estimator('lr', {'C': 1, 'solver': 'lbfgs', 'max_iter': 5000, 'tol': 1e-4}), X, y)
        cutoff = est.predict_proba(X)[0, 1]
        bundle = {'feature_names': ['a', 'b'], 'pipeline': est, 'threshold': cutoff}
        frame = pd.DataFrame(X, columns=['a', 'b'])
        result = predict.predict_features(bundle, frame[['b', 'a']])
        np.testing.assert_allclose(result.eye_A_score, est.predict_proba(X)[:, 1])
        self.assertEqual(result.eye_A_prediction.iloc[0], 1)
        with self.assertRaises(ValueError):
            predict.predict_features(bundle, frame[['a']])
        with self.assertRaises(ValueError):
            predict.predict_features(bundle, [[np.inf, 0]])


if __name__ == '__main__':
    unittest.main()
