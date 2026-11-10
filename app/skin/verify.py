"""Run: python skin/verify.py. Checks execution reproducibility, not accuracy."""
from pathlib import Path
from importlib.metadata import version
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile

import joblib

root = Path(__file__).resolve().parent
for line in (root.parent / 'requirements.txt').read_text().splitlines():
    if not line.strip() or line.startswith('#'):
        continue
    name, expected = line.split('==')
    actual = version(name)
    # PEP 440 permits omitted leading zeroes in numeric version segments.
    assert tuple(map(int, actual.split('.'))) == tuple(map(int, expected.split('.'))), (name, actual, expected)
metadata = json.loads((root / 'metadata.json').read_text(encoding='utf-8'))
assert hashlib.sha256((root / 'skin_rf_checkpoint.joblib').read_bytes()).hexdigest() == metadata['checkpoint_sha256']
ck = joblib.load(root / 'skin_rf_checkpoint.joblib')
assert len(ck['feature_cols']) == metadata['input_features']
assert len(set(ck['feature_cols'])) == len(ck['feature_cols'])
assert len(ck['nz_filter_keep']) == len(ck['feature_cols'])
assert int(ck['nz_filter_keep'].sum()) == metadata['selected_features'] == ck['model'].n_features_in_
assert float(ck['threshold']) == metadata['threshold']
assert list(ck['model'].classes_) == [0, 1]
cases = json.loads((root / 'smoke_test_cases.json').read_text(encoding='utf-8'))
with tempfile.TemporaryDirectory(prefix='cos_skin_verify_') as temp:
    work = Path(temp)
    for name in ['predict.py', 'skin_rf_checkpoint.joblib']:
        shutil.copy2(root / name, work / name)
    for case in cases:
        target = work / Path(case['input']).name
        shutil.copy2(root / case['input'], target)
        result = subprocess.run(
            [sys.executable, '-I', str(work / 'predict.py'), '--input', str(target)],
            cwd=work, check=True, capture_output=True, text=True, encoding='utf-8',
        )
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        assert json.loads(result.stdout) == case['expected'], case['input']
    invalid = [
        {'components': []},
        {'components': [{'canonical_smiles': 'CCO', 'amount_pct': -1}]},
        {'components': [{'canonical_smiles': 'CCO', 'amount_pct': 101}]},
        {'components': [{'name': 'unknown', 'amount_pct': 10}]},
    ]
    for payload in invalid:
        path = work / 'invalid.json'
        path.write_text(json.dumps(payload), encoding='utf-8')
        result = subprocess.run(
            [sys.executable, '-I', str(work / 'predict.py'), '--input', str(path)],
            cwd=work, capture_output=True,
        )
        assert result.returncode != 0 and b'ValueError' in result.stderr, result
print(f'PASS: dependency versions, hash, feature contract, {len(cases)} portable predictions, {len(invalid)} invalid inputs')
