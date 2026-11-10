"""Prediction with the selected model's saved aggregation and decision threshold."""
from __future__ import annotations
import argparse
from pathlib import Path
import joblib
import numpy as np
import pandas as pd

DEFAULT_MODEL = Path(__file__).resolve().parent / 'eye_A_final.joblib'


def load_bundle(path=DEFAULT_MODEL):
    bundle = joblib.load(path)
    if bundle['format'] != 'eye-A-grouped-v1':
        raise ValueError('Unsupported model bundle')
    if bundle['representation'] not in ('wmean', 'max'):
        raise ValueError('Unsupported aggregation')
    if bundle['pipeline'].n_features_in_ != len(bundle['feature_names']):
        raise ValueError('Model and feature schema disagree')
    if list(bundle['pipeline'].classes_) != [0, 1]:
        raise ValueError('Unexpected class orientation')
    if not 0 < bundle['threshold'] < 1:
        raise ValueError('Invalid decision threshold')
    return bundle


def predict_features(bundle, features):
    names = bundle['feature_names']
    if isinstance(features, pd.DataFrame):
        if not features.columns.is_unique:
            raise ValueError('Duplicate input columns')
        missing = [name for name in names if name not in features.columns]
        if missing:
            raise ValueError(f'Missing required features: {missing[:8]}')
        values = features.loc[:, names].to_numpy(dtype=float)
    else:
        values = np.asarray(features, dtype=float)
    if values.ndim != 2 or values.shape[1] != len(names) or not len(values):
        raise ValueError(f'Expected nonempty (n, {len(names)}) input')
    if np.isinf(values).any():
        raise ValueError('Infinite input features are invalid; NaNs use saved imputation')
    scores = bundle['pipeline'].predict_proba(values)[:, 1]
    if not np.isfinite(scores).all():
        raise ValueError('Nonfinite model output')
    return pd.DataFrame({'eye_A_score': scores,
                         'eye_A_prediction': (scores >= bundle['threshold']).astype(int),
                         'decision_threshold': bundle['threshold']})


def vectorize_components(bundle, smiles, percentages=None):
    """Use the bundle aggregation, not a caller-assumed default.

    Weighted mean needs relative amounts for multiple represented ingredients.
    Max ignores amounts. Undisclosed structures are never inferred.
    """
    from rdkit import Chem
    from rdkit.Chem import Descriptors
    from rdkit.Chem.rdFingerprintGenerator import GetMorganGenerator

    names = bundle['feature_names']
    method = bundle['representation']
    if method not in ('wmean', 'max'):
        raise ValueError('Unsupported aggregation')
    if not smiles or isinstance(smiles, str):
        raise ValueError('Provide a nonempty list of component SMILES')
    if percentages is None:
        if len(smiles) != 1 and method == 'wmean':
            raise ValueError('Multiple components require their relative amounts')
        weights = np.ones(len(smiles)) / len(smiles)
    else:
        amounts = np.asarray(percentages, dtype=float)
        if amounts.shape != (len(smiles),) or not np.isfinite(amounts).all():
            raise ValueError('Finite aligned component amounts are required')
        if (amounts < 0).any() or amounts.sum() <= 0:
            raise ValueError('Amounts must be nonnegative with a positive total')
        weights = amounts / amounts.sum()
    if names[:2048] != [f'fp_w_{i}' for i in range(2048)]:
        raise ValueError('Unexpected fingerprint schema')
    if not all(n.startswith('desc_') for n in names[2048:]):
        raise ValueError('Unexpected descriptor schema')
    descriptors = [n.removeprefix('desc_') for n in names[2048:]]
    generator = GetMorganGenerator(radius=2, fpSize=2048, includeChirality=False)
    rows = []
    for value in smiles:
        molecule = Chem.MolFromSmiles(value)
        if molecule is None or not molecule.GetNumAtoms():
            raise ValueError(f'Invalid or empty component SMILES: {value!r}')
        largest = max(Chem.GetMolFrags(molecule, asMols=True, sanitizeFrags=True),
                      key=lambda m: (m.GetNumHeavyAtoms(), Descriptors.MolWt(m)))
        values = Descriptors.CalcMolDescriptors(largest, missingVal=np.nan)
        rows.append(np.r_[generator.GetFingerprintAsNumPy(molecule),
                          [values[n] for n in descriptors]].astype(float))
    matrix = np.stack(rows)
    finite = np.isfinite(matrix)
    if method == 'max':
        pooled = np.max(np.where(finite, matrix, -np.inf), axis=0)
        pooled[~finite.any(axis=0)] = np.nan
    else:
        numerator = np.sum(np.where(finite, matrix, 0) * weights[:, None], axis=0)
        denominator = np.sum(finite * weights[:, None], axis=0)
        pooled = np.divide(numerator, denominator, out=np.full(matrix.shape[1], np.nan), where=denominator > 0)
    return pd.DataFrame([pooled], columns=names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=DEFAULT_MODEL)
    parser.add_argument('--input', type=Path, required=True, help='CSV vectorized with the saved aggregation')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve() or args.model.resolve() == args.output.resolve():
        raise ValueError('Output must not overwrite input or model')
    if args.output.exists():
        raise FileExistsError(args.output)
    frame = pd.read_csv(args.input, low_memory=False)
    result = predict_features(load_bundle(args.model), frame)
    if 'formulation_id' in frame:
        result.insert(0, 'formulation_id', frame.formulation_id.to_numpy())
    result.to_csv(args.output, index=False, encoding='utf-8-sig')
    print(f'Saved {len(result)} predictions to {args.output}')


if __name__ == '__main__':
    main()
