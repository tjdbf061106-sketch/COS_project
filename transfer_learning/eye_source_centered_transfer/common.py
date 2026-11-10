"""Feature construction and the explicitly reconstructed transfer objective."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.special import expit

FORMAT = 'eye-source-centered-transfer-reconstruction-v1'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + '\n', encoding='utf-8')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalize_name(name):
    return ' '.join(name.casefold().split())


@lru_cache(maxsize=128)
def component_vector(smiles, names):
    from rdkit import Chem
    from rdkit.Chem import Descriptors
    from rdkit.Chem.rdFingerprintGenerator import GetMorganGenerator
    if list(names[:2048]) != [f'fp_w_{i}' for i in range(2048)]:
        raise ValueError('Unexpected source feature schema')
    if not all(name.startswith('desc_') for name in names[2048:]):
        raise ValueError('Unexpected descriptor schema')
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None or not molecule.GetNumAtoms():
        raise ValueError('Invalid mapped SMILES')
    largest = max(Chem.GetMolFrags(molecule, asMols=True, sanitizeFrags=True),
                  key=lambda m: (m.GetNumHeavyAtoms(), Descriptors.MolWt(m)))
    descriptor_values = Descriptors.CalcMolDescriptors(largest, missingVal=np.nan)
    fingerprint = GetMorganGenerator(radius=2, fpSize=2048, includeChirality=False)
    return np.r_[fingerprint.GetFingerprintAsNumPy(molecule),
                 [descriptor_values[n[5:]] for n in names[2048:]]].astype(float)


def vectorize(payload, names, mapping):
    if not isinstance(payload, dict) or not isinstance(payload.get('components'), list):
        raise ValueError('Expected an object with a components list')
    if not payload['components']:
        raise ValueError('Empty composition')
    aliases = {normalize_name(alias): entry for entry in mapping['entries']
               for alias in entry['aliases']}
    audit, selected = [], []
    for component in payload['components']:
        if not isinstance(component, dict):
            raise ValueError('Every component must be an object')
        name, amount = component.get('name'), component.get('amount_pct')
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Every component needs a name')
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ValueError('Every component needs a numeric amount_pct')
        if not np.isfinite(amount) or not 0 <= amount <= 100:
            raise ValueError('amount_pct must be finite and between 0 and 100')
        entry = aliases.get(normalize_name(name))
        audit.append({'name': name, 'amount_pct': float(amount),
                      'mapped_id': entry['id'] if entry else None,
                      'status': 'mapped_candidate' if entry else 'excluded_unmapped'})
        if entry and amount > 0:
            selected.append((entry, float(amount)))
    total = sum(row['amount_pct'] for row in audit)
    if not 0 < total <= 100.11 + 1e-9:
        raise ValueError('Total amount must be positive and at most 100.11%')
    if not selected:
        raise ValueError('No positive amount maps to the fixed ingredient whitelist')
    amounts = np.array([amount for _, amount in selected])
    weights = amounts / amounts.sum()
    matrix = np.stack([component_vector(entry['canonical_smiles'], tuple(names))
                       for entry, _ in selected])
    finite = np.isfinite(matrix)
    numerator = np.sum(np.where(finite, matrix, 0) * weights[:, None], axis=0)
    denominator = np.sum(finite * weights[:, None], axis=0)
    values = np.divide(numerator, denominator, out=np.full(len(names), np.nan),
                       where=denominator > 0)
    water = sum(amount for entry, amount in selected if entry['id'] == 'water')
    coverage = {'reported_total_pct': total, 'mapped_pct': float(amounts.sum()),
                'unmapped_pct': total - float(amounts.sum()),
                'mapped_nonwater_pct': float(amounts.sum()) - water,
                'unreported_pct': max(0., 100. - total),
                'mapped_component_count': len(selected), 'component_audit': audit}
    return values, coverage


def feature_group(vector):
    # Equal partial features must never appear in both train and test.
    stable = np.nan_to_num(np.round(vector, 12), nan=-1.234567890123e99)
    return hashlib.sha256(stable.astype('<f8').tobytes()).hexdigest()[:20]


def objective(theta, design, labels, anchor, regularization=1.0):
    labels = np.asarray(labels, dtype=int)
    counts = np.bincount(labels, minlength=2)
    if np.any(counts == 0):
        raise ValueError('Training requires both classes')
    weights = len(labels) / (2.0 * counts[labels])
    logits = design @ theta
    delta = theta - anchor
    loss = np.mean(weights * (np.logaddexp(0., logits) - labels * logits))
    gradient = design.T @ (weights * (expit(logits) - labels)) / len(labels)
    return float(loss + .5 * regularization * delta @ delta), gradient + regularization * delta


def score_bundle(bundle, payload):
    if bundle.get('format') != FORMAT or bundle.get('threshold') != 0.5:
        raise ValueError('Unsupported reconstructed model')
    features, coverage = vectorize(payload, bundle['feature_names'], bundle['mapping'])
    score = float(bundle['pipeline'].predict_proba(features[None, :])[0, 1])
    return {'formulation_id': payload.get('formulation_id'),
            'eye_transfer_score': score, 'eye_transfer_prediction': int(score >= .5),
            'decision_threshold': .5, 'positive_label': 'EPA I/II',
            'negative_label': 'EPA III/IV', 'coverage': coverage,
            'model_status': 'reconstructed research model; original artifact not recovered',
            'note': 'Only whitelist-mapped partial composition is used. Score is not a calibrated safety probability.'}
