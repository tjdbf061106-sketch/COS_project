"""Portable prediction for the saved Eye A model, including its chosen cutoff."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

DEFAULT_MODEL = Path(__file__).resolve().parent / 'eye_A_LR_wmean.joblib'


def load_bundle(path=DEFAULT_MODEL):
    bundle = joblib.load(path)
    if bundle['format'] != 'eye-A-lr-wmean-v1':
        raise ValueError('Unsupported model bundle')
    if bundle['pipeline'].n_features_in_ != len(bundle['feature_names']):
        raise ValueError('Model and feature schema disagree')
    if list(bundle['pipeline'].classes_) != [0, 1]:
        raise ValueError('Unexpected class orientation')
    if not 0 < bundle['threshold'] < 1:
        raise ValueError('Invalid decision threshold')
    return bundle


def predict_features(bundle, features):
    """Named DataFrames are reordered; arrays must already follow feature_names."""
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
    # This is a model score, not a calibrated real-world irritation probability.
    scores = bundle['pipeline'].predict_proba(values)[:, 1]
    if not np.isfinite(scores).all():
        raise ValueError('Nonfinite model output')
    return pd.DataFrame({
        'eye_A_score': scores,
        'eye_A_prediction': (scores >= bundle['threshold']).astype(int),
        'decision_threshold': bundle['threshold'],
    })


def vectorize_components(feature_names, smiles, percentages=None):
    """Encode represented ingredients using the same audited training recipe.

    Percentages are normalized over represented ingredients. A lone component
    may omit its percentage. Multiple components require explicit amounts.
    No undisclosed ingredient composition is inferred.
    """
    from rdkit import Chem
    from rdkit.Chem import Descriptors
    from rdkit.Chem.rdFingerprintGenerator import GetMorganGenerator

    if not smiles or isinstance(smiles, str):
        raise ValueError('Provide a nonempty list of component SMILES')
    if percentages is None:
        if len(smiles) != 1:
            raise ValueError('Multiple components require their relative amounts')
        weights = np.ones(1)
    else:
        amounts = np.asarray(percentages, dtype=float)
        if amounts.shape != (len(smiles),) or not np.isfinite(amounts).all():
            raise ValueError('Finite aligned component amounts are required')
        if (amounts < 0).any() or amounts.sum() <= 0:
            raise ValueError('Amounts must be nonnegative with a positive total')
        weights = amounts / amounts.sum()
    if feature_names[:2048] != [f'fp_w_{i}' for i in range(2048)]:
        raise ValueError('Unexpected fingerprint schema')
    if not all(n.startswith('desc_') for n in feature_names[2048:]):
        raise ValueError('Unexpected descriptor schema')
    descriptors = [n.removeprefix('desc_') for n in feature_names[2048:]]
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
    numerator = np.sum(np.where(finite, matrix, 0) * weights[:, None], axis=0)
    denominator = np.sum(finite * weights[:, None], axis=0)
    pooled = np.divide(numerator, denominator,
                       out=np.full(matrix.shape[1], np.nan), where=denominator > 0)
    return pd.DataFrame([pooled], columns=feature_names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', '--checkpoint', type=Path, default=DEFAULT_MODEL)
    parser.add_argument('--input', type=Path, required=True,
                        help='Component JSON or vectorized CSV')
    parser.add_argument('--output', type=Path, help='New output file; JSON defaults to stdout')
    args = parser.parse_args()
    if args.output is not None:
        if args.input.resolve() == args.output.resolve() or args.model.resolve() == args.output.resolve():
            raise ValueError('Output must not overwrite input or model')
        if args.output.exists():
            raise FileExistsError(args.output)
    bundle = load_bundle(args.model)
    if args.input.suffix.lower() == '.json':
        payload = json.loads(args.input.read_text(encoding='utf-8-sig'))
        result = predict_components(bundle, payload)
        serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output is None:
            print(serialized)
        else:
            with args.output.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(serialized + '\n')
        return
    if args.output is None:
        parser.error('--output is required for vectorized CSV input')
    frame = pd.read_csv(args.input, low_memory=False)
    result = predict_features(bundle, frame)
    if 'formulation_id' in frame:
        result.insert(0, 'formulation_id', frame.formulation_id.to_numpy())
    result.to_csv(args.output, index=False, encoding='utf-8-sig', mode='x')
    print(f'Saved {len(result)} predictions to {args.output}')


def predict_components(bundle, payload):
    """Accept the same explicit SMILES/amount JSON fields as the skin package."""
    if not isinstance(payload, dict):
        raise ValueError('Expected a JSON object with components')
    components = payload.get('components')
    if not isinstance(components, list) or not components:
        raise ValueError('Provide a nonempty components list')
    smiles, amounts = [], []
    for component in components:
        if not isinstance(component, dict):
            raise ValueError('Each component must be an object')
        structure = component.get('canonical_smiles')
        amount = component.get('amount_pct')
        if not isinstance(structure, str) or not structure.strip():
            raise ValueError('Every component requires canonical_smiles')
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ValueError('Every component requires a numeric amount_pct')
        if not np.isfinite(amount) or not 0 <= amount <= 100:
            raise ValueError('amount_pct must be finite and between 0 and 100')
        smiles.append(structure)
        amounts.append(amount)
    total = sum(amounts)
    if total <= 0 or total > 100 + 1e-9:
        raise ValueError('Total represented amount must be greater than 0 and at most 100%')
    frame = vectorize_components(bundle['feature_names'], smiles, amounts)
    prediction = predict_features(bundle, frame).iloc[0]
    return {
        'eye_A_score': float(prediction.eye_A_score),
        'eye_A_prediction': int(prediction.eye_A_prediction),
        'decision_threshold': float(prediction.decision_threshold),
        'predicted_label_meaning': 'EPA I/II' if prediction.eye_A_prediction else 'EPA III/IV',
        'n_components_used': len(components),
        'represented_amount_pct': total,
        'note': 'Research model score; not a calibrated irritation probability or cosmetic safety assessment.',
    }


if __name__ == '__main__':
    main()
